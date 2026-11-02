"""Stateless LUT rendering shared by OpenClaw and the local result viewer."""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pyvips

from .errors import AppError
from .imaging import inspect, render
from .luts import inspect_cube, processor, require_engine, ocio
from .clf import inspect_clf
from .schemas import Recipe, LutReference

ROOT = Path(__file__).resolve().parents[2]
MAX_FILES = 10
MAX_BYTES = 10 * 1024 * 1024


def catalog():
    root = ROOT / "lut-library"
    data = json.loads((root / "catalog.json").read_text())
    return [{"id": row["id"], "name": row["name"], "description": row["style_zh"],
             "tags": row["tags"], "input_profile": row["input_profile"],
             "path": row["path"], "sha256": row["technical"]["sha256"], "format": row["technical"]["lut_type"]}
            for row in data["items"] if row.get("enabled", True) and (root / row["path"]).is_file()]


def load_catalog_processor(row):
    """Validate a bundled transform before use, without reading any photos."""
    require_engine()
    lut_path = (ROOT / "lut-library" / row["path"]).resolve()
    if not lut_path.is_relative_to((ROOT / "lut-library").resolve()):
        raise AppError("lut_path", "LUT 路径无效。")
    raw = lut_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise AppError("lut_changed", "LUT 文件校验失败，已停止调色。")
    if lut_path.suffix.lower() == ".clf":
        inspect_clf(raw)
    elif lut_path.suffix.lower() == ".cube":
        inspect_cube(raw, bundled=True)
    elif lut_path.suffix.lower() == ".png" and row.get("format") == "HaldCLUT":
        from .hald import processor as hald_processor
        return hald_processor(str(lut_path), row["sha256"])
    else:
        raise AppError("lut_format", "运行库转换格式不受支持。")
    return processor(str(lut_path), row["sha256"], ocio.__version__)


def read_input(path):
    path = Path(path).resolve()
    if path.stat().st_size > 256_000:
        raise AppError("input_size", "调用数据过大。")
    data = json.loads(path.read_text())
    value = data.get("input", {})
    style = value.get("user_prompt", "")
    attachments = value.get("attachments", [])
    if not isinstance(style, str) or not 1 <= len(style.strip()) <= 1000:
        raise AppError("style_required", "请描述想要的风格，最多 1000 字。")
    if not isinstance(attachments, list) or not 1 <= len(attachments) <= MAX_FILES:
        raise AppError("photos_required", "请提供 1–10 张 JPEG 或 PNG 图片。")
    files = []
    for item in attachments:
        if not isinstance(item, str):
            raise AppError("attachment_invalid", "图片附件路径无效。")
        source = Path(item).resolve()
        # Both production /oasn/in/files and local invocation fixtures use this
        # boundary. Never discover files by scanning the input directory.
        if not source.is_relative_to(path.parent) or not source.is_file():
            raise AppError("attachment_scope", "附件必须属于本次调用的输入目录。")
        if source.stat().st_size > MAX_BYTES:
            raise AppError("image_size", "每张图片不能超过 10 MB。")
        files.append(source)
    if len(set(files)) != len(files):
        raise AppError("duplicate_photo", "同一张图片不能重复传入。")
    return style.strip(), files


def image_summary(path):
    meta = inspect(path)
    im = pyvips.Image.thumbnail(str(path), 96, height=96, size="down").colourspace("srgb")
    rgb = im.extract_band(0, n=3).cast("float")
    pixels = np.frombuffer(rgb.write_to_memory(), dtype=np.float32).reshape(-1, 3)
    if im.format == "ushort":
        pixels /= 257
    pixels = np.clip(pixels / 255, 0, 1)
    luma = pixels @ np.array([.2126, .7152, .0722])
    return {**meta, "mean_brightness": round(float(luma.mean()), 3),
            "shadow_fraction": round(float((luma < .15).mean()), 3),
            "highlight_fraction": round(float((luma > .85).mean()), 3),
            "mean_rgb": [round(float(v), 3) for v in pixels.mean(axis=0)]}


def describe_request(input_path):
    style, paths = read_input(input_path)
    return {"user_style": style, "photos": [{"index": i + 1, **image_summary(p)} for i, p in enumerate(paths)],
            "luts": [{k: v for k, v in row.items() if k not in ("path", "sha256")} for row in catalog()],
            "capabilities": "真实 3D LUT 调色；图像统计不等于识别人像或场景；不支持局部编辑、加颗粒、换背景。"}


def apply_lut(input_path, output_dir, lut_id, strength, reason):
    style, files = read_input(input_path)
    if not isinstance(strength, (float, int)) or not math.isfinite(strength) or not 0 < strength <= 1:
        raise AppError("strength_invalid", "LUT 强度必须大于 0 且不超过 1。")
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
        raise AppError("reason_invalid", "请提供简短的 LUT 选择依据。")
    row = next((row for row in catalog() if row["id"] == lut_id), None)
    if not row:
        raise AppError("lut_unknown", "所选 LUT 不在当前可用库中。")
    transform = load_catalog_processor(row)
    metas = [inspect(file) for file in files]
    fingerprint = hashlib.sha256(json.dumps([style, lut_id, strength,
        [hashlib.sha256(file.read_bytes()).hexdigest() for file in files]], ensure_ascii=False).encode()).hexdigest()
    output_dir = Path(output_dir).resolve()
    if output_dir == Path(input_path).resolve().parent or any(p.is_relative_to(output_dir) for p in files):
        raise AppError("output_scope", "输出目录不能覆盖输入目录。")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "result.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        if previous.get("fingerprint") != fingerprint:
            raise AppError("already_processed", "本次已生成结果；修改风格请发起新任务。", 409)
        if all((output_dir / p["filename"]).is_file() for p in previous["photos"]):
            return previous
        raise AppError("result_missing", "已有结果文件不完整，请发起新任务。", 409)
    recipe = Recipe(lut=LutReference(id=row["id"], name=row["name"], sha256=row["sha256"], strength=strength)).model_dump()
    results = []
    for index, (source, meta) in enumerate(zip(files, metas), 1):
        filename = f"photo-{index:02d}-graded.{meta['format']}"
        target = output_dir / filename
        render(source, target, recipe, lut_processor=transform)
        results.append({"index": index, "filename": filename, "path": str(target),
                        "bytes": target.stat().st_size, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                        **inspect(target)})
    result = {"schema_version": "lut.result.v1", "status": "completed", "fingerprint": fingerprint,
              "style": style, "lut": {"id": lut_id, "name": row["name"], "strength": strength},
              "reason": reason.strip(), "photos": results}
    temp = output_dir / ".result.tmp"
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    temp.replace(manifest_path)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["inspect", "apply"])
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    parser.add_argument("--lut-id")
    parser.add_argument("--strength", type=float, default=.75)
    parser.add_argument("--reason", default="")
    args = parser.parse_args()
    try:
        if args.action == "inspect":
            result = describe_request(args.input)
        else:
            if not args.output or not args.lut_id:
                parser.error("apply requires --output and --lut-id")
            result = apply_lut(args.input, args.output, args.lut_id, args.strength, args.reason)
        print(json.dumps(result, ensure_ascii=False))
    except (AppError, ValueError, OSError, pyvips.Error) as exc:
        message = exc.message if isinstance(exc, AppError) else "无法读取或处理本次图片，请检查图片与调用数据。"
        print(json.dumps({"status": "failed", "code": getattr(exc, "code", "processing_failed"), "message": message}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
