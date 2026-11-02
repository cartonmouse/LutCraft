"""Offline inventory of existing LUT collections. Never downloads or renders.

Keep all source files. Merge CUBE records by exact numeric mapping plus domain;
keep other formats separate and deduplicate them by bytes only.
"""
import argparse
from collections import Counter, defaultdict
import copy
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from urllib.parse import quote
import zipfile

from library import inspect_cube

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "inventory/2026-10-30"
ASSISTED = ROOT / "collected/2026-10-30-assisted"
PUBLIC = ROOT / "collected/2026-10-30"
PURCHASED = ROOT / "purchased/2026-10-29"
AUX = {".xmp", ".3dl", ".csp", ".icc", ".icm", ".onpreset"}
DOC = {".txt", ".md", ".pdf", ".url", ".html", ".htm"}
PACK_IDS = {"ling-iphone-2": "purchased-ling", "pocket-action": "purchased-pocket", "xh-5219": "purchased-kodak"}
PACK_DIRS = {"林馆长iPhone 专用lut-合集2": "purchased-ling", "Pocket Action LUT预设": "purchased-pocket", "柯达 5219": "purchased-kodak"}
sys.path.insert(0, str(ROOT.parent / "backend"))
from app.luts import inspect_cube as engine_inspect  # noqa: E402
from app.errors import AppError  # noqa: E402


