"""Numerically validate archived HaldCLUTs and append them to the photo catalog.

No downloads, photo renders, resampling, or changes to existing LUT bytes.
The previous activation receipts and implementation snapshots remain auditable.
"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import re
import shutil
import sys

import numpy as np
import pyvips

from library import ROOT, scan

sys.path.insert(0, str(ROOT.parent / "backend"))
from app.hald import HaldProcessor, VERSION, inspect_hald

SOURCE = ROOT / "inventory/2026-10-30/photo-suitability/catalog.json"
BACKUP = ROOT / "inventory/2026-10-30/before-hald-activation"
REPORT = ROOT / "derived/2026-10-30-hald-native/validation.json"
RECEIPT = ROOT / "hald-activation-receipt-2026-10-30.json"
README = ROOT / "collected/2026-10-30/documents/rawtherapee-haldclut/HaldCLUT/README.txt"
LICENSE = ROOT / "licenses/rawtherapee-haldclut/README.txt"
LIMITS = {"max_error": 2e-5, "rms_error": 2e-6}


def read(p):
    return json.loads(p.read_text())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def put(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_suffix(p.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temp.replace(p)


def sources():
    if sha(SOURCE) != read(ROOT / "photo-suitability-receipt-2026-10-30.json")["catalog_sha256"]:
        raise ValueError("Frozen classification changed")
    rows = read(SOURCE)["hald_items"]
    for row in rows:
        if sha(ROOT / row["path"]) != row["original_sha256"]:
            raise ValueError("Archived Hald changed: " + row["name"])
        if row["declared_input"] != "sRGB" or row["declared_output"] != "sRGB":
            raise ValueError("Unexpected Hald profile")
    looks = [r for r in rows if r["asset_role"] == "unreviewed_look"]
    if len(looks) != 292 or len(rows) != 293:
        raise ValueError("Unexpected archived Hald selection")
    return looks


def reference(values, size, depth, points):
    """Independent float64, eight weighted corners using raster pixel addresses."""
    pos = np.clip(points.astype(np.float64), 0, 1) * (size - 1)
    lower = np.minimum(np.floor(pos).astype(np.int64), size - 2)
    fraction = pos - lower
    out = np.zeros((len(points), 3), dtype=np.float64)
    for corner in itertools.product((0, 1), repeat=3):
        xyz = lower + corner
        weight = np.prod(np.where(np.array(corner), fraction, 1 - fraction), axis=1)
        address = xyz[:, 0] + size * xyz[:, 1] + size * size * xyz[:, 2]
        out += values[address].astype(np.float64) * (weight / ((1 << depth) - 1))[:, None]
    return out


def test_points(size):
    rng = np.random.default_rng(20261030)
    knots = (rng.integers(0, size, (8192, 3)) / (size - 1)).astype(np.float32)
    faces = rng.random((6144, 3)).astype(np.float32)
    for face in range(6):
        faces[face * 1024:(face + 1) * 1024, face // 2] = face % 2
    axes = np.linspace(0, 1, 33, dtype=np.float32)
    grid = np.stack(np.meshgrid(axes, axes, axes, indexing="ij"), axis=-1).reshape(-1, 3)
    gray = np.repeat(np.linspace(0, 1, 2049, dtype=np.float32)[:, None], 3, axis=1)
    return np.concatenate((grid, rng.random((65536, 3)).astype(np.float32), knots,
                           np.clip(knots - 1e-7, 0, 1), np.clip(knots + 1e-7, 0, 1), faces, gray,
                           np.array([[-1, .3, 2], [2, -1, .3], [.3, 2, -1]], dtype=np.float32)))


def numerical(data):
    cpu = HaldProcessor(data)
    x = test_points(cpu.size)
    expected = reference(cpu.values, cpu.size, cpu.depth, x)
    actual = x.copy()
    cpu.applyRGB(actual)
    errors = np.abs(actual.astype(np.float64) - expected)
    maximum, rms = float(errors.max()), float(np.sqrt((errors ** 2).mean()))
    strengths = {}
    for s in (.25, .5, .75, 1):
        blended = actual * np.float32(s) + np.clip(x, 0, 1) * np.float32(1 - s)
        wanted = expected * s + np.clip(x.astype(np.float64), 0, 1) * (1 - s)
        strengths[str(s)] = float(np.abs(blended - wanted).max())
    passed = bool(np.isfinite(actual).all() and maximum <= LIMITS["max_error"] and rms <= LIMITS["rms_error"] and max(strengths.values()) <= LIMITS["max_error"])
    return {"passed": passed, "sample_count": len(x), "max_error": maximum, "rms_error": rms,
            "strength_max_errors": strengths, "limits": LIMITS,
            "input_sampling": "33^3 grid, 65536 random, 8192 source knots and +/-1e-7, 6144 face, 2049 gray, 3 clamping probes"}


def identity_check():
    row = next(r for r in read(SOURCE)["hald_items"] if r["asset_role"] == "identity_template")
    image = pyvips.Image.new_from_file(str(ROOT / row["path"]))
    assert image.width == image.height == 1728 and image.bands == 3 and image.format == "ushort"
    values = np.frombuffer(image.write_to_memory(), dtype=np.uint16).reshape(-1, 3)
    idx = np.random.default_rng(1).integers(0, len(values), 65536)
    xyz = np.stack((idx % 144, idx // 144 % 144, idx // (144 * 144)), axis=1)
    maximum = float(np.abs(values[idx].astype(float) / 65535 - xyz / 143).max())
    if maximum > 1 / 65535:
        raise ValueError("Identity template contradicts Hald axis convention")
    return {"path": row["path"], "sha256": row["original_sha256"], "samples": len(idx), "max_error": maximum, "included_in_runtime": False}


def build():
    if REPORT.exists() or RECEIPT.exists():
        raise ValueError("Validation already exists; verify instead of overwriting")
    result, mappings = [], {}
    for i, row in enumerate(sources(), 1):
        data = (ROOT / row["path"]).read_bytes()
        technical = inspect_hald(data)
        validation = numerical(data)
        if not validation["passed"]:
            raise ValueError("Hald numerical check failed: " + row["name"] + str(validation))
        slug = re.sub(r"[^a-z0-9]+", "-", row["name"].lower()).strip("-")
        uid = "rawtherapee-" + slug + "-" + row["original_sha256"][:8]
        runtime_id = mappings.setdefault(technical["mapping_sha256"], uid)
        result.append({"source_id": row["id"], "id": uid, "name": row["name"], "source_path": row["path"],
                       "runtime_id": runtime_id, "source_sha256": row["original_sha256"], "technical": technical, "validation": validation})
        if i % 20 == 0 or i == 292:
            print(json.dumps({"checked": i, "total": 292, "max_error": validation["max_error"]}), flush=True)
    identity = identity_check()
    put(REPORT, {"version": VERSION, "count": len(result), "unique_count": len(mappings), "date": "2026-10-30", "items": result,
                 "identity": identity, "source_catalog_sha256": sha(SOURCE), "source_readme_sha256": sha(README),
                 "implementation_sha256": {p: sha(ROOT.parent / p) for p in ("backend/app/hald.py", "lut-library/tools/activate_hald_luts.py")},
                 "versions": {"numpy": np.__version__, "vips": '.'.join(str(pyvips.version(i)) for i in range(3))},
                 "source_documents": ["https://rawpedia.pixls.us/film_simulation/", "https://raw.githubusercontent.com/RawTherapee/RawTherapee/dev/rtengine/clutstore.cc"],
                 "policy": "Native Hald PNG, all source nodes and bit depth retained; sRGB encoded input/output; red-fastest; trilinear; grayscale expands equally to RGB; no resampling/color-space conversion",
                 "limitations": "Numerical checks of Hald lookup, not full RawTherapee workflow equivalence or photo aesthetics; no cross-format perceptual deduplication",
                 "photo_effect_tests": 0})


def snapshot():
    return BACKUP / "catalog.json" if RECEIPT.exists() else ROOT / "catalog.json"


def verify_previous_implementation(previous):
    if not RECEIPT.exists():
        for rel, digest in previous["implementation_sha256"].items():
            if sha(ROOT.parent / rel) != digest:
                raise ValueError("Validated implementation changed: " + rel)
        return
    receipt = read(RECEIPT)
    if sha(ROOT / "photo-conversion-receipt-2026-10-30.json") != receipt["previous_receipt_sha256"]:
        raise ValueError("Historical conversion receipt changed")
    for rel, digest in previous["implementation_sha256"].items():
        if sha(BACKUP / "implementation" / rel) != digest or receipt["previous_implementation_sha256"].get(rel) != digest:
            raise ValueError("Previous validated implementation backup changed: " + rel)
    from intake_archived_luts import RECEIPT as intake_receipt, verify_successor
    if intake_receipt.exists():
        verify_successor(receipt)
    else:
        for rel, digest in receipt["implementation_sha256"].items():
            if sha(ROOT.parent / rel) != digest:
                raise ValueError("Current validated implementation changed: " + rel)


def verify_build(recheck=False):
    report = read(REPORT)
    selected = {r["id"]: r for r in sources()}
    if report["count"] != len(selected) or {r["source_id"] for r in report["items"]} != set(selected):
        raise ValueError("Hald selection/report mismatch")
    if sha(SOURCE) != report["source_catalog_sha256"] or sha(README) != report["source_readme_sha256"]:
        raise ValueError("Hald source evidence changed")
    from intake_archived_luts import RECEIPT as intake_receipt, BACKUP as intake_backup
    implementation_root = intake_backup / "implementation" if intake_receipt.exists() else ROOT.parent
    for rel, digest in report["implementation_sha256"].items():
        if sha(implementation_root / rel) != digest:
            raise ValueError("Hald validation implementation changed: " + rel)
    if report["identity"] != identity_check():
        raise ValueError("Identity check changed")
    canonical = {r["id"]: r for r in report["items"] if r["id"] == r["runtime_id"]}
    if len(canonical) != report["unique_count"] or len({r["technical"]["mapping_sha256"] for r in canonical.values()}) != len(canonical):
        raise ValueError("Incorrect Hald deduplication")
    for item in report["items"]:
        if item["technical"]["mapping_sha256"] != canonical[item["runtime_id"]]["technical"]["mapping_sha256"]:
            raise ValueError("Incorrect Hald alias mapping")
        row = selected[item["source_id"]]
        if item["source_path"] != row["path"] or item["source_sha256"] != row["original_sha256"]:
            raise ValueError("Hald lineage mismatch")
        check = item["validation"]
        if not check["passed"] or check["limits"] != LIMITS or check["sample_count"] < 100000 or check["max_error"] > LIMITS["max_error"] or check["rms_error"] > LIMITS["rms_error"]:
            raise ValueError("Invalid numerical acceptance")
        if recheck and numerical((ROOT / row["path"]).read_bytes()) != check:
            raise ValueError("Hald numerical recheck differs")
    return report


def verify(actual=None, recheck=False):
    report = verify_build(recheck)
    receipt = read(RECEIPT)
    verify_previous_implementation(read(ROOT / "photo-conversion-receipt-2026-10-30.json"))
    from intake_archived_luts import historical_catalog, RECEIPT as intake_receipt, verify as verify_intake
    historical = historical_catalog()
    if sha(REPORT) != receipt["report_sha256"] or sha(historical) != receipt["catalog_sha256"]:
        raise ValueError("Hald receipt mismatch")
    if sha(BACKUP / "catalog.json") != receipt["previous_catalog_sha256"] or receipt["previous_catalog_sha256"] != read(ROOT / "photo-conversion-receipt-2026-10-30.json")["catalog_sha256"]:
        raise ValueError("Previous 131-LUT snapshot changed")
    for rel, digest in receipt["previous_files_sha256"].items():
        if sha(BACKUP / rel) != digest or (rel not in ("catalog.json", "CATALOG.md") and sha(ROOT / rel) != digest):
            raise ValueError("Previous runtime file/metadata changed: " + rel)
    actual = scan() if actual is None else actual
    current_count = len(actual)
    saved = read(historical)
    if intake_receipt.exists():
        verify_intake(actual)
        previous_ids = {r["id"] for r in saved["items"]}
        actual = [r for r in actual if r["id"] in previous_ids]
    if saved["items"] != actual or saved["count"] != len(actual) or len(actual) != 131 + report["unique_count"]:
        raise ValueError("Expanded catalog/scan mismatch")
    by_id = {r["id"]: r for r in actual}
    old = read(BACKUP / "catalog.json")["items"]
    for row in old:
        if by_id.get(row["id"]) != row:
            raise ValueError("Existing runtime row changed")
    if set(by_id) - {r["id"] for r in old} != {r["runtime_id"] for r in report["items"]}:
        raise ValueError("Unexpected added runtime entry")
    if sha(LICENSE) != report["source_readme_sha256"]:
        raise ValueError("Missing/changed attribution")
    for r in report["items"]:
        if r["id"] != r["runtime_id"]:
            continue
        row = by_id[r["id"]]
        if row["technical"] != r["technical"] or row["original_sha256"] != r["source_sha256"] or sha(ROOT / row["path"]) != r["source_sha256"]:
            raise ValueError("Runtime Hald values/hash changed")
        if sha(ROOT / row["metadata_path"]) != receipt["new_metadata_sha256"][r["id"]]:
            raise ValueError("Hald runtime metadata changed")
        if not row["enabled"] or row["file_modified"] or row["effect_test_status"] != "not_tested":
            raise ValueError("Incorrect Hald activation/effect status")
    return {"passed": True, "added": report["unique_count"], "archived_source_looks": report["count"], "previous_preserved": 131, "active_luts": current_count,
            "numerical_samples_per_lut": report["items"][0]["validation"]["sample_count"],
            "max_error": max(r["validation"]["max_error"] for r in report["items"]), "photo_effect_tests": 0}


def activate():
    if RECEIPT.exists():
        return verify()
    report = verify_build()
    baseline = read(BACKUP / "baseline.json")
    old = read(ROOT / "catalog.json")
    if sha(ROOT / "catalog.json") != baseline["files_sha256"]["catalog.json"] or old["items"] != scan():
        raise ValueError("Runtime changed since preflight")
    sources_by_id = {r["id"]: r for r in sources()}
    prepared = []
    for r in report["items"]:
        if r["id"] != r["runtime_id"]:
            continue
        source = sources_by_id[r["source_id"]]
        folder = ROOT / "luts/hald-photo" / r["id"]
        if folder.exists():
            raise ValueError("Refusing to overwrite Hald runtime directory")
        path = folder / (r["id"] + ".png")
        member = source["sources"][0]["member"]
        kind = "黑白" if "/Black-and-White/" in member else "彩色"
        meta = {"schema_version": 1, "id": r["id"], "name": "RawTherapee " + r["name"],
                "publisher": "RawTherapee Film Simulation Collection", "filename": path.name,
                "format": "HaldCLUT", "category": "hald-photo", "style_zh": r["name"] + "（作者命名；照片效果待人工查看）",
                "tags": ["HaldCLUT", kind], "aliases": [x["name"] for x in report["items"] if x["runtime_id"] == r["id"]],
                "source_variants": [{"name": x["name"], "path": x["source_path"], "sha256": x["source_sha256"]} for x in report["items"] if x["runtime_id"] == r["id"]],
                "source_page": source["sources"][0]["source_page"],
                "source_origin": source["sources"][0], "source_path": r["source_path"], "source_sha256": r["source_sha256"],
                "original_sha256": r["source_sha256"], "file_modified": False,
                "input_profile": "sRGB 照片；原始 Hald 网格；三线性插值", "input_space": "srgb", "output_space": "srgb",
                "enabled": True, "effect_test_status": "not_tested", "historical_preview_refs": [],
                "photo_suitability": {"category": "native_hald", "source_id": source["id"], "evidence_ids": source["evidence_ids"], "basis": "sRGB source README plus numerical validation of native Hald lookup"},
                "validation": {"report_path": REPORT.relative_to(ROOT).as_posix(), "version": VERSION, "status": "passed", **r["validation"]},
                "license": {"id": "CC-BY-SA-4.0", "status": source["sources"][0]["license_note"], "documents": [LICENSE.relative_to(ROOT).as_posix()],
                            "authors": ["Pat David", "Pavlov Dmitry", "Michael Ezra"]},
                "cautions": "无降采样，保留原表位深；数值验证不等于照片观感验收；不保证与完整 RawTherapee RAW 工作流相同。",
                "added_date": "2026-10-30", "batch": f"{report['unique_count']} 种原生 HaldCLUT 接入"}
        row = {**meta, "path": path.relative_to(ROOT).as_posix(), "metadata_path": (folder / "metadata.json").relative_to(ROOT).as_posix(), "technical": r["technical"]}
        prepared.append((path, meta, row))
    items = sorted(old["items"] + [r for _, _, r in prepared], key=lambda r: r["id"])
    if any(len({r[k] for r in items}) != len(items) for k in ("id", "name")) or len({r["technical"]["mapping_sha256"] for r in items}) != len(items):
        raise ValueError("Duplicate runtime ID/name/mapping")
    created = []
    try:
        LICENSE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(README, LICENSE)
        for path, meta, row in prepared:
            path.parent.mkdir(parents=True)
            created.append(path.parent)
            shutil.copyfile(ROOT / row["source_path"], path)
            put(path.parent / "metadata.json", meta)
        if scan() != items:
            raise ValueError("Staged Hald runtime differs from catalog")
        put(ROOT / "catalog.json", {"schema_version": 1, "library_name": "Photo LUT Library", "count": len(items), "items": items})
        lines = ["# 照片 LUT 运行目录", "", f"共 **{len(items)} 种**：50 种原始 CUBE、81 种 CLF 照片转换版、{report['unique_count']} 种原生 HaldCLUT。", "",
                 "新增 HaldCLUT 保留原表、位深与网格，已做数值校验，照片效果待人工查看。Identity 模板继续归档。", "",
                 "[Hald 接入说明](HALD-ACTIVATION.md) · [81 种转换报告](PHOTO-CONVERSION.md)", "",
                 "| 名称 | 格式 | 网格 | 文件 |", "|---|---|---:|---|"]
        lines += [f"| {r['name']} | {r['technical']['lut_type']} | {r['technical']['grid_size']}³ | [文件]({r['path']}) |" for r in items]
        (ROOT / "CATALOG.md").write_text("\n".join(lines) + "\n")
        implementation = set(baseline["implementation_sha256"]) | {"backend/app/hald.py", "lut-library/tools/activate_hald_luts.py"}
        put(RECEIPT, {"date": "2026-10-30", "added": report["unique_count"], "active_luts": len(items), "existing_preserved": 131,
                      "catalog_sha256": sha(ROOT / "catalog.json"), "report_sha256": sha(REPORT),
                      "backup_path": BACKUP.relative_to(ROOT).as_posix(), "previous_catalog_sha256": baseline["files_sha256"]["catalog.json"],
                      "previous_files_sha256": baseline["files_sha256"], "previous_receipt_sha256": baseline["previous_receipt_sha256"],
                      "previous_implementation_sha256": baseline["implementation_sha256"],
                      "implementation_sha256": {p: sha(ROOT.parent / p) for p in sorted(implementation)},
                      "new_metadata_sha256": {row["id"]: sha(ROOT / row["metadata_path"]) for _, _, row in prepared},
                      "photo_effect_tests": 0})
    except Exception:
        for folder in created:
            shutil.rmtree(folder)
        for name in ("catalog.json", "CATALOG.md"):
            shutil.copyfile(BACKUP / name, ROOT / name)
        RECEIPT.unlink(missing_ok=True)
        raise
    return verify(items)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "activate", "verify"))
    parser.add_argument("--numerical", action="store_true")
    args = parser.parse_args()
    result = build() if args.command == "build" else activate() if args.command == "activate" else verify(recheck=args.numerical)
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
