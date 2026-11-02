"""Fetch and inventory publicly offered LUTs; never render or enable them.

Reads an explicit URL manifest. Archives are retained unchanged, and only
allowlisted data/document members are extracted. Uses the project Python.
"""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import urllib.request
import zipfile

from PIL import Image
from library import inspect_cube

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "backend"))
from app.errors import AppError  # noqa: E402
from app.luts import inspect_cube as engine_inspect  # noqa: E402

MAX_DOWNLOAD = 600 * 1024 * 1024
MAX_MEMBER = 100 * 1024 * 1024
MAX_EXPANDED = 3 * 1024 * 1024 * 1024
DOC_SUFFIXES = {".txt", ".md", ".pdf", ".html", ".htm"}


def sha(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")
        temp = Path(file.name)
    temp.replace(path)


def preserve(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"Refusing to overwrite changed asset: {path}")
    else:
        with path.open("xb") as file:
            file.write(content)


def safe_path(root, relative):
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("Path leaves the collection")
    return target


def fetch_one(spec, output, previous):
    if not re.fullmatch(r"[a-z0-9-]+", spec["id"]):
        raise ValueError("Download ID must be a slug")
    path = output / "downloads" / (spec["id"] + spec["extension"])
    path.parent.mkdir(parents=True, exist_ok=True)
    result = {**spec, "path": path.relative_to(output).as_posix()}
    if path.exists():
        if not previous or previous.get("sha256") != sha(path):
            raise ValueError(f"Untracked/modified download: {path}")
        return previous
    temp = path.with_suffix(path.suffix + ".part")
    try:
        request = urllib.request.Request(spec["url"], headers={"User-Agent": "Mozilla/5.0 LUT-Archive/1.0"})
        with urllib.request.urlopen(request, timeout=45) as response, temp.open("wb") as file:
            if response.headers.get_content_type() == "text/html":
                raise ValueError("Download returned an HTML page instead of a LUT/archive")
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_DOWNLOAD:
                    raise ValueError("Download exceeds collection limit")
                file.write(chunk)
            result["resolved_url"] = response.url
        if spec["extension"] == ".zip":
            with zipfile.ZipFile(temp) as archive:
                if sum(m.file_size for m in archive.infolist()) > MAX_EXPANDED:
                    raise ValueError("Archive exceeds expanded size limit")
                if archive.testzip():
                    raise ValueError("ZIP CRC failure")
        elif spec["extension"] == ".cube" and b"LUT_3D_SIZE" not in temp.read_bytes():
            raise ValueError("Not a 3D CUBE download")
        temp.replace(path)
        result.update(bytes=path.stat().st_size, sha256=sha(path), status="downloaded")
        return result
    finally:
        temp.unlink(missing_ok=True)


def fetch(config, output):
    report_path = output / "downloads.json"
    old = json.loads(report_path.read_text()) if report_path.exists() else {"items": []}
    previous = {i["id"]: i for i in old["items"]}
    requested = {item["id"] for item in config["downloads"]}
    rows = {key: value for key, value in previous.items() if key in requested}
    failures = []
    def save():
        write_json(report_path, {"date": config["date"], "items": sorted(rows.values(), key=lambda r: r["id"]), "errors": failures})
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_one, spec, output, previous.get(spec["id"])): spec for spec in config["downloads"]}
        for future in as_completed(futures):
            spec = futures[future]
            try:
                result = future.result()
                rows[result["id"]] = result
                print(f"OK {result['id']}: {result['bytes']:,} bytes", flush=True)
            except Exception as exc:
                failures.append({"id": spec["id"], "url": spec["url"], "error": str(exc)})
                print(f"FAILED {spec['id']}: {exc}", flush=True)
            save()
    return not failures


