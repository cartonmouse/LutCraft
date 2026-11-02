"""Exercise the production renderer on the approved 81 CLFs and local photos.

No network, acquisition, catalog mutation or overwrite of historical previews.
Saves real PNG results, smaller browsing copies, metrics and an offline viewer.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "backend"))
from app.imaging import render
from app.single_pass import load_catalog_processor


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def thumbnail(path, target):
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((420, 420), Image.Resampling.LANCZOS)
        im.save(target, quality=90, subsampling=0)


class AuditProcessor:
    """Observe the same blocks as production, before its blend and clamp."""
    def __init__(self, cpu, strength):
        self.cpu, self.strength, self.expected, self.inputs = cpu, strength, [], []
        self.outside = 0

    def applyRGB(self, block):
        before = block.copy()
        self.inputs.append(before)
        self.cpu.applyRGB(block)
        if not np.isfinite(block).all():
            raise ValueError("Non-finite rendered photo pixels")
        if self.strength < 1:
            blended = block.copy()
            blended *= self.strength
            blended += before * (1 - self.strength)
        else:
            blended = block
        self.outside += int(((blended < 0) | (blended > 1)).any(axis=2).sum())
        self.expected.append(np.rint(np.clip(blended, 0, 1) * 255).astype(np.uint8))


def measure(result, base, outside):
    valid = base[:, :, 3] > 0 if base.shape[2] == 4 else np.ones(base.shape[:2], dtype=bool)
    a, b = base[:, :, :3][valid] / 255., result[:, :, :3][valid] / 255.
    y0, y1 = a @ [.2126, .7152, .0722], b @ [.2126, .7152, .0722]
    new_black = float(((y0 > .02) & (b.max(axis=1) <= 1 / 255)).mean())
    new_white = float(((y0 < .98) & (b.min(axis=1) >= 254 / 255)).mean())
    return {"new_near_black_fraction": new_black, "new_near_white_fraction": new_white,
            "mean_encoded_luma_change": float(y1.mean() - y0.mean()),
            "mean_abs_rgb_change": float(np.abs(a - b).mean()),
            "channel_clip_before_output_fraction": outside / (base.shape[0] * base.shape[1]),
            "luma_p05_p50_p95": np.quantile(y1, [.05, .5, .95]).tolist(),
            "baseline_luma_p05_p50_p95": np.quantile(y0, [.05, .5, .95]).tolist(),
            "mean_rgb": b.mean(axis=0).tolist(),
            "attention": new_black > .01 or new_white > .005,
            "attention_basis": "new near-black >1% or new near-white >0.5%; descriptive flag, not aesthetic failure"}


def process_lut(row, sources, output):
    folder = output / row["id"]
    folder.mkdir()
    cpu = load_catalog_processor({**row, "sha256": row["technical"]["sha256"]})
    results = []
    for source in sources:
        with Image.open(output / source["baseline"]) as im:
            baseline = np.asarray(im).copy()
        for strength in (.5, 1.):
            filename = f"{source['id']}-{round(strength * 100)}.png"
            path = folder / filename
            audit = AuditProcessor(cpu, strength)
            recipe = {"lut": {"id": row["id"], "name": row["name"],
                              "sha256": row["technical"]["sha256"], "strength": strength}}
            render(Path(source["path"]), path, recipe, max_edge=1280, lut_processor=audit)
            with Image.open(path) as im:
                pixels = np.asarray(im).copy()
                size = list(im.size)
            expected = np.concatenate(audit.expected, axis=0)
            if pixels.shape != baseline.shape or not np.array_equal(pixels[:, :, :3], expected):
                raise ValueError("Saved PNG differs from production float32 blend/clamp: " + str(path))
            if pixels.shape[2] == 4 and not np.array_equal(pixels[:, :, 3], baseline[:, :, 3]):
                raise ValueError("Alpha changed")
            # Match each output against the same actual pre-LUT working pixels.
            working = np.concatenate(audit.inputs, axis=0)
            base_rgb = np.rint(np.clip(working, 0, 1) * 255).astype(np.uint8)
            if not np.array_equal(base_rgb, baseline[:, :, :3]):
                raise ValueError("Baseline and LUT preprocessing differ")
            thumb = path.with_suffix(".jpg")
            thumbnail(path, thumb)
            metrics = measure(pixels, baseline, audit.outside)
            results.append({"sample_id": source["id"], "strength": strength,
                            "path": path.relative_to(output).as_posix(), "sha256": sha(path),
                            "thumbnail": thumb.relative_to(output).as_posix(), "size": size,
                            "pixel_match": True, "alpha_preserved": True, "metrics": metrics})
    record = {"id": row["id"], "name": row["name"].removesuffix(" · 照片版"),
              "source_mapping_id": row["parent"]["mapping_id"], "lut_path": row["path"],
              "lut_sha256": row["technical"]["sha256"], "results": results,
              "technical_status": "passed", "photo_test_status": "sampled_outdoor_scenes",
              "aesthetic_approval": "not_universally_assessed"}
    write_json(folder / "results.json", record)
    return record


def contact_sheets(manifest, output):
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 16)
    small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 13)
    pages = []
    sources = manifest["samples"]
    for strength in (.5, 1.):
        for start in range(0, len(manifest["items"]), 9):
            batch = manifest["items"][start:start + 9]
            cell_w, cell_h, label_w = 182, 214, 174
            canvas = Image.new("RGB", (label_w + len(sources) * cell_w, 74 + (len(batch) + 1) * cell_h), "#f2f1ec")
            draw = ImageDraw.Draw(canvas)
            draw.text((14, 12), f"81 LUT 照片测试 · {round(strength*100)}% · {start+1}–{start+len(batch)} / 81", font=font, fill="#202820")
            for column, source in enumerate(sources):
                draw.text((label_w + column * cell_w + 7, 44), source["name"], font=small, fill="#303830")
            for n, item in enumerate([None] + batch):
                y = 74 + n * cell_h
                if item is None:
                    name = "原图 / sRGB"
                else:
                    name = f"{start+n:02d} {item['name']}"
                words = [name[i:i + 18] for i in range(0, len(name), 18)]
                for k, text in enumerate(words):
                    draw.text((9, y + 30 + k * 21), text, font=small, fill="#202820")
                for col, source in enumerate(sources):
                    r = next((r for r in item["results"] if r["sample_id"] == source["id"] and r["strength"] == strength), None) if item else None
                    path = output / (r["thumbnail"] if r else source["baseline"])
                    with Image.open(path) as im:
                        im = im.convert("RGB")
                        im.thumbnail((cell_w - 8, cell_h - 12), Image.Resampling.LANCZOS)
                        x = label_w + col * cell_w + (cell_w - im.width) // 2
                        canvas.paste(im, (x, y + (cell_h - im.height) // 2))
            name = f"sheet-{round(strength*100)}-{start//9+1:02d}.jpg"
            canvas.save(output / name, quality=92, subsampling=0)
            pages.append({"strength": strength, "start": start+1, "end": start+len(batch), "path": name})
    return pages


def viewer(manifest, output):
    data = json.dumps(manifest, ensure_ascii=False).replace("</", "<\\/")
    template = (Path(__file__).with_name("photo_test_viewer.html")).read_text()
    (output / "index.html").write_text(template.replace("__PHOTO_TEST_DATA__", data), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Use a new output directory; historical tests are immutable")
    output.mkdir(parents=True)
    catalog_path = ROOT / "catalog.json"
    catalog_sha = sha(catalog_path)
    items = [x for x in json.loads(catalog_path.read_text())["items"] if x.get("derived")]
    if len(items) != 81:
        raise ValueError("Expected the approved 81 converted LUTs")
    sources = json.loads(args.samples.read_text())
    if len(sources) != 6 or len({s["sha256"] for s in sources}) != 6:
        raise ValueError("Expected six explicitly selected distinct photos")
    for sample in sources:
        if sha(Path(sample["path"])) != sample["sha256"]:
            raise ValueError("Input photo changed")
        target = output / (sample["id"] + "-original.png")
        render(Path(sample["path"]), target, {}, max_edge=1280)
        sample["baseline"] = target.name
        sample["baseline_sha256"] = sha(target)
        with Image.open(target) as im:
            sample["preview_size"] = list(im.size)
        thumb = target.with_suffix(".jpg")
        thumbnail(target, thumb)
        sample["thumbnail"] = thumb.name
    records = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = {pool.submit(process_lut, row, sources, output): row for row in items}
        for task in as_completed(tasks):
            result = task.result()
            records.append(result)
            print(json.dumps({"done": len(records), "total": 81, "lut": result["name"],
                              "renders": len(result["results"]), "attention_cases": sum(r["metrics"]["attention"] for r in result["results"])}, ensure_ascii=False), flush=True)
    records.sort(key=lambda x:x["id"])
    for sample in sources:
        if sha(Path(sample["path"])) != sample["sha256"]:
            raise ValueError("Original photo was modified")
    if sha(catalog_path) != catalog_sha or any(sha(ROOT / row["path"]) != row["technical"]["sha256"] for row in items):
        raise ValueError("Runtime catalog or LUT bytes changed")
    manifest = {"date": "2026-10-30", "scope": "81 converted LUTs on six existing outdoor photos",
                "catalog_sha256": catalog_sha, "renderer": "backend.app.imaging.render", "max_edge": 1280,
                "strengths": [.5, 1.], "extra_adjustments": "none", "working_space": "sRGB encoded RGB",
                "render_count": sum(len(r["results"]) for r in records), "lut_count": 81,
                "photo_sources_preserved": True, "runtime_luts_preserved": True,
                "samples": sources, "items": records,
                "limits": "Six outdoor images only; not a portrait, indoor, night or print-quality assessment. Metrics are descriptive, not aesthetic scoring."}
    manifest["contact_sheets"] = contact_sheets(manifest, output)
    write_json(output / "manifest.json", manifest)
    viewer(manifest, output)
    print(json.dumps({"status": "complete", "luts": 81, "photos": 6, "render_count": manifest["render_count"], "output": str(output)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