def checksum(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
        f.write(data)
        tmp = Path(f.name)
    tmp.replace(path)


def relative(path):
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def local(path):
    result = (ROOT / path).resolve()
    if not result.is_relative_to(ROOT.resolve()):
        raise ValueError("Path outside LUT library")
    return result


def preserve(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Refusing to overwrite changed file: {path}")
    else:
        path.write_bytes(data)


def archive_members(file, wanted, prefix="", depth=0, budget=None):
    """Read only data files; never execute or follow .url files."""
    if depth > 3:
        raise ValueError("Excessive archive nesting")
    budget = budget if budget is not None else [0]
    with zipfile.ZipFile(file) as z:
        seen = set()
        for item in z.infolist():
            p = PurePosixPath(item.filename)
            if p.is_absolute() or ".." in p.parts or "\\" in item.filename or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("Unsafe archive member")
            if item.is_dir() or "__MACOSX" in p.parts or any(t.startswith(".") for t in p.parts):
                continue
            if item.filename in seen:
                raise ValueError("Duplicate archive member name")
            seen.add(item.filename)
            budget[0] += item.file_size
            if budget[0] > 3 * 1024 ** 3 or item.file_size > 100 * 1024 ** 2:
                raise ValueError("Archive size limit exceeded")
            name = prefix + item.filename
            if p.suffix.lower() == ".zip":
                yield from archive_members(io.BytesIO(z.read(item)), wanted, name + "!", depth + 1, budget)
            elif p.suffix.lower() in wanted:
                yield name, z.read(item)


class Inventory:
    def __init__(self):
        self.cubes, self.auxiliary, self.documents = {}, {}, {}
        self.verified, self.cache, self.archives = {}, {}, {}
        self.halds, self.assisted_items = [], {}
        self.assisted_members, self.invalid = [], []
        self.registry = {i["id"]: i for i in read(ROOT / "sources.json")["items"]}

    def verify_file(self, path, expected):
        rel = relative(path)
        if rel not in self.verified:
            self.verified[rel] = checksum(path)
        if self.verified[rel] != expected:
            raise ValueError("Checksum mismatch: " + rel)

    def origin(self, source_id, **fields):
        source = self.registry[source_id]
        return {"source_id": source_id, "source_page": source.get("source_page", ""),
                "license_note": source.get("license_note", ""), **fields}

    def add_cube(self, item, path, origins, catalog):
        technical = item["technical"]
        self.verify_file(path, item["original_sha256"])
        self.cache[technical["sha256"]] = technical
        key = technical["mapping_sha256"]
        if key not in self.cubes:
            self.cubes[key] = {"id": "cube-" + key[:20], "name": item["name"], "format": "cube",
                               "path": relative(path), "original_sha256": item["original_sha256"],
                               "technical": technical, "aliases": [], "sources": [], "locations": [],
                               "catalog_refs": [], "runtime_ids": [], "historical_preview_refs": [],
                               "review_flags": [], "effect_test_status": "not_tested", "enabled": False}
        row = self.cubes[key]
        row["aliases"] = sorted(set(row["aliases"] + [item["name"]] + item.get("aliases", [])))
        row["sources"].extend(origins)
        row["locations"].append({"path": relative(path), "sha256": item["original_sha256"]})
        row["catalog_refs"].append({"catalog": catalog, "id": item["id"], "original_group": item.get("group")})
        if catalog == "catalog.json":
            row["runtime_ids"].append(item["id"])
            row["enabled"] = True
            row["historical_preview_refs"].append("previews/pink-grass-2026-10-28/README.md")
        if catalog.startswith("purchased/") and item.get("group") == "photo-candidates":
            row["historical_preview_refs"].extend(["purchased/2026-10-29/previews/coast/README.md", "purchased/2026-10-29/previews/pink-grass/README.md"])
        if item.get("engine_format_supported") is not None:
            row["engine_format_supported"] = item["engine_format_supported"]
        flags = set(row["review_flags"])
        if item.get("group") in {"video", "video-archive"}:
            flags.add("specialized_input_source")
        if item.get("group") == "device-review":
            flags.add("device_input_review")
        if item.get("group") == "photo-candidates":
            flags.add("historical_photo_priority")
        with path.open(encoding="utf-8-sig") as f:
            head = "".join(next(f, "") for _ in range(35))
        if re.search(r"adobe\s*rgb|adobergb|prophoto", head, re.I):
            flags.add("color_profile_header_review")
        for source in origins:
            filename = source.get("member", source.get("path", ""))
            if source["source_id"] == "lutify-free":
                match = re.search(r"-([A-Za-z0-9]+)-to-([A-Za-z0-9]+)\.cube$", filename, re.I)
                if match:
                    source["filename_input_label"], source["filename_output_label"] = match.groups()
                    flags.add("display_reference_label" if match.groups() == ("Rec709", "Rec709") else "specialized_input_source")
            elif re.search(r"\blog\b|v-log|s-log|d-log|slog|vlog|logc|delog", filename, re.I):
                flags.add("specialized_input_source")
        row["review_flags"] = sorted(flags)
        return row

    def add_data(self, name, content, origin, document=False, existing=None):
        suffix = PurePosixPath(name).suffix.lower()
        digest = hashlib.sha256(content).hexdigest()
        groups = self.documents if document else self.auxiliary
        key = suffix + ":" + digest
        if key not in groups:
            path = existing or OUT / ("documents" if document else "assets") / suffix.lstrip(".") / (digest + suffix)
            preserve(path, content)
            groups[key] = {"id": suffix.lstrip(".") + "-" + digest[:20], "name": PurePosixPath(name).name,
                           "format": suffix.lstrip("."), "path": relative(path), "sha256": digest,
                           "bytes": len(content), "sources": [], "enabled": False, "effect_test_status": "not_tested"}
        groups[key]["sources"].append({**origin, "sha256": digest, "bytes": len(content)})

    def base_collections(self):
        for directory in [ROOT, PURCHASED, PUBLIC]:
            catalog_path = directory / "catalog.json"
            self.verify_file(catalog_path, checksum(catalog_path))
            catalog = read(catalog_path)
            for item in catalog["items"]:
                origins = copy.deepcopy(item.get("sources", []))
                if directory == PURCHASED:
                    sid = PACK_IDS[item["pack"]]
                    origins = [self.origin(sid, **s) for s in origins]
                self.add_cube(item, directory / item["path"], origins, relative(catalog_path))
            if directory == PUBLIC:
                for item in catalog["haldcluts"]:
                    self.verify_file(directory / item["path"], item["original_sha256"])
                    self.halds.append({**item, "path": relative(directory / item["path"])})
        print(f"Existing catalogs: {len(self.cubes)} CUBE mappings, {len(self.halds)} HaldCLUT files", flush=True)

    def assisted(self):
        for sid in ["on1-free", "lutify-free", "film-crux-free", "phlearn-free"]:
            source = self.registry[sid]
            archive = local(source["local_archive"])
            receipt = read(local(source["download_receipt"]))
            self.verify_file(archive, receipt["sha256"])
            self.archives[relative(archive)] = receipt["sha256"]
            with zipfile.ZipFile(archive) as z:
                if z.testzip():
                    raise ValueError("ZIP CRC failure")
            count = 0
            for name, content in archive_members(archive, {".cube"} | AUX | DOC):
                suffix = PurePosixPath(name).suffix.lower()
                digest = hashlib.sha256(content).hexdigest()
                origin = self.origin(sid, archive=relative(archive), member=name, sha256=digest, bytes=len(content))
                self.assisted_members.append({**origin, "format": suffix})
                if suffix != ".cube":
                    self.add_data(name, content, origin, document=suffix in DOC)
                    continue
                with tempfile.NamedTemporaryFile(suffix=".cube") as tmp:
                    tmp.write(content)
                    tmp.flush()
                    try:
                        technical = self.cache.get(digest) or inspect_cube(Path(tmp.name))
                    except (ValueError, UnicodeError) as exc:
                        path = ASSISTED / "unparsed" / (digest + ".cube")
                        preserve(path, content)
                        self.invalid.append({**origin, "path": relative(path), "error": str(exc).replace(tmp.name, name)})
                        continue
                key = technical["mapping_sha256"]
                supported, error = True, None
                try:
                    engine_inspect(content)
                except AppError as exc:
                    supported, error = False, str(exc)
                if key not in self.assisted_items:
                    slug = re.sub(r"[^a-z0-9]+", "-", PurePosixPath(name).stem.lower()).strip("-")[:70]
                    path = ASSISTED / "assets/cube" / sid / (slug + "-" + key[:16] + ".cube")
                    preserve(path, content)
                    self.assisted_items[key] = {"id": sid + "-" + key[:16], "name": PurePosixPath(name).stem,
                        "format": "cube", "path": path.relative_to(ASSISTED).as_posix(), "original_sha256": digest,
                        "technical": technical, "engine_format_supported": supported, "engine_format_error": error,
                        "sources": [], "enabled": False, "effect_test_status": "not_tested", "compatibility": "unknown"}
                self.assisted_items[key]["sources"].append(origin)
                count += 1
            print(f"Assisted archive {sid}: {count} CUBE members", flush=True)
        for item in self.assisted_items.values():
            self.add_cube(item, ASSISTED / item["path"], copy.deepcopy(item["sources"]), relative(ASSISTED / "catalog.json"))

    def supplementary(self):
        inv = read(PURCHASED / "source-inventory.json")
        for record in inv["files"]:
            if "copied_path" not in record:
                continue
            path = PURCHASED / record["copied_path"]
            self.verify_file(path, record["sha256"])
            sid = PACK_DIRS[Path(record["path"]).parts[0]]
            if record["extension"] in AUX:
                self.add_data(path.name, path.read_bytes(), self.origin(sid, path=record["path"]), existing=path)
            elif record["extension"] == ".zip":
                self.archives[relative(path)] = record["sha256"]
                for name, content in archive_members(path, AUX | DOC):
                    self.add_data(name, content, self.origin(sid, archive=relative(path), member=name), document=PurePosixPath(name).suffix.lower() in DOC)
        manifest = read(ROOT / "free-downloads-2026-10-30.json")
        records = read(PUBLIC / "downloads.json")["items"] + manifest.get("existing_archives", [])
        for record in records:
            path = local(record["existing_path"]) if "existing_path" in record else PUBLIC / record["path"]
            self.verify_file(path, record["sha256"])
            if path.suffix.lower() == ".zip":
                self.archives[relative(path)] = record["sha256"]
                for name, content in archive_members(path, AUX):
                    self.add_data(name, content, self.origin(record["source_id"], archive=relative(path), member=name))
        for record in read(PUBLIC / "archive-inventory.json")["documents"]:
            path = PUBLIC / record["path"]
            self.verify_file(path, record["sha256"])
            self.add_data(record["member"], path.read_bytes(), record, document=True, existing=path)
        print(f"Supplementary formats: {len(self.auxiliary)} unique files; no format conversion", flush=True)

    def finish(self):
        cubes = sorted(self.cubes.values(), key=lambda i: (i["name"].lower(), i["id"]))
        for row in cubes:
            row["locations"] = list({p["path"]: p for p in row["locations"]}.values())
            row["historical_preview_refs"] = sorted(set(row["historical_preview_refs"]))
            if row["historical_preview_refs"]:
                row["effect_test_status"] = "historical_previews_available"
            row["photo_compatibility"] = "not_reassessed"
            if not row["sources"]:
                raise ValueError("Missing provenance: " + row["id"])
        by_source = {}
        for sid in self.registry:
            items = [i for i in cubes if any(s["source_id"] == sid for s in i["sources"])]
            if items or any(s["source_id"] == sid for i in self.halds for s in i["sources"]):
                by_source[sid] = {"name": self.registry[sid]["name"], "cube_source_files": sum(s["source_id"] == sid for i in items for s in i["sources"]),
                                 "cube_mappings": len(items), "hald_unique_files": sum(any(s["source_id"] == sid for s in i["sources"]) for i in self.halds)}
        summary = {"source_cube_files": sum(len(i["sources"]) for i in cubes), "unique_cube_mappings": len(cubes),
                   "redundant_cube_occurrences": sum(len(i["sources"]) - 1 for i in cubes),
                   "cube_mappings_with_multiple_origins": sum(len(i["sources"]) > 1 for i in cubes),
                   "runtime_cube_mappings": sum(bool(i["runtime_ids"]) for i in cubes),
                   "archived_cube_mappings_outside_runtime": sum(not i["runtime_ids"] for i in cubes),
                   "hald_unique_files": len(self.halds), "hald_identity_templates": sum(i.get("asset_role") == "identity_template" for i in self.halds),
                   "source_entries_with_local_assets": len(by_source), "auxiliary_unique_files": dict(Counter(i["format"] for i in self.auxiliary.values())),
                   "unparsed_cube_files": len(self.invalid), "new_effect_tests": 0, "new_downloads": 0}
        catalog = {"schema_version": 1, "date": "2026-10-30", "scope": "offline inventory; photos only; no new rendering or activation",
                   "path_base": "lut-library", "summary": summary, "per_source": by_source, "items": cubes, "haldcluts": self.halds,
                   "notes": ["CUBE按完整数值、网格和输入域合并；不同输入版本和不同格式不做视觉等效去重。", "源文件数不重复计算运行库的11份工作副本；它们已包含在免费原包来源中。", "新整理不代表已适配照片；以前生成的预览单独保留，本轮未生成预览。"]}
        write(OUT / "catalog.json", catalog)
        write(OUT / "auxiliary.json", {"path_base": "lut-library", "items": list(self.auxiliary.values()), "documents": list(self.documents.values()), "unparsed": self.invalid})
        write(OUT / "duplicates.json", {"method": "exact numeric CUBE mapping and domain", "originals_deleted": False,
                                        "items": [i for i in cubes if len(i["sources"]) > 1]})
        assisted_summary = {"source_cube_files": sum(len(i["sources"]) for i in self.assisted_items.values()),
                            "unique_cube_mappings": len(self.assisted_items), "new_cube_mappings": sum(all(r["catalog"] == relative(ASSISTED / "catalog.json") for r in self.cubes[k]["catalog_refs"]) for k in self.assisted_items),
                            "unparsed_cube_files": len(self.invalid), "formats": dict(Counter(m["format"] for m in self.assisted_members))}
        write(ASSISTED / "catalog.json", {"schema_version": 1, "summary": assisted_summary, "items": list(self.assisted_items.values())})
        write(ASSISTED / "archive-inventory.json", {"members": self.assisted_members, "unparsed": self.invalid})
        self.documentation(catalog, assisted_summary)
        for item in cubes:
            for location in item["locations"]:
                self.verified[location["path"]] = location["sha256"]
        for item in self.auxiliary.values():
            self.verified[item["path"]] = item["sha256"]
        for item in self.documents.values():
            self.verified[item["path"]] = item["sha256"]
        write(OUT / "verification-manifest.json", {"files": self.verified, "source_archives": self.archives})
        write(ROOT / "inventory-receipt-2026-10-30.json", {"summary": summary, "assisted_summary": assisted_summary,
              "catalog": relative(OUT / "catalog.json"), "catalog_sha256": checksum(OUT / "catalog.json"),
              "source_archive_count": len(self.archives), "source_archives": self.archives, "new_downloads": 0, "effect_test_status": "not_run_this_pass"})
        print(json.dumps(summary, ensure_ascii=False), flush=True)

    def documentation(self, catalog, assisted):
        s = catalog["summary"]
        lines = ["# 已有 LUT 总目录", "", "更新：2026-10-30。已按用户要求停止领取和下载；本次仅整理本地已有文件。", "",
                 f"共 **{s['source_cube_files']} 个 CUBE 来源文件**，按完整数值和输入域合并为 **{s['unique_cube_mappings']} 种颜色映射**。",
                 f"另有 **{s['hald_unique_files']} 个 HaldCLUT 文件**（含 {s['hald_identity_templates']} 个 Identity 模板），保持原格式。不同输入版本或格式不等于不同视觉风格。", "",
                 f"运行库仍为 **{s['runtime_cube_mappings']} 款**；其余 {s['archived_cube_mappings_outside_runtime']} 种 CUBE 映射归档待确认。本轮没有效果测试、色彩转换或运行库接入。", "",
                 "| 来源 | CUBE来源文件 | 来源内映射数 | HaldCLUT唯一文件 |", "|---|---:|---:|---:|"]
        for v in catalog["per_source"].values():
            lines.append(f"| {v['name']} | {v['cube_source_files']} | {v['cube_mappings']} | {v['hald_unique_files']} |")
        lines += ["", "来源之间可能共享映射，来源内映射数不能直接相加作为全库总数。源文件数不重复计入运行库工作副本。", "",
                  f"精确合并后记录 {s['redundant_cube_occurrences']} 个重复来源项，涉及 {s['cube_mappings_with_multiple_origins']} 组映射；所有原包和来源记录保留，未删除下载原件。", "",
                  "## 文件入口", "", "- [完整 CUBE 文件目录](inventory/2026-10-30/CUBES.md)",
                  "- [统一机器索引](inventory/2026-10-30/catalog.json)", "- [重复映射及全部来源](inventory/2026-10-30/duplicates.json)",
                  "- [其他格式与说明文档索引](inventory/2026-10-30/auxiliary.json)", "- [本次整理校验摘要](inventory-receipt-2026-10-30.json)",
                  "- [来源与领取进度](SOURCES.md)", "", "## 照片使用状态", "",
                  "- 以前的14款照片候选只是当时优先预览的子集，不是全库可用于照片的上限。其他素材完整保留。",
                  "- 输入空间、设备专用版本、Log版本、文件头颜色配置均保留在来源和复核标记中；不自动宣称与sRGB照片兼容。",
                  "- PHLEARN的10个CUBE为两套相同的5款；Lutify的150个CUBE属于5种风格的多输入版本，不算150种视觉风格。",
                  "- ON1部分文件头提到Adobe RGB，需后续核对照片输入；本次没有更改色值。",
                  "- 旧预览保持原记录，新领取资产仍为not_tested；项目当前只处理照片。", "",
                  "## 其他格式", "", "| 格式 | 按字节去重的文件数 |", "|---|---:|"]
        for fmt, count in sorted(s["auxiliary_unique_files"].items()):
            lines.append(f"| {fmt.upper()} | {count} |")
        lines += ["", "XMP、ONPreset和其他格式按原件归档，不计入CUBE数量，未做跨格式视觉去重或格式转换。", "",
                  "## 本地存储与复核", "", "原有目录不搬移：已购包在purchased/，首批免费包在collected/2026-10-30/，人工领取原包及CUBE在collected/2026-10-30-assisted/。统一索引和补充格式在inventory/2026-10-30/。", "",
                  "备份整个lut-library目录；已购包中的教程视频/安装程序仍在原下载位置，详见原购买库清单。所有授权说明保留；收集不代表已确认服务内置或再分发许可。", "",
                  "```bash", ".venv/bin/python lut-library/tools/organize_existing.py verify", "```", ""]
        (ROOT / "INVENTORY.md").write_text("\n".join(lines))
        lines = ["# CUBE 完整目录", "", "每行是一种精确数值映射。别名、全部来源、输入标记见同目录catalog.json；原文件路径相对于lut-library。", "",
                 "| 名称 | 网格 | 来源 | 状态 | 文件 |", "|---|---:|---|---|---|"]
        for row in catalog["items"]:
            name = row["name"].replace("|", "\\|").replace("\n", " ")
            sources = ", ".join(sorted({x["source_id"] for x in row["sources"]}))
            status = "已在运行库" if row["runtime_ids"] else "归档待确认"
            lines.append(f"| {name} | {row['technical']['grid_size']}³ | {sources} | {status} | [CUBE](../../{quote(row['path'])}) |")
        (OUT / "CUBES.md").write_text("\n".join(lines) + "\n")
        (ASSISTED / "README.md").write_text(f"# 人工领取 LUT 本地整理\n\n4个已下载原包，共{assisted['source_cube_files']}个CUBE来源文件，批内合并为{assisted['unique_cube_mappings']}种映射；相对于旧库新增{assisted['new_cube_mappings']}种映射。\n\n原包保留，独立CUBE在assets/cube/；XMP等补充格式与说明文档统一索引于[已有LUT总目录](../../INVENTORY.md)。未做效果测试。\n\n- [本批索引](catalog.json)\n- [原包成员清单](archive-inventory.json)\n")


def verify():
    catalog = read(OUT / "catalog.json")
    manifest = read(OUT / "verification-manifest.json")
    # A later, explicitly recorded activation may replace the runtime catalog.
    # Verify the original snapshot against its backup and the new runtime
    # against the activation receipt; never waive checks on archived assets.
    activation_path = ROOT / "photo-activation-receipt-2026-10-30.json"
    activation = read(activation_path) if activation_path.exists() else None
    conversion_path = ROOT / "photo-conversion-receipt-2026-10-30.json"
    conversion = read(conversion_path) if conversion_path.exists() else None
    for path, expected in manifest["files"].items():
        if path == "catalog.json" and activation:
            backup = local(activation["backup_path"] + "/catalog.json")
            if checksum(backup) != expected or expected != activation["previous_catalog_sha256"]:
                raise ValueError("Original runtime snapshot mismatch")
            activated_snapshot = local(conversion["backup_path"] + "/catalog.json") if conversion else local(path)
            if checksum(activated_snapshot) != activation["catalog_sha256"]:
                raise ValueError("Activated runtime catalog mismatch")
            if conversion:
                from activate_hald_luts import snapshot
                if checksum(snapshot()) != conversion["catalog_sha256"]:
                    raise ValueError("Converted runtime catalog mismatch")
            continue
        if checksum(local(path)) != expected:
            raise ValueError("Checksum mismatch: " + path)
    items = catalog["items"]
    if len({i["technical"]["mapping_sha256"] for i in items}) != len(items):
        raise ValueError("Duplicate unified mapping")
    for i in items:
        if bool(i["runtime_ids"]) != i["enabled"]:
            raise ValueError("Unexpected activation")
    summary = catalog["summary"]
    assert summary["unique_cube_mappings"] == len(items)
    assert summary["source_cube_files"] == sum(len(i["sources"]) for i in items)
    assert summary["source_cube_files"] == sum(i["cube_source_files"] for i in catalog["per_source"].values())
    if activation:
        assert summary["runtime_cube_mappings"] == activation["existing_preserved"]
        from activate_photo_luts import verify as verify_activation
        verify_activation()
    else:
        assert summary["runtime_cube_mappings"] == len(read(ROOT / "catalog.json")["items"])
    assert not read(OUT / "auxiliary.json")["unparsed"]
    receipt = read(ROOT / "inventory-receipt-2026-10-30.json")
    assert checksum(OUT / "catalog.json") == receipt["catalog_sha256"]
    print(f"Verified {len(manifest['files'])} local files; {len(items)} CUBE mappings; no downloads or effect tests.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "verify"])
    args = parser.parse_args()
    if args.command == "build":
        task = Inventory()
        task.base_collections()
        task.assisted()
        task.supplementary()
        task.finish()
    else:
        verify()
