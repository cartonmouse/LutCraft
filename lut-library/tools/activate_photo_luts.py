"""Activate the reviewed 50 photo LUT mappings, without evaluating any LUT.

Uses the frozen classification as an allowlist. Keeps existing IDs and bytes,
copies the preferred publisher's original bytes for new entries, and publishes
the catalog last. Never invokes upload queues, analysis, rendering or networking.
"""
import argparse
from collections import Counter
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

from classify_photo_suitability import OriginalReader
from library import ROOT, inspect_cube, scan

sys.path.insert(0, str(ROOT.parent / "backend"))
from app.luts import inspect_cube as engine_inspect
from app.lut_metadata import LutMetadata

CLASSIFICATION = ROOT / "inventory/2026-10-30/photo-suitability/catalog.json"
RECEIPT = ROOT / "photo-activation-receipt-2026-10-30.json"
BACKUP = ROOT / "inventory/2026-10-30/before-photo-activation"
DATE = "2026-10-30"
PUBLISHERS = {"on1-free": "ON1", "xmosaique": "xMosaique", "iwltbap-free": "IWLTBAP"}
ON1_STYLES = {
    "Amber & Aqua": ("cinematic", "琥珀与青色", ["青橙"]),
    "Bloom": ("creative", "Bloom", ["Bloom"]),
    "Dark & Moody": ("moody", "暗调氛围", ["暗调", "氛围"]),
    "Golden Hour": ("warm", "金色时刻", ["金色"]),
    "Heatwave": ("warm", "热浪", ["热浪"]),
    "Honey Glow": ("warm", "蜂蜜色光泽", ["蜂蜜色"]),
    "Lush Nature": ("nature", "繁茂自然", ["自然"]),
    "Moody Forest": ("moody", "森林氛围", ["森林", "氛围"]),
    "Super Vivid": ("vivid", "鲜艳色彩", ["鲜艳"]),
    "Urban Pop": ("creative", "城市 Pop", ["城市"]),
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        f.write(data)
        temp = Path(f.name)
    temp.replace(path)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def selected_rows():
    receipt = read(ROOT / "photo-suitability-receipt-2026-10-30.json")
    if sha(CLASSIFICATION) != receipt["catalog_sha256"]:
        raise ValueError("Classification changed; review before activation")
    selected = [x for x in read(CLASSIFICATION)["cube_items"] if x["category"] == "direct"]
    if len(selected) != 50 or len({x["mapping_sha256"] for x in selected}) != 50:
        raise ValueError("Expected the reviewed 50 unique direct mappings")
    if any(x["format_blockers"] or x["conflicting_declarations"] for x in selected):
        raise ValueError("Selected LUT has unresolved blockers")
    return selected


def source_bytes(reader, origin):
    if "archive" in origin:
        relative = origin["archive"]
        path, digest = ROOT / relative, reader.manifest["source_archives"][relative]
    else:
        path, digest = reader.downloads[origin["download_id"]]
    if path.suffix.lower() == ".zip":
        data = reader.member(reader.zip(path, digest), origin["member"], str(path))
    else:
        data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != origin["sha256"]:
        raise ValueError("Original bytes changed: " + origin["member"])
    return data, path.relative_to(ROOT).as_posix(), digest


def naming(row, origin, name_counts):
    publisher = PUBLISHERS[origin["source_id"]]
    name = Path(origin["member"]).stem.removesuffix(" - Standard")
    short = name.removeprefix(publisher + " ")
    if publisher == "ON1":
        category, style, tags = ON1_STYLES[short]
    elif publisher == "xMosaique":
        category = "black-and-white" if "Mono" in short else "instant" if "Instant" in short or "Expired" in short else "film"
        style, tags = short, ["黑白"] if "Mono" in short else ["拍立得风格"] if category == "instant" else ["胶片风格"]
    else:
        prefix = short.split("-", 1)[0]
        category = "film" if prefix == "F" or short.startswith("K") else "cinematic"
        style = {"C": "冷色风格", "F": "胶片风格", "H": "热色风格", "W": "暖色风格", "X": "创意风格"}.get(prefix, short)
        tags = {"C": ["冷调"], "F": ["胶片"], "H": ["暖调"], "W": ["暖调"], "X": ["创意"]}.get(prefix, ["胶片"] if short.startswith("K") else [])
    suffix = f" · {row['grid_size']}³" if name_counts[(publisher, short)] > 1 else ""
    display = f"{publisher} {short}{suffix}"
    slug = re.sub(r"[^a-z0-9]+", "-", f"{publisher}-{short}".lower()).strip("-")
    if suffix:
        slug += f"-{row['grid_size']}"
    return slug, display, category, f"{style}（按来源命名，效果待验证）", tags


def verify():
    selected = selected_rows()
    later_path = ROOT / "photo-conversion-receipt-2026-10-30.json"
    later = read(later_path) if later_path.exists() else None
    snapshot = ROOT / later["backup_path"] / "catalog.json" if later else ROOT / "catalog.json"
    saved, all_actual = read(snapshot), scan()
    original_ids = {x["id"] for x in saved["items"]}
    actual = [x for x in all_actual if x["id"] in original_ids] if later else all_actual
    if saved["items"] != actual or saved["count"] != 50:
        raise ValueError("Runtime catalog differs from active files/metadata")
    if {x["technical"]["mapping_sha256"] for x in actual} != {x["mapping_sha256"] for x in selected}:
        raise ValueError("Runtime does not match the reviewed allowlist")
    for row in actual:
        engine_inspect((ROOT / row["path"]).read_bytes())
        LutMetadata.import_values(None, read(ROOT / row["metadata_path"]), row["original_sha256"])
        if not row.get("enabled") or row.get("photo_suitability", {}).get("category") != "direct":
            raise ValueError("Missing active photo classification")
        for doc in row["license"].get("documents", []):
            if not (ROOT / doc).is_file():
                raise ValueError("Missing source documentation: " + doc)
    receipt = read(RECEIPT)
    if sha(snapshot) != receipt["catalog_sha256"]:
        raise ValueError("Activation receipt no longer matches catalog")
    if len({x["name"] for x in actual}) != 50:
        raise ValueError("Ambiguous runtime display names")
    old = read(BACKUP / "catalog.json")["items"]
    current = {x["id"]: x for x in actual}
    for row in old:
        retained = current[row["id"]]
        for key in ("path", "original_sha256", "name"):
            if retained[key] != row[key]:
                raise ValueError("Existing LUT changed: " + row["id"])
    # This is the production catalog consumer; do not call describe_request/apply.
    from app.single_pass import catalog
    visible = catalog()
    if {r["id"] for r in visible} != {r["id"] for r in all_actual}:
        raise ValueError("Production reader does not expose all active entries")
    if later:
        # Follow the explicit receipt chain; don't waive the old 50-item checks.
        from convert_photo_luts import verify as verify_conversions
        verify_conversions()
    return {"active_luts": len(all_actual), "verified_original_activation_luts": len(actual),
            "existing_preserved": len(old), "new_luts": len(actual) - len(old),
            "runtime_reader_visible": len(visible), "subsequent_converted_luts": len(all_actual) - len(actual),
            "total_cube_bytes": sum(x["technical"]["bytes"] for x in actual),
            "checks": "allowlist, IDs, mapping and file hashes, importer syntax, metadata, license paths, production catalog reader",
            "effect_tests": 0, "lut_evaluations": "numerical loader checks only" if later else 0, "passed": True}


def activate():
    if RECEIPT.exists():
        return {**verify(), "activation": "already_applied"}
    selected = selected_rows()
    current = read(ROOT / "catalog.json")
    if current["items"] != scan():
        raise ValueError("Existing runtime catalog needs reconciliation first")
    by_mapping = {x["technical"]["mapping_sha256"]: x for x in current["items"]}
    if len(by_mapping) != 11 or not set(by_mapping).issubset({x["mapping_sha256"] for x in selected}):
        raise ValueError("Unexpected current runtime library")
    if BACKUP.exists():
        raise ValueError("Prior backup exists without completion receipt; inspect it first")
    choices = {x["id"]: next(a for a in x["source_assessments"] if a["category"] == "direct") for x in selected}
    name_counts = Counter((PUBLISHERS[choices[x["id"]]["origin"]["source_id"]], Path(choices[x["id"]]["origin"]["member"]).stem.removesuffix(" - Standard").removeprefix(PUBLISHERS[choices[x["id"]]["origin"]["source_id"]] + " ")) for x in selected)
    prepared, new_paths, records = [], [], []
    documents = {}
    iw_docs = [ROOT / "licenses/iwltbap-aspen/Readme - LUTs Color Grading Pack by IWLTBAP (Free).pdf",
               ROOT / "collected/2026-10-30/documents/iwltbap-free-sampler/LUTs Color Grading Pack (Free) by IWLTBAP/About - LUTs Color Grading Pack by IWLTBAP (Free).pdf"]
    for doc in iw_docs:
        documents[ROOT / "licenses/iwltbap-photo-2026-10-30" / doc.name] = doc.read_bytes()
    notice = (ROOT / "collected/2026-10-30/documents/xmosaique-all/THIRD-PARTY-NOTICES.txt").read_text()
    documents[ROOT / "licenses/xmosaique-THIRD-PARTY-NOTICES.txt"] = notice.encode()
    classification_hash = sha(CLASSIFICATION)
    with ExitStack() as stack:
        reader = OriginalReader(stack)
        staging = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="lut-photo-activation-")))
        for index, row in enumerate(selected):
            assessment = choices[row["id"]]
            origin = assessment["origin"]
            existing = by_mapping.get(row["mapping_sha256"])
            if existing:
                meta = read(ROOT / existing["metadata_path"])
                dest = ROOT / existing["path"]
                data = dest.read_bytes()
            else:
                data, archive, archive_hash = source_bytes(reader, origin)
                uid, name, category, style, tags = naming(row, origin, name_counts)
                dest = ROOT / "luts" / category / uid / (uid + ".cube")
                if dest.parent.exists():
                    raise ValueError("Refusing to overwrite an unregistered LUT directory")
                sid = origin["source_id"]
                docs = [p.relative_to(ROOT).as_posix() for p in documents if (sid == "iwltbap-free" and "iwltbap-photo" in str(p)) or (sid == "xmosaique" and p.name.startswith("xmosaique"))]
                license_id = "LicenseRef-" + sid
                if sid == "xmosaique":
                    license_id = "MIT" if Path(origin["member"]).name in notice.split("Source:")[0] else "CC-BY-NC-4.0"
                meta = {"schema_version": 1, "id": uid, "name": name, "publisher": PUBLISHERS[sid],
                        "filename": dest.name, "category": category, "style_zh": style, "tags": tags,
                        "source_page": origin["source_page"], "preview_page": origin["source_page"],
                        "source_archive": archive, "source_sha256": archive_hash, "archive_member": origin["member"],
                        "original_filename": Path(origin["member"]).name, "original_sha256": hashlib.sha256(data).hexdigest(),
                        "added_date": DATE, "batch": "2026-10-30 照片适用性接入；未测试效果",
                        "license": {"id": license_id, "status": origin["license_note"], "documents": docs, "redistribution_verified": False},
                        "file_modified": False, "style_basis": "author_filename_or_label_not_measured"}
                new_paths.append(dest.parent)
            tmp = staging / f"{index}.cube"
            tmp.write_bytes(data)
            technical = inspect_cube(tmp)
            engine_inspect(data)
            if technical["mapping_sha256"] != row["mapping_sha256"] or technical["sha256"] != meta["original_sha256"]:
                raise ValueError("Activated file does not match reviewed mapping/original bytes")
            aliases = sorted(set(row["aliases"] + [row["name"], Path(origin["member"]).stem]))
            basis = assessment["reason"] + " 本次仅按资料确认，未做新的照片效果测试。"
            meta.update({"input_profile": "sRGB / display-referred（来源声明；未做新增效果验证）",
                         "input_space": "srgb", "output_space": "srgb", "compatibility_basis": basis,
                         "aliases": aliases, "enabled": True, "effect_test_status": row["effect_test_status"],
                         "historical_preview_refs": row["historical_preview_refs"],
                         "photo_suitability": {"category": "direct", "mapping_id": row["id"],
                                               "classification_path": str(CLASSIFICATION.relative_to(ROOT)),
                                               "classification_sha256": classification_hash, "evidence_ids": assessment["evidence_ids"],
                                               "basis": "static_metadata_only", "activated_date": DATE},
                         "cautions": "照片效果尚未完成本轮验证；名称／标签不表示实测结果。" + (" 作者标记此款为实验版本。" if "K99" in meta["name"] else "")})
            if len(encoded(meta)) > 24000:
                raise ValueError("Sidecar exceeds browser import limit")
            LutMetadata.import_values(None, meta, meta["original_sha256"])
            prepared.append((dest, data, meta, technical))
            records.append({"id": meta["id"], "mapping_id": row["id"], "mapping_sha256": row["mapping_sha256"],
                            "path": dest.relative_to(ROOT).as_posix(), "sha256": technical["sha256"],
                            "source_id": origin["source_id"], "new": existing is None, "effect_test_status": row["effect_test_status"]})
    if len({m[2]["id"] for m in prepared}) != 50 or len({m[2]["name"] for m in prepared}) != 50:
        raise ValueError("Duplicate runtime ID or name")
    for path, data in documents.items():
        if path.exists() and path.read_bytes() != data:
            raise ValueError("Source notice changed: " + str(path))
    # Preserve old catalog and metadata before publishing any new active entries.
    BACKUP.mkdir(parents=True)
    previous_files = [ROOT / "catalog.json", ROOT / "CATALOG.md"] + [ROOT / x["metadata_path"] for x in current["items"]]
    for path in previous_files:
        backup = BACKUP / path.relative_to(ROOT)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, backup)
    try:
        for path, data in documents.items():
            if not path.exists():
                put(path, data)
        items = []
        for path, data, meta, technical in prepared:
            if not path.exists():
                put(path, data)
            meta_path = path.parent / "metadata.json"
            put(meta_path, encoded(meta))
            items.append({**meta, "path": path.relative_to(ROOT).as_posix(), "metadata_path": meta_path.relative_to(ROOT).as_posix(), "technical": technical})
        items.sort(key=lambda x: x["id"])
        lines = ["# 照片 LUT 运行目录", "", "共 50 种数值映射（原有 11 种 + 新增 39 种）。仅接入已分类为可直接使用的映射；本次未做效果测试。", "",
                 "[适用性依据](PHOTO-SUITABILITY.md) · [接入校验记录](photo-activation-receipt-2026-10-30.json)", "",
                 "| 名称 | 描述 | 网格 | 文件 | 来源 |", "|---|---|---:|---|---|"]
        for x in items:
            lines.append(f"| {x['name']} | {x['style_zh']} | {x['technical']['grid_size']}³ | [CUBE]({x['path']}) | [{x['publisher']}]({x['source_page']}) |")
        put(ROOT / "CATALOG.md", ("\n".join(lines) + "\n").encode())
        put(ROOT / "catalog.json", encoded({"schema_version": 1, "library_name": "Photo LUT Library", "count": 50, "items": items}))
        put(RECEIPT, encoded({"date": DATE, "scope": "local photo runtime activation only", "active_luts": 50, "existing_preserved": 11, "new_luts": 39,
                             "archived_cube_mappings": 941, "archived_hald_files": 293, "archived_auxiliary_files": 602,
                             "classification_path": str(CLASSIFICATION.relative_to(ROOT)), "classification_sha256": classification_hash,
                             "catalog_sha256": sha(ROOT / "catalog.json"), "previous_catalog_sha256": sha(BACKUP / "catalog.json"),
                             "backup_path": str(BACKUP.relative_to(ROOT)), "effect_tests": 0, "lut_evaluations": 0,
                             "analysis_jobs": 0, "conversions": 0, "new_downloads": 0, "published": False, "items": records}))
        return verify()
    except Exception:
        for path in previous_files:
            put(path, (BACKUP / path.relative_to(ROOT)).read_bytes())
        for path in new_paths:
            if path.exists():
                shutil.rmtree(path)
        if RECEIPT.exists():
            RECEIPT.unlink()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["apply", "verify"])
    args = parser.parse_args()
    print(json.dumps(activate() if args.action == "apply" else verify(), ensure_ascii=False, indent=2))