def members(file, is_zip, prefix="", depth=0, budget=None):
    if not is_zip:
        yield file.name, file.read_bytes()
        return
    if depth > 3:
        raise ValueError("Nested archive depth exceeds collection limit")
    if budget is None:
        budget = [0]
    with zipfile.ZipFile(file) as archive:
        budget[0] += sum(member.file_size for member in archive.infolist())
        if budget[0] > MAX_EXPANDED:
            raise ValueError("Nested archive exceeds expanded size limit")
        seen = set()
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in member.filename or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("Unsafe archive member: " + member.filename)
            if member.is_dir() or "__MACOSX" in path.parts or any(p.startswith(".") for p in path.parts):
                continue
            if member.filename in seen:
                raise ValueError("Duplicate archive member: " + member.filename)
            seen.add(member.filename)
            if member.file_size > MAX_MEMBER:
                continue
            suffix = path.suffix.lower()
            if suffix == ".zip":
                yield from members(io.BytesIO(archive.read(member)), True,
                                   prefix + member.filename + "!", depth + 1, budget)
            elif suffix in {".cube", ".3dl", ".png", ".tif", ".tiff", ".xmp"} | DOC_SUFFIXES or path.name.lower().startswith(("license", "copying", "readme")):
                yield prefix + member.filename, archive.read(member)


def existing_mappings():
    result = defaultdict(list)
    for catalog in [ROOT / "catalog.json", ROOT / "purchased/2026-10-29/catalog.json"]:
        if not catalog.exists():
            continue
        for item in json.loads(catalog.read_text())["items"]:
            key = item["technical"].get("mapping_sha256")
            if key:
                result[key].append({"catalog": catalog.relative_to(ROOT).as_posix(), "id": item["id"]})
    return result


