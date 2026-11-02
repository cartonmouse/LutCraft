"""Render purchased photo candidates for review, without enabling any LUT."""
import argparse
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import PyOpenColorIO as ocio
from PIL import Image, ImageCms, ImageDraw, ImageOps

from make_previews import font, save_png


def sheet(original, entries, output, pack, strength, icc):
    width, gap, margin, header, label = 300, 18, 30, 150, 76
    height = round(width * original.height / original.width)
    cards = [("原图", "归一化至 sRGB", original)]
    for entry in entries:
        with Image.open(output / entry[f"preview_{strength}"]["path"]) as im:
            cards.append((entry["name"], entry["style_zh"], im.copy()))
    cols = 3 if pack == "xh-5219" else 4
    rows = (len(cards) + cols - 1) // cols
    canvas = Image.new("RGB", (margin * 2 + cols * width + (cols - 1) * gap,
                               header + rows * (height + label + gap) + 26), "#f2f4f3")
    draw = ImageDraw.Draw(canvas)
    title = "林馆长 · 709 拍照候选" if pack == "ling-iphone-2" else "XH 5219 · 标准版照片候选"
    draw.text((margin, 24), title, font=font(30), fill="#163d35")
    draw.text((margin, 73), f"LUT {strength}%  ·  同一张样片  ·  无额外基础调色", font=font(21), fill="#445950")
    draw.text((margin, 106), "sRGB 直接套用试验；效果预览不代表输入兼容性已确认", font=font(18), fill="#6e685c")
    for index, (name, style, im) in enumerate(cards):
        x = margin + index % cols * (width + gap)
        y = header + index // cols * (height + label + gap)
        canvas.paste(im.resize((width, height), Image.Resampling.LANCZOS), (x, y))
        draw.rectangle((x, y + height, x + width, y + height + label), fill="white")
        name = name.removeprefix("林馆长").replace("709", "").replace("N-CINE1", "CINE1")
        size = 22
        while draw.textlength(name, font=font(size)) > width - 20 and size > 12:
            size -= 1
        draw.text((x + 10, y + height + 12), name, font=font(size), fill="#183d36")
        draw.text((x + 10, y + height + 44), "原图" if index == 0 else f"{index:02d}  ·  {strength}%", font=font(18), fill="#6a7973")
    path = output / f"{pack}-{strength}.jpg"
    canvas.save(path, quality=94, subsampling=0, icc_profile=icc)
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-edge", type=int, default=1200)
    args = parser.parse_args()
    if args.max_edge < 64:
        parser.error("--max-edge must be at least 64")
    root, output = args.library.resolve(), args.output.resolve()
    if output.exists():
        raise SystemExit("Output exists; choose a new directory.")
    catalog_path = root / "photo-candidates.json"
    items = json.loads(catalog_path.read_text())["items"]
    if not items or any(i["group"] != "photo-candidates" or not i["engine_format_supported"] for i in items):
        raise ValueError("Only format-supported photo candidates may enter this preview")
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    icc = srgb.tobytes()
    with Image.open(args.source) as source:
        original_size = source.size
        image = ImageOps.exif_transpose(source)
        source_icc = source.info.get("icc_profile")
        source_profile = "Assumed sRGB (untagged)"
        if source_icc:
            profile = ImageCms.ImageCmsProfile(io.BytesIO(source_icc))
            source_profile = ImageCms.getProfileDescription(profile).strip()
            image = ImageCms.profileToProfile(image, profile, srgb, outputMode="RGB")
        else:
            image = image.convert("RGB")
        image.thumbnail((args.max_edge, args.max_edge), Image.Resampling.LANCZOS)
    output.mkdir(parents=True)
    original = save_png(image, output / "original.png", icc)
    pixels = np.asarray(image).astype(np.float32) / 255
    entries = []
    for index, item in enumerate(items, 1):
        path = (root / item["path"]).resolve()
        if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != item["original_sha256"]:
            raise ValueError("LUT path or checksum mismatch")
        transform = ocio.FileTransform(src=str(path), interpolation=ocio.INTERP_TETRAHEDRAL)
        cpu = ocio.Config.CreateRaw().getProcessor(transform).getDefaultCPUProcessor()
        result = pixels.copy()
        cpu.applyRGB(result)
        if not np.isfinite(result).all():
            raise ValueError("Non-finite LUT output")
        entry = {"id": item["id"], "name": item["name"], "pack": item["pack"], "style_zh": item["style_zh"],
                 "lut_sha256": item["original_sha256"], "compatibility": "unconfirmed"}
        for strength in (50, 100):
            weight = strength / 100
            rendered = np.rint(np.clip(pixels * (1 - weight) + result * weight, 0, 1) * 255).astype(np.uint8)
            path = output / f"{index:02d}-{strength}.png"
            entry[f"preview_{strength}"] = save_png(Image.fromarray(rendered), path, icc)
            with Image.open(path) as saved:
                if saved.size != image.size or not saved.info.get("icc_profile") or not np.array_equal(np.asarray(saved), rendered):
                    raise ValueError("Saved preview differs from the calculated result")
        entries.append(entry)
    sheets = []
    for pack in sorted({i["pack"] for i in entries}):
        for strength in (50, 100):
            sheets.append({"pack": pack, "strength": strength,
                           **sheet(image, [i for i in entries if i["pack"] == pack], output, pack, strength, icc)})
    manifest = {"schema_version": 1, "count": len(entries), "source_path": str(args.source.resolve()),
                "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
                "source_icc_description": source_profile, "original_size": original_size, "preview_size": image.size,
                "catalog_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
                "working_space": "sRGB encoded RGB; exploratory direct application, not a compatibility confirmation",
                "engine": "OpenColorIO " + ocio.__version__, "interpolation": "tetrahedral",
                "strengths": [0.5, 1.0], "extra_adjustments": "none", "original": original,
                "contact_sheets": sheets, "items": entries}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    lines = ["# 购买 LUT 照片候选预览", "", "同一张项目样片，完整画幅；归一化为 sRGB 后直接套用 LUT，未额外调曝光、对比度或白平衡。", "",
             "这是 sRGB 管线下的试用效果，不代表已经确认 LUT 的输入/输出空间；不能作为 Log、Adobe RGB 或人像适用性的验证。", "",
             "[原图](original.png) · [完整计算记录](manifest.json)", ""]
    for s in sheets:
        lines.append(f"- [{s['pack']} · {s['strength']}% 总览]({s['path']})")
    lines += ["", "| 名称 | 50% | 100% |", "|---|---|---|"]
    for entry in entries:
        lines.append(f"| {entry['name']} | [查看]({entry['preview_50']['path']}) | [查看]({entry['preview_100']['path']}) |")
    (output / "README.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"previewed_luts": len(entries), "images": len(entries) * 2, "contact_sheets": len(sheets), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
