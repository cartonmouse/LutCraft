"""Render one photograph with every catalogued LUT at 100% and 50%.

Run with the project's .venv Python (Pillow, NumPy and OpenColorIO).
The LUT files and application albums are never modified.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import PyOpenColorIO as ocio
from PIL import Image, ImageCms, ImageDraw, ImageFont, ImageOps

from library import ROOT, scan

ORDER = ["iwltbap-aspen", "iwltbap-sedona", "iwltbap-renata", "iwltbap-humble",
         "iwltbap-coronado", "iwltbap-blade-runner-2049", "iwltbap-k64",
         "xmosaique-warm-instant", "xmosaique-dusty-slide", "xmosaique-silver-mono",
         "xmosaique-infrared-mono"]


def font(size, bold=False):
    path = "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
    return ImageFont.truetype(path, size)


def save_png(image, path, icc):
    image.save(path, icc_profile=icc, compress_level=6)
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def contact_sheet(original, entries, out, strength, icc):
    margin, gap, width, header, label = 40, 20, 360, 162, 92
    height = round(width * original.height / original.width)
    cards = [{"name": "Original", "style_zh": "原图 / 色彩归一化", "image": original}]
    for entry in entries:
        cards.append({"name": entry["name"].removeprefix("IWLTBAP "),
                      "style_zh": entry["style_zh"],
                      "image": Image.open(out / entry[f"preview_{strength}"]["path"])})
    cols = 4
    rows = (len(cards) + cols - 1) // cols
    canvas = Image.new("RGB", (margin * 2 + cols * width + (cols - 1) * gap,
                                header + rows * (height + label) + (rows - 1) * gap + 70), "#f1f2f4")
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 24), "LUT LIBRARY  /  SAME PHOTO", font=font(18, True), fill="#50716c")
    draw.text((margin, 55), f"原图 + {len(entries)} 款 LUT · 效果对比", font=font(40), fill="#20272d")
    draw.text((margin, 111), f"统一强度 {strength}%  ·  无额外曝光、白平衡或饱和度调整  ·  完整画幅", font=font(22), fill="#58646d")
    for index, card in enumerate(cards):
        x = margin + (index % cols) * (width + gap)
        y = header + (index // cols) * (height + label + gap)
        photo = card["image"].resize((width, height), Image.Resampling.LANCZOS)
        canvas.paste(photo, (x, y))
        draw.rectangle((x, y + height, x + width, y + height + label), fill="white")
        draw.rounded_rectangle((x + 12, y + height + 16, x + 52, y + height + 48), radius=7, fill="#e5ece9")
        draw.text((x + 18, y + height + 21), f"{index:02}", font=font(18, True), fill="#345b51")
        title_font = font(24, True)
        if draw.textlength(card["name"], font=title_font) > width - 76:
            title_font = font(20, True)
        draw.text((x + 64, y + height + 19), card["name"], font=title_font, fill="#20272d")
        draw.text((x + 14, y + height + 56), card["style_zh"], font=font(20), fill="#59666e")
    draw.text((margin, canvas.height - 42), "同一张原始照片  |  基于原始 .cube 文件计算  |  sRGB", font=font(19), fill="#69757b")
    path = out / f"comparison-{strength}.jpg"
    canvas.save(path, quality=95, subsampling=0, icc_profile=icc)
    for card in cards[1:]:
        card["image"].close()
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "previews" / "pink-grass-2026-10-28")
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit("Output folder is not empty; select a new --output directory.")
    out.mkdir(parents=True, exist_ok=True)
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    icc = srgb.tobytes()
    with Image.open(args.source) as source:
        image = ImageOps.exif_transpose(source)
        input_icc = source.info.get("icc_profile")
        profile_name = "Assumed sRGB (untagged)"
        if input_icc:
            profile = ImageCms.ImageCmsProfile(io.BytesIO(input_icc))
            profile_name = ImageCms.getProfileDescription(profile).strip()
            image = ImageCms.profileToProfile(image, profile, srgb, outputMode="RGB")
        else:
            image = image.convert("RGB")
    pixels = np.asarray(image).astype(np.float32) / 255.0
    original = save_png(image, out / "00-original.png", icc)
    items = scan()
    items.sort(key=lambda x: ORDER.index(x["id"]) if x["id"] in ORDER else len(ORDER))
    entries = []
    numeric_digests = set()
    for index, item in enumerate(items, 1):
        transform = ocio.FileTransform(src=str(ROOT / item["path"]), interpolation=ocio.INTERP_TETRAHEDRAL)
        processor = ocio.Config.CreateRaw().getProcessor(transform).getDefaultCPUProcessor()
        graded = pixels.copy()
        processor.applyRGB(graded)
        if not np.isfinite(graded).all():
            raise ValueError("Non-finite render: " + item["id"])
        entry = {"id": item["id"], "name": item["name"], "style_zh": item["style_zh"],
                 "lut_path": item["path"], "lut_sha256": item["technical"]["sha256"],
                 "number": index, "grid_size": item["technical"]["grid_size"]}
        for strength in (100, 50):
            weight = strength / 100
            blended = graded if strength == 100 else pixels * (1 - weight) + graded * weight
            result = np.rint(np.clip(blended, 0, 1) * 255).astype(np.uint8)
            if strength == 100:
                digest = hashlib.sha256(result.tobytes()).hexdigest()
                if digest in numeric_digests or np.array_equal(result, np.asarray(image)):
                    raise ValueError("Duplicate/unchanged render: " + item["id"])
                numeric_digests.add(digest)
            path = out / f"{index:02}-{item['id']}-{strength}.png"
            entry[f"preview_{strength}"] = save_png(Image.fromarray(result), path, icc)
            # Verify lossless encoding, dimensions and color metadata on the delivered file.
            with Image.open(path) as saved:
                if saved.size != image.size or not saved.info.get("icc_profile") or not np.array_equal(np.asarray(saved), result):
                    raise ValueError("Saved preview verification failed: " + str(path))
        entries.append(entry)
        print(f"Rendered {index}/{len(items)}: {item['name']}", flush=True)
    sheets = {str(s): contact_sheet(image, entries, out, s, icc).name for s in (100, 50)}
    manifest = {
        "schema_version": 1, "source_path": str(args.source.resolve()),
        "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "source_icc_description": profile_name, "working_space": "sRGB encoded RGB",
        "width": image.width, "height": image.height, "original": original,
        "engine": "OpenColorIO " + ocio.__version__, "interpolation": "tetrahedral",
        "strengths": [1.0, 0.5], "extra_adjustments": "none", "contact_sheets": sheets,
        "count": len(entries), "items": entries,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    lines = ["# 同图 LUT 效果预览", "", "使用同一张原始照片，保留完整画幅；统一转换至 sRGB。未额外调整曝光、白平衡、对比度或饱和度。", "",
             "[100% 强度总览](comparison-100.jpg) · [50% 强度总览](comparison-50.jpg) · [原图](00-original.png)", "",
             "| 编号 | LUT | 风格 | 100% | 50% |", "|---|---|---|---|---|"]
    for item in entries:
        lines.append(f"| {item['number']:02} | {item['name']} | {item['style_zh']} | [查看]({item['preview_100']['path']}) | [查看]({item['preview_50']['path']}) |")
    lines += ["", f"单张预览为 {image.width}×{image.height} 无损 PNG；总览为缩小后的 JPEG。处理过程、输入文件与 LUT 校验值记录在 manifest.json。", "",
              "此预览展示 LUT 对这张照片的效果。不同照片的光线和原始色彩会影响结果。", ""]
    (out / "README.md").write_text("\n".join(lines))
    print(f"Verified {len(entries)} distinct LUT renders at two strengths: {out}")


if __name__ == "__main__":
    main()