def index(config, output):
    records = json.loads((output / "downloads.json").read_text())
    sources = {s["id"]: s for s in config["sources"]}
    archive_rows = records["items"] + config.get("existing_archives", [])
    cubes, halds, docs, others, invalid = {}, {}, [], [], []
    old = existing_mappings()
    for archive_row in archive_rows:
        source = sources[archive_row["source_id"]]
        path = safe_path(ROOT, archive_row["existing_path"]) if "existing_path" in archive_row else safe_path(output, archive_row["path"])
        if sha(path) != archive_row["sha256"]:
            raise ValueError("Source archive changed: " + str(path))
        count = 0
        for name, content in members(path, path.suffix.lower() == ".zip"):
            suffix = PurePosixPath(name).suffix.lower()
            checksum = hashlib.sha256(content).hexdigest()
            origin = {"source_id": source["id"], "download_id": archive_row["id"], "member": name,
                      "sha256": checksum, "bytes": len(content), "source_page": source["page"],
                      "license_note": source["license_note"], "input_note": source["input_note"]}
            origin["source_page"] = archive_row.get("source_page", source["page"])
            origin["declared_license"] = source.get("declared_license", "not_confirmed")
            if source["id"] == "xmosaique" and suffix == ".cube":
                mit_names = {"LoFi 160", "LoFi 400", "Dusty Slide", "Muted Negative", "Lime Cross",
                             "Cyan Cross", "Citrus Instant", "Warm Instant", "Cold Instant",
                             "Expired Amber", "Sepia Print", "Silver Mono", "Infrared Mono"}
                origin["declared_license"] = "MIT (upstream rights unverified)" if PurePosixPath(name).stem in mit_names else "CC-BY-NC-4.0"
            if suffix == ".cube":
                # Inspection is structural only; no LUT engine is executed.
                with tempfile.NamedTemporaryFile(suffix=".cube") as tmp:
                    tmp.write(content)
                    tmp.flush()
                    try:
                        technical = inspect_cube(Path(tmp.name))
                    except (ValueError, UnicodeError) as exc:
                        relative = f"unparsed/{archive_row['id']}/{checksum[:16]}.cube"
                        preserve(output / relative, content)
                        invalid.append({**origin, "path": relative, "error": str(exc).replace(tmp.name, name)})
                        continue
                key = technical["mapping_sha256"]
                filename = PurePosixPath(name).name
                group = "video-archive" if re.search(r"\blog\b|v-log|s-log|d-log|slog|vlog|logc|delog", name, re.I) else "unreviewed"
                if key not in cubes:
                    slug = re.sub(r"[^a-z0-9]+", "-", PurePosixPath(name).stem.lower()).strip("-")[:72] or "lut"
                    relative = f"assets/cube/{source['id']}/{slug}-{key[:16]}.cube"
                    preserve(output / relative, content)
                    supported, error = True, None
                    try:
                        engine_inspect(content)
                    except AppError as exc:
                        supported, error = False, str(exc)
                    cubes[key] = {"id": source["id"] + "-" + key[:16], "name": PurePosixPath(name).stem,
                                  "path": relative, "filename": Path(relative).name, "format": "cube",
                                  "original_sha256": checksum, "technical": technical,
                                  "engine_format_supported": supported, "engine_format_error": error,
                                  "group": group, "enabled": False, "compatibility": "unknown",
                                  "effect_test_status": "not_tested", "sources": [], "duplicate_of_existing": old.get(key, [])}
                cubes[key]["sources"].append(origin)
                if group == "unreviewed":
                    cubes[key]["group"] = group
                count += 1
            elif source.get("format") == "haldclut" and suffix in {".png", ".tif", ".tiff"}:
                with Image.open(io.BytesIO(content)) as image:
                    width, height = image.size
                    level = round(width ** (1 / 3))
                    valid = width == height and level ** 3 == width and level >= 2
                    image.verify()
                if not valid:
                    others.append({**origin, "format": suffix, "reason": "Not square HaldCLUT dimensions; retained in archive"})
                    continue
                if checksum not in halds:
                    slug = re.sub(r"[^a-z0-9]+", "-", PurePosixPath(name).stem.lower()).strip("-")[:72]
                    relative = f"assets/haldclut/{slug}-{checksum[:16]}{suffix}"
                    preserve(output / relative, content)
                    halds[checksum] = {"id": source["id"] + "-" + checksum[:16], "name": PurePosixPath(name).stem,
                                       "format": "haldclut", "path": relative, "original_sha256": checksum,
                                       "asset_role": "identity_template" if "identity" in name.lower() else "unreviewed_look",
                                       "width": width, "height": height, "hald_level": level,
                                       "engine_format_supported": False, "enabled": False, "compatibility": "unknown",
                                       "effect_test_status": "not_tested", "sources": []}
                halds[checksum]["sources"].append(origin)
            elif suffix in DOC_SUFFIXES or PurePosixPath(name).name.lower().startswith(("license", "copying", "readme")):
                relative = f"documents/{archive_row['id']}/{name}"
                target = safe_path(output, relative)
                preserve(target, content)
                docs.append({**origin, "path": relative})
            else:
                others.append({**origin, "format": suffix, "reason": "Original retained in archive; not converted or imported"})
        print(f"Indexed {archive_row['id']}: {count} CUBE members", flush=True)
    items = sorted(cubes.values(), key=lambda r: (r["sources"][0]["source_id"], r["name"]))
    hald_items = sorted(halds.values(), key=lambda r: r["name"])
    per_source = {}
    for source in sources:
        found = [i for i in items if any(s["source_id"] == source for s in i["sources"])]
        per_source[source] = {"cube_files": sum(s["source_id"] == source for i in items for s in i["sources"]),
                              "unique_cube_mappings": len(found),
                              "matches_existing": sum(bool(i["duplicate_of_existing"]) for i in found),
                              "haldclut_files": sum(s["source_id"] == source for i in hald_items for s in i["sources"])}
    summary = {"source_cube_files": sum(len(i["sources"]) for i in items), "unique_cube_mappings": len(items),
               "matches_existing_mappings": sum(bool(i["duplicate_of_existing"]) for i in items),
               "new_cube_mappings": sum(not i["duplicate_of_existing"] for i in items),
               "video_archive_mappings": sum(i["group"] == "video-archive" for i in items),
               "engine_format_supported_mappings": sum(i["engine_format_supported"] for i in items),
               "source_haldclut_files": sum(len(i["sources"]) for i in hald_items), "unique_haldclut_files": len(hald_items),
               "hald_identity_templates": sum(i["asset_role"] == "identity_template" for i in hald_items),
               "unparsed_cube_files": len(invalid), "document_files": len(docs), "other_archive_members": len(others)}
    write_json(output / "catalog.json", {"schema_version": 1, "date": config["date"],
               "scope": "local collection only; no effect testing or runtime activation",
               "summary": summary, "per_source": per_source, "items": items, "haldcluts": hald_items})
    write_json(output / "archive-inventory.json", {"documents": docs, "other_members": others, "unparsed": invalid})
    lines = ["# 免费 LUT 收集目录", "", "本批仅下载、归档、结构检查及精确去重；没有渲染照片、转换颜色空间或启用到运行库。", "",
             f"CUBE 源文件 {summary['source_cube_files']} 个，批内去重后 {len(items)} 种映射；其中 {summary['matches_existing_mappings']} 种与已有库相同，新增 {summary['new_cube_mappings']} 种。", "",
             f"另有 {len(hald_items)} 个按文件内容去重的 HaldCLUT（含 {summary['hald_identity_templates']} 个 Identity 空白模板），保持原格式；未与 CUBE 做跨格式效果去重，不能将两者相加宣称独立风格总数。", "",
             "| 来源 | CUBE 文件 | 来源内映射数 | 与已有库相同 | HaldCLUT 文件 |", "|---|---:|---:|---:|---:|"]
    for key, value in per_source.items():
        lines.append(f"| [{sources[key]['name']}]({sources[key]['page']}) | {value['cube_files']} | {value['unique_cube_mappings']} | {value['matches_existing']} | {value['haldclut_files']} |")
    lines += ["", "来源间可能共享映射，因此来源内映射数之和可能大于全批去重数。下载和旧包均保留，重复来源在每款 sources 字段中可追溯。", "",
              "- [完整机器目录](catalog.json)", "- [下载记录与校验值](downloads.json)", "- [原包附属文件清单](archive-inventory.json)",
              "- `downloads/`：本轮原始下载；历史 IWLTBAP 原包复用 ../../_sources/。",
              "- `assets/`：保留原始字节的去重 CUBE / HaldCLUT。",
              "- `documents/`、`evidence/`：原包说明和获取时的公开来源页面。",
              "", "全部素材标记为待测试。输入名称、品牌和风格来自源文件，未验证照片适用性。免费获取和项目服务授权分别记录；CC BY-NC 等限制及上游授权不明条目不能直接用于商业服务。", ""]
    (output / "README.md").write_text("\n".join(lines))
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def verify(output):
    catalog = json.loads((output / "catalog.json").read_text())
    items = catalog["items"] + catalog["haldcluts"]
    seen = set()
    for item in items:
        if item["id"] in seen or sha(safe_path(output, item["path"])) != item["original_sha256"]:
            raise ValueError("Duplicate ID or asset checksum failure")
        seen.add(item["id"])
        if item["enabled"] or item["effect_test_status"] != "not_tested":
            raise ValueError("Collection must remain untested and disabled")
        if item["format"] == "cube" and inspect_cube(output / item["path"]) != item["technical"]:
            raise ValueError("CUBE structure changed")
    for row in json.loads((output / "downloads.json").read_text())["items"]:
        if sha(output / row["path"]) != row["sha256"]:
            raise ValueError("Download checksum failure")
    inventory = json.loads((output / "archive-inventory.json").read_text())
    for row in inventory["documents"] + inventory["unparsed"]:
        if sha(output / row["path"]) != row["sha256"]:
            raise ValueError("Document/quarantine checksum failure")
    print(f"Verified {len(items)} archived LUT assets; no effect testing performed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["fetch", "index", "verify"])
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.manifest.read_text())
    output = safe_path(ROOT, config["output"])
    output.mkdir(parents=True, exist_ok=True)
    if args.command == "fetch":
        if not fetch(config, output):
            raise SystemExit(1)
    elif args.command == "index":
        index(config, output)
    else:
        verify(output)


if __name__ == "__main__":
    main()
