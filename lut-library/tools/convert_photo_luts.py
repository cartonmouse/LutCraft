"""Offline conversion of the approved 81 mappings. Never reads a photo.

Build retains a 65^3 CUBE comparison and a composed CLF. Activation is separate
and accepts only the fully validated CLF, preserving the prior 50 entries.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

import numpy as np
import PyOpenColorIO as ocio

from library import ROOT, inspect_cube, inspect_transform, scan
from photo_conversion_math import (VERSION, ADOBE_GAMMA, WHITE, SRGB_PRIMARIES,
    ADOBE_PRIMARIES, SRGB_TO_ADOBE, ADOBE_TO_SRGB, grid, load_table, reference,
    source_agreement, validate, write_clf)

PLAN = ROOT / "inventory/2026-10-30/conversion-plan/catalog.json"
OUT = ROOT / "derived/2026-10-30-srgb-v1"
REPORT = OUT / "conversion.json"
RECEIPT = ROOT / "photo-conversion-receipt-2026-10-30.json"
BACKUP = ROOT / "inventory/2026-10-30/before-photo-conversion"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def selected():
    plan_receipt = read(ROOT / "conversion-plan-receipt-2026-10-30.json")
    if sha(PLAN) != plan_receipt["catalog_sha256"]:
        raise ValueError("Reviewed conversion plan changed")
    rows = [r for r in read(PLAN)["items"] if r["decision"] == "defined_route"]
    if len(rows) != 81 or len({r["mapping_id"] for r in rows}) != 81:
        raise ValueError("Expected exactly the approved 81 mappings")
    for row in rows:
        if sha(ROOT / row["path"]) != row["source_sha256"]:
            raise ValueError("Original changed: " + row["name"])
    return rows


def build():
    if RECEIPT.exists():
        raise ValueError("Already activated; use verify, never regenerate active artifacts")
    rows = selected()
    base = read(ROOT / "photo-activation-receipt-2026-10-30.json")
    if sha(ROOT / "catalog.json") != base["catalog_sha256"]:
        raise ValueError("Expected the unchanged 50-LUT runtime before conversion")
    if REPORT.exists():
        raise ValueError("Completed conversion exists; verify it instead of overwriting")
    OUT.mkdir(parents=True, exist_ok=True)
    recipe = {"version": VERSION, "format": "CLF 3, standalone embedded LUT3D plus analytical transforms",
              "input": "sRGB encoded, normalized full range", "output": "extended sRGB encoded",
              "white_xy": WHITE, "srgb_primaries_xy": SRGB_PRIMARIES, "adobe_primaries_xy": ADOBE_PRIMARIES,
              "adobe_gamma": ADOBE_GAMMA, "rec709_gamma": 2.4,
              "srgb_to_adobe_matrix": SRGB_TO_ADOBE.tolist(), "adobe_to_srgb_matrix": ADOBE_TO_SRGB.tolist(),
              "interpolation": "tetrahedral", "precision": "float64 independent reference; OCIO float32 production",
              "reference_srgb": {"decode_knee": .04045, "encode_knee": .0031308, "slope": 12.92, "offset": .055, "gamma": 2.4},
              "clf_srgb": "CLF monCurveFwd/Rev gamma 2.4 offset .055 uses its continuous knee/slope; checked against reference, not claimed identical",
              "gamut_policy": "negative linear output continues linear sRGB branch; positive >1 continues power branch; no early output clamp or gamut compression",
              "strength": "encoded sRGB blend then clamp, unchanged production behavior",
              "intent": "relative D65 RGB; no luminance rescaling, surround correction, adaptation or black-point compensation",
              "output_space_basis": "same-profile Export LUT workflow inference; not original-author visual equivalence",
              "versions": {"numpy": np.__version__, "opencolorio": ocio.__version__, "python": sys.version.split()[0]},
              "source_documents": ["https://www.adobe.com/digitalimag/pdfs/AdobeRGB1998.pdf", "https://registry.color.org/rgb-registry/srgb",
                                   "https://johnrellis.com/lightroom/exportlut.htm", "https://opencolorio.readthedocs.io/en/latest/api/transforms.html#exponentwithlineartransform"]}
    put_json(OUT / "recipe.json", recipe)
    results = []
    for number, row in enumerate(rows, 1):
        folder = OUT / row["mapping_id"]
        folder.mkdir(exist_ok=True)
        source = ROOT / row["path"]
        technical = inspect_cube(source)
        if technical["mapping_sha256"] != row["mapping_sha256"] or technical["domain_min"] != [0, 0, 0] or technical["domain_max"] != [1, 1, 1]:
            raise ValueError("Source mapping/domain changed")
        table = load_table(source, row["grid_size"])
        agreement = source_agreement(table, row["grid_size"], source)
        cube = folder / "srgb-65-comparison.cube"
        values = reference(table, row["grid_size"], grid(np.linspace(0, 1, 65)), row["route_id"])
        np.savetxt(cube, values, fmt="%.7f", header="LUT_3D_SIZE 65\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1", comments="")
        comparison = validate(table, row["grid_size"], row["route_id"], cube)
        clf = folder / "srgb.clf"
        write_clf(source, row["route_id"], clf)
        validation = validate(table, row["grid_size"], row["route_id"], clf)
        result = {"mapping_id": row["mapping_id"], "name": row["name"], "source_id": row["source_id"],
                  "source_path": row["path"], "source_sha256": row["source_sha256"], "source_mapping_sha256": row["mapping_sha256"],
                  "source_grid_size": row["grid_size"], "route_id": row["route_id"], "source_interpolation_check": agreement,
                  "derived_path": clf.relative_to(ROOT).as_posix(), "derived_sha256": sha(clf), "derived_bytes": clf.stat().st_size,
                  "numerical_validation": validation, "comparison_cube": {"path": cube.relative_to(ROOT).as_posix(),
                  "sha256": sha(cube), "bytes": cube.stat().st_size, "grid_size": 65, "validation": comparison, "activated": False},
                  "photo_effect_test_status": "not_tested", "new_photo_effect_tests": 0}
        results.append(result)
        put_json(folder / "validation.json", result)
        print(json.dumps({"progress": f"{number}/81", "name": row["name"], "cube65_passed": comparison["passed"],
                          "clf_passed": validation["passed"], "clf_max_error": validation["worst"]["error"]}, ensure_ascii=False), flush=True)
    report = {"date": "2026-10-30", "scope": "approved 81 conversions and numerical checks, no photos",
              "plan_sha256": sha(PLAN), "recipe_path": (OUT / "recipe.json").relative_to(ROOT).as_posix(),
              "recipe_sha256": sha(OUT / "recipe.json"), "math_script_sha256": sha(Path(__file__).with_name("photo_conversion_math.py")),
              "count": len(results), "clf_passed": sum(x["numerical_validation"]["passed"] for x in results),
              "cube65_passed": sum(x["comparison_cube"]["validation"]["passed"] for x in results),
              "photo_effect_tests": 0, "downloads": 0, "items": results}
    put_json(REPORT, report)
    selected()  # All 81 source hashes still match after execution.
    return {k: v for k, v in report.items() if k != "items"}


def verify_build(numerical=False):
    rows = {r["mapping_id"]: r for r in selected()}
    report = read(REPORT)
    if report["plan_sha256"] != sha(PLAN) or report["recipe_sha256"] != sha(OUT / "recipe.json"):
        raise ValueError("Conversion input/recipe changed")
    if report["math_script_sha256"] != sha(Path(__file__).with_name("photo_conversion_math.py")):
        raise ValueError("Conversion math changed; existing validation is not reusable")
    recipe = read(OUT / "recipe.json")
    if recipe["versions"]["opencolorio"] != ocio.__version__ or recipe["versions"]["numpy"] != np.__version__:
        raise ValueError("Numerical engine version changed; explicitly revalidate before reuse")
    if report["count"] != 81 or len(report["items"]) != 81 or {x["mapping_id"] for x in report["items"]} != set(rows):
        raise ValueError("Conversion selection mismatch")
    for item in report["items"]:
        row = rows[item["mapping_id"]]
        if item["source_path"] != row["path"] or item["source_sha256"] != row["source_sha256"]:
            raise ValueError("Parent mismatch")
        for path, digest in ((item["derived_path"], item["derived_sha256"]),
                             (item["comparison_cube"]["path"], item["comparison_cube"]["sha256"])):
            if sha(ROOT / path) != digest:
                raise ValueError("Derivative/comparison bytes changed: " + path)
        info = inspect_transform(ROOT / item["derived_path"])
        if info["grid_size"] != row["grid_size"] or info["bytes"] != item["derived_bytes"]:
            raise ValueError("CLF failed structural checks")
        metrics = item["numerical_validation"]
        limits = metrics["limits"]
        if [m["strength"] for m in metrics["strengths"]] != [.25, .5, .75, 1.0]:
            raise ValueError("Strength coverage changed")
        if sum(g["samples"] for g in metrics["groups"]) != metrics["sample_count"]:
            raise ValueError("Sample counts do not reconcile")
        if limits != {"max_error": 1 / 255, "rms_error": .25 / 255} or metrics["sample_count"] < 1000000:
            raise ValueError("Numerical coverage/threshold changed")
        passed = all(x["max_error"] <= limits["max_error"] and x["rms_error"] <= limits["rms_error"] for x in metrics["strengths"])
        if passed != metrics["passed"] or not passed:
            raise ValueError("Numerical validation failed: " + row["name"])
        if numerical:
            table = load_table(ROOT / row["path"], row["grid_size"])
            checked = validate(table, row["grid_size"], row["route_id"], ROOT / item["derived_path"])
            if checked != metrics:
                raise ValueError("Numerical results are not reproducible: " + row["name"])
            print(f"Numerically reverified: {row['name']}", flush=True)
    if report["clf_passed"] != 81:
        raise ValueError("Not all 81 CLFs passed")
    return report


def verify(numerical=False):
    report = verify_build(numerical)
    if not RECEIPT.exists():
        return {"converted": 81, "numerically_passed": 81, "activated": False, "photo_effect_tests": 0}
    receipt = read(RECEIPT)
    from activate_hald_luts import snapshot, verify_previous_implementation, RECEIPT as hald_receipt
    verify_previous_implementation(receipt)
    historical_catalog = snapshot()
    if sha(REPORT) != receipt["conversion_report_sha256"] or sha(historical_catalog) != receipt["catalog_sha256"]:
        raise ValueError("Execution receipt mismatch")
    old = read(BACKUP / "catalog.json")
    base = read(ROOT / "photo-activation-receipt-2026-10-30.json")
    if sha(BACKUP / "catalog.json") != base["catalog_sha256"] or receipt["previous_catalog_sha256"] != base["catalog_sha256"]:
        raise ValueError("Previous 50-LUT snapshot mismatch")
    for relative, digest in receipt["previous_files_sha256"].items():
        if sha(BACKUP / relative) != digest:
            raise ValueError("Backup changed: " + relative)
        if relative not in ("catalog.json", "CATALOG.md") and sha(ROOT / relative) != digest:
            raise ValueError("Existing metadata changed: " + relative)
    all_actual = scan()
    saved = read(historical_catalog)
    historical_ids = {x["id"] for x in saved["items"]}
    actual = [x for x in all_actual if x["id"] in historical_ids]
    if saved["items"] != actual or saved["count"] != 131 or len(actual) != 131:
        raise ValueError("Runtime scan/catalog mismatch")
    current = {x["id"]: x for x in actual}
    for row in old["items"]:
        if current.get(row["id"]) != row:
            raise ValueError("Existing runtime entry changed: " + row["id"])
    records = {x["mapping_id"]: x for x in report["items"]}
    derived = [x for x in actual if x.get("derived")]
    if len(derived) != 81 or {x["parent"]["mapping_id"] for x in derived} != set(records):
        raise ValueError("Runtime derivative selection mismatch")
    sys.path.insert(0, str(ROOT.parent / "backend"))
    from app.single_pass import catalog, load_catalog_processor
    from app.lut_metadata import LutMetadata
    from photo_conversion_math import evaluate
    visible = catalog()
    if {x["id"] for x in visible} != {x["id"] for x in all_actual}:
        raise ValueError("Production reader is missing active LUTs")
    if hald_receipt.exists():
        from activate_hald_luts import verify as verify_hald
        verify_hald(all_actual)
    elif len(all_actual) != len(actual):
        raise ValueError("Unrecorded runtime additions")
    for x in derived:
        item = records[x["parent"]["mapping_id"]]
        if sha(ROOT / x["path"]) != item["derived_sha256"] or x["parent"]["sha256"] != item["source_sha256"]:
            raise ValueError("Runtime lineage/hash mismatch")
        if not x["enabled"] or x["effect_test_status"] != "not_tested" or x["photo_suitability"]["category"] != "converted":
            raise ValueError("Incorrect conversion/effect status")
        meta = read(ROOT / x["metadata_path"])
        LutMetadata.import_values(None, meta, x["original_sha256"])
    for row in visible:
        # Same loader as real photo processing; RGB arrays only, no image I/O.
        cpu = load_catalog_processor(row)
        evaluate(cpu, np.array([[0, 0, 0], [1, 1, 1], [.03, .25, .9]], dtype=np.float32))
    return {"converted": 81, "numerically_passed": 81, "activated": 81, "existing_preserved": 50,
            "active_runtime_count": len(all_actual), "runtime_reader_visible": len(visible),
            "runtime_loader_checks": len(visible), "cube65_comparison_passed": report["cube65_passed"],
            "photo_effect_tests": 0, "passed": True}


def activate():
    if RECEIPT.exists():
        return {**verify(), "activation": "already_applied"}
    report = verify_build()
    baseline = read(ROOT / "catalog.json")
    if baseline["count"] != 50 or baseline["items"] != scan() or sha(ROOT / "catalog.json") != read(ROOT / "photo-activation-receipt-2026-10-30.json")["catalog_sha256"]:
        raise ValueError("Existing runtime changed before activation")
    if BACKUP.exists():
        raise ValueError("Prior backup without completion receipt; inspect before retry")
    rows = {x["mapping_id"]: x for x in selected()}
    prepared = []
    sys.path.insert(0, str(ROOT.parent / "backend"))
    from app.lut_metadata import LutMetadata
    for result in report["items"]:
        row = rows[result["mapping_id"]]
        publisher = "ON1" if row["source_id"] == "on1-free" else "Pocket Action"
        slug = re.sub(r"[^a-z0-9]+", "-", row["name"].lower()).strip("-")
        uid = f"{row['source_id']}-photo-{slug + '-' if slug else ''}{row['mapping_sha256'][:10]}"
        folder = ROOT / "luts/photo-converted" / uid
        if folder.exists():
            raise ValueError("Refusing to overwrite an existing derivative: " + uid)
        origin = next((c["origin"] for c in row["source_contexts"] if c["origin"].get("sha256") == row["source_sha256"]), row["source_contexts"][0]["origin"])
        path = folder / (uid + ".clf")
        data = (ROOT / result["derived_path"]).read_bytes()
        technical = inspect_transform(ROOT / result["derived_path"])
        validation = result["numerical_validation"]
        meta = {"schema_version": 1, "id": uid, "name": f"{publisher} {row['name']} · 照片版",
                "publisher": publisher, "filename": path.name, "category": "photo-converted",
                "style_zh": f"{row['name']}（作者命名；照片效果待验证）", "tags": ["照片转换版"], "aliases": [row["name"]],
                "source_page": origin.get("source_page") or "PURCHASED.md", "source_origin": origin,
                "license": {"id": "LicenseRef-" + row["source_id"], "status": origin["license_note"], "documents": [], "redistribution_verified": False},
                "input_profile": "sRGB 照片输入；颜色空间适配已通过数值校验，照片效果未测试",
                "input_space": "srgb", "output_space": "srgb", "enabled": True, "derived": True, "file_modified": True,
                "original_sha256": technical["sha256"], "artifact_sha256": technical["sha256"],
                "checksum_field_semantics": "original_sha256 is the legacy runtime artifact-integrity field; upstream unmodified source is parent.sha256",
                "parent": {"mapping_id": row["mapping_id"], "path": row["path"], "sha256": row["source_sha256"],
                           "mapping_sha256": row["mapping_sha256"], "grid_size": row["grid_size"]},
                "conversion": {"version": VERSION, "route_id": row["route_id"], "format": "CLF 3",
                               "derived_archive_path": result["derived_path"], "recipe_path": report["recipe_path"],
                               "recipe_sha256": report["recipe_sha256"], "report_path": REPORT.relative_to(ROOT).as_posix(),
                               "numerical_status": "passed", "sample_count": validation["sample_count"],
                               "max_error": validation["worst"]["error"], "limits": validation["limits"]},
                "photo_suitability": {"category": "converted", "parent_mapping_id": row["mapping_id"],
                                      "basis": "documented source interpretation plus independent numerical validation"},
                "effect_test_status": "not_tested", "historical_preview_refs": [],
                "compatibility_basis": row["basis"] + " CLF 保存原表与完整转换链；已通过数值检查，照片效果未测试。",
                "cautions": "本项目内使用 CLF 转换链；不是可直接导入仅支持 CUBE 软件的单张 sRGB CUBE。转换精度不等于照片效果验收。",
                "added_date": "2026-10-30", "batch": "81 种照片转换版；数值通过，照片效果未测试"}
        LutMetadata.import_values(None, meta, technical["sha256"])
        if len(json.dumps(meta, ensure_ascii=False).encode()) > 24000:
            raise ValueError("Metadata size limit exceeded")
        item = {**meta, "path": path.relative_to(ROOT).as_posix(), "metadata_path": (folder / "metadata.json").relative_to(ROOT).as_posix(), "technical": technical}
        prepared.append((path, data, meta, item))
    items = sorted(baseline["items"] + [x[3] for x in prepared], key=lambda x: x["id"])
    for field in ("id", "name"):
        if len({x[field] for x in items}) != 131:
            raise ValueError("Duplicate runtime " + field)
    if len({x["technical"]["mapping_sha256"] for x in items}) != 131:
        raise ValueError("Duplicate runtime transform mapping")
    previous_paths = ["catalog.json", "CATALOG.md"] + [x["metadata_path"] for x in baseline["items"]]
    previous_hashes = {}
    for relative in previous_paths:
        target = BACKUP / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
        previous_hashes[relative] = sha(target)
    try:
        for path, data, meta, _ in prepared:
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
            put_json(path.parent / "metadata.json", meta)
        lines = ["# 照片 LUT 运行目录", "", "共 **131 种**：50 种直接使用的原始 CUBE + 81 种数值验证通过的 CLF 照片转换版。新转换版未做照片效果测试。", "",
                 "CLF 将颜色空间变换与原 LUT 封装为完整流程；不是单张重新采样的 CUBE。项目单次调色入口支持两种格式。", "",
                 "[转换与校验报告](PHOTO-CONVERSION.md) · [接入记录](photo-conversion-receipt-2026-10-30.json)", "",
                 "| 名称 | 形式 | 原表网格 | 文件 | 来源 |", "|---|---|---:|---|---|"]
        for x in items:
            fmt = Path(x["path"]).suffix[1:].upper()
            lines.append(f"| {x['name']} | {'照片转换链' if x.get('derived') else '原始 CUBE'} | {x['technical']['grid_size']}³ | [{fmt}]({x['path']}) | [{x['publisher']}]({x['source_page']}) |")
        (ROOT / "CATALOG.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Catalog is published only after every active artifact exists.
        put_json(ROOT / "catalog.json", {"schema_version": 1, "library_name": "Photo LUT Library", "count": 131, "items": items})
        receipt = {"date": "2026-10-30", "scope": "81 approved photo conversions and local runtime activation",
                   "active_luts": 131, "existing_preserved": 50, "converted_and_activated": 81,
                   "format": "CLF 3", "backup_path": BACKUP.relative_to(ROOT).as_posix(),
                   "previous_catalog_sha256": previous_hashes["catalog.json"], "previous_files_sha256": previous_hashes,
                   "catalog_sha256": sha(ROOT / "catalog.json"), "conversion_report_path": REPORT.relative_to(ROOT).as_posix(),
                   "conversion_report_sha256": sha(REPORT), "source_hashes_preserved": 81,
                   "photo_effect_tests": 0, "analysis_jobs": 0, "new_downloads": 0, "published": False,
                   "items": [{"id": x[3]["id"], "path": x[3]["path"], "sha256": x[3]["technical"]["sha256"],
                              "parent_mapping_id": x[3]["parent"]["mapping_id"]} for x in prepared]}
        put_json(RECEIPT, receipt)
        return verify()
    except Exception:
        for relative in previous_paths:
            shutil.copyfile(BACKUP / relative, ROOT / relative)
        for path, _, _, _ in prepared:
            if path.parent.exists():
                shutil.rmtree(path.parent)
        if RECEIPT.exists():
            RECEIPT.unlink()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "activate", "verify"])
    parser.add_argument("--numerical", action="store_true", help="repeat deterministic numerical checks; never use photos")
    args = parser.parse_args()
    result = build() if args.action == "build" else activate() if args.action == "activate" else verify(args.numerical)
    print(json.dumps(result, ensure_ascii=False, indent=2))
