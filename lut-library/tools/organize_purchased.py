"""Organize the three purchased packs locally, without changing source bytes.

Run with the project's .venv Python. This creates a separate review catalog;
it never adds unconfirmed color transforms to the runtime catalog.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote
import zipfile

from library import inspect_cube

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "backend"))
from app.errors import AppError  # noqa: E402
from app.luts import inspect_cube as inspect_engine  # noqa: E402

PACKS = {
    "Pocket Action LUT预设": "pocket-action",
    "林馆长iPhone 专用lut-合集2": "ling-iphone-2",
    "柯达 5219": "xh-5219",
}
GROUPS = {
    "photo-candidates": "照片候选（需样张确认）",
    "device-review": "设备/输入待确认",
    "video": "视频版本",
    "legacy": "旧版归档",
    "needs-conversion": "色彩空间或网格待处理",
}
SERIES = {"人像系列": "portrait", "胶片系列": "film", "经典系列": "classic", "限定系列": "special"}
XH_STYLES = ["柔和", "清晨", "明亮", "胶片", "冷调", "电影", "哈苏标准", "浓郁"]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def put(path, data):
    """Reruns are allowed only when the existing file is identical."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise FileExistsError(f"Refusing to overwrite changed file: {path}")
    else:
        with path.open("xb") as stream:
            stream.write(data)


def put_json(path, data):
    put(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode())


def classify(relative, technical, comments):
    parts, stem = relative.parts, relative.stem.strip()
    pack = PACKS[parts[0]]
    group, category = "device-review", "creative"
    profile = "原包未明确标注输入/输出色彩空间，需确认。"
    style, tags, evidence = stem, [], "原始文件名和目录名；非实拍测量结论"
    publisher = "未提供" if pack == "pocket-action" else "林馆长" if pack == "ling-iphone-2" else "XH / Una&XIAOHAN（随包署名）"
    name = stem
    if pack == "pocket-action":
        series = next((p for p in parts if p in SERIES), "限定系列")
        category = SERIES[series]
        tags = [series.removesuffix("系列"), stem]
        profile = "Pocket/Action 用途目录；具体设备拍摄配置、输入/输出空间未明确。"
        if "Rec709gamma2.4.icc" in comments:
            profile = "文件注释标注 Rec.709 gamma 2.4；不能据此确认与 sRGB 编码域等同。"
        if "AdobeRGB1998.icc" in comments:
            group = "needs-conversion"
            profile = "文件注释标注 Adobe RGB (1998)，需核实输入/输出并建立转换。"
    elif pack == "ling-iphone-2":
        category, tags = "cinematic", ["电影", "iPhone", stem.replace("林馆长", "")]
        if any("拍照教学" in p for p in parts):
            group = "photo-candidates"
            profile = "拍照教学目录，文件名标注 709；作为普通照片候选，sRGB 输入/输出仍需确认。"
        else:
            group = "video"
            profile = "Blackmagic Cam 视频教学目录；输入曲线和色域未明确，不假定为 Apple Log。"
    else:
        category, tags = "film", ["胶片", "5219"]
        if "老版本" in parts:
            group = "legacy"
            profile = "旧版 V-Log 用途目录，具体旧版输入仍需核实。" if "Log灰片调色、监看（5219）" in parts else "旧版标准用途目录，保留作对照。"
        elif "Log灰片调色、监看（5219）" in parts:
            group = "video"
            profile = "同目录新5219灰片剪辑-介绍.jpg 标注 vlog；按 V-Log 用途归档，未适配普通 sRGB 照片。"
        elif any(p.startswith("★苹果") for p in parts):
            group = "photo-candidates"
            profile = "标准格调目录；同目录新5219介绍.jpg 标注 LUMIX Lab 标准。普通照片候选，sRGB 输入/输出仍需确认。"
        else:
            profile = "大疆 Mimo 专用目录；具体设备、拍摄模式与输入/输出空间未明确。"
        match = re.fullmatch(r"XH[-_]5219[-_]([1-8])", stem)
        if match:
            style = XH_STYLES[int(match[1]) - 1]
            tags.append(style)
            name = f"XH 5219 {match[1]} · {style}"
            evidence = "随包新5219介绍.jpg / 新5219灰片剪辑-介绍.jpg 的编号说明"
        elif "H哈苏" in stem:
            tags.append(stem.removeprefix("H"))
    if technical["grid_size"] not in (13, 17, 32, 33, 65):
        group = "needs-conversion"
        profile += f" 当前项目不支持 {technical['grid_size']}³ 网格，原件保留。"
    return {"pack": pack, "group": group, "category": category,
            "name": name, "style_zh": style, "tags": tags, "publisher": publisher,
            "input_profile": profile, "style_basis": evidence}


def verify(root):
    catalog = json.loads((root / "catalog.json").read_text())
    ids, mappings = set(), set()
    for item in catalog["items"]:
        path = (root / item["path"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Catalog path escapes the collection")
        current = inspect_cube(path)
        if current != item["technical"] or current["sha256"] != item["original_sha256"]:
            raise ValueError(f"LUT changed: {item['id']}")
        if item["id"] in ids or current["mapping_sha256"] in mappings:
            raise ValueError("Duplicate ID or numeric mapping")
        ids.add(item["id"])
        mappings.add(current["mapping_sha256"])
        metadata = json.loads((root / item["metadata_path"]).read_text())
        if metadata != {k: v for k, v in item.items() if k not in ("path", "metadata_path")}:
            raise ValueError(f"Metadata mismatch: {item['id']}")
    inventory = json.loads((root / "source-inventory.json").read_text())
    for file in inventory["files"]:
        copied = file.get("copied_path")
        if copied and digest(root / copied) != file["sha256"]:
            raise ValueError(f"Copied file changed: {copied}")
    cubes = [f for f in inventory["files"] if f["extension"] == ".cube"]
    sources = [s for item in catalog["items"] for s in item["sources"]]
    if Counter((s["path"], s["sha256"]) for s in sources) != Counter((f["path"], f["sha256"]) for f in cubes):
        raise ValueError("Source inventory does not match LUT provenance")
    for file in cubes:
        if file["organized_id"] not in ids:
            raise ValueError("Source has no organized asset")
    if catalog["count"] != len(ids) or catalog["source_cube_count"] != len(cubes):
        raise ValueError("Catalog counts differ")
    if catalog["group_counts"] != dict(sorted(Counter(i["group"] for i in catalog["items"]).items())):
        raise ValueError("Group counts differ")
    print(json.dumps({"verified_luts": len(ids), "source_cubes": len(cubes),
                      "group_counts": catalog["group_counts"]}, ensure_ascii=False))


def organize(source, output, added_date):
    source, output = source.resolve(), output.resolve()
    if not source.is_dir() or source == output or output.is_relative_to(source):
        raise ValueError("Use an existing source and an output outside the source tree")
    files = sorted(p for p in source.rglob("*") if p.is_file() and not any(x.startswith(".") for x in p.relative_to(source).parts))
    if any(p.is_symlink() or not p.resolve().is_relative_to(source) for p in files):
        raise ValueError("Source files must remain inside the source tree")
    unknown = {p.relative_to(source).parts[0] for p in files} - PACKS.keys()
    if unknown:
        raise ValueError(f"Unrecognized packs: {unknown}")
    inventory, cubes, mapping_groups = [], [], defaultdict(list)
    for path in files:
        relative = path.relative_to(source)
        suffix = path.suffix.lower()
        record = {"path": relative.as_posix(), "extension": suffix,
                  "bytes": path.stat().st_size, "sha256": digest(path)}
        if suffix == ".cube":
            technical = inspect_cube(path)
            comments = "\n".join(line for line in path.read_text(encoding="utf-8-sig").splitlines() if line.lstrip().startswith("#"))
            info = classify(relative, technical, comments)
            error = None
            try:
                inspect_engine(path.read_bytes())
            except AppError as exc:
                error = str(exc)
            cube = {**info, "source": record, "technical": technical,
                    "engine_format_supported": error is None, "engine_error": error}
            cubes.append(cube)
            mapping_groups[technical["mapping_sha256"]].append(cube)
        elif suffix in (".xmp", ".zip", ".jpg", ".jpeg", ".png", ".txt", ".pdf"):
            section = "xmp" if suffix == ".xmp" else "archives" if suffix == ".zip" else "support"
            target = Path(section) / PACKS[relative.parts[0]] / Path(*relative.parts[1:])
            put(output / target, path.read_bytes())
            record["copied_path"] = target.as_posix()
            if suffix == ".zip":
                with zipfile.ZipFile(path) as archive:
                    record["archive_entries"] = [{"name": member.filename, "bytes": member.file_size}
                                                 for member in archive.infolist() if not member.is_dir()]
        else:
            record["retention"] = "原位置保留；通过 source_root + path 定位，未复制视频教程或安装程序"
        inventory.append(record)

    items = []
    priority = {key: i for i, key in enumerate(GROUPS)}
    # Prefer current photo variants, then device variants, then legacy aliases.
    for mapping, group in sorted(mapping_groups.items()):
        group.sort(key=lambda x: (priority[x["group"]], x["source"]["path"]))
        chosen = group[0]
        slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", Path(chosen["source"]["path"]).stem.lower()).strip("-")
        uid = f"{chosen['pack']}-{slug}-{mapping[:8]}"
        folder = Path(chosen["group"]) / chosen["pack"] / uid
        filename = uid + ".cube"
        put(output / folder / filename, (source / chosen["source"]["path"]).read_bytes())
        metadata = {"schema_version": 1, "id": uid, "filename": filename,
                    **{k: chosen[k] for k in ("pack", "group", "name", "category", "style_zh", "tags", "publisher", "input_profile", "style_basis", "engine_format_supported", "engine_error")},
                    "aliases": sorted({Path(c["source"]["path"]).stem.strip() for c in group}),
                    "source_page": "", "source_root": str(source),
                    "original_filename": Path(chosen["source"]["path"]).name,
                    "original_sha256": chosen["technical"]["sha256"],
                    "sources": [{"path": c["source"]["path"], "sha256": c["source"]["sha256"],
                                 "input_profile": c["input_profile"], "original_group": c["group"]} for c in group],
                    "technical": chosen["technical"], "added_date": added_date,
                    "file_modified": False, "enabled": False, "compatibility": "unknown",
                    "input_space": "unknown", "output_space": "unknown",
                    "compatibility_basis": chosen["input_profile"],
                    "cautions": "目录分类和格式检查不等于 sRGB 兼容性确认；在指定输入条件下预览后再接入自动调色。",
                    "license": {"id": "LicenseRef-Purchased-Unverified", "purchase_basis": "用户声明已购买",
                                "status": "下载材料未提供明确的软件嵌入或再分发授权条款；购买凭证和条款待补录。",
                                "redistribution_verified": False}}
        put_json(output / folder / "metadata.json", metadata)
        items.append({**metadata, "path": (folder / filename).as_posix(),
                      "metadata_path": (folder / "metadata.json").as_posix()})
        for c in group:
            c["source"]["organized_id"] = uid

    items.sort(key=lambda x: (priority[x["group"]], x["pack"], x["name"]))
    catalog = {"schema_version": 1, "library_name": "Purchased LUT Review Library",
               "added_date": added_date, "source_root": str(source), "count": len(items),
               "source_cube_count": len(cubes), "duplicate_mapping_count": len(cubes) - len(items),
               "group_counts": dict(sorted(Counter(i["group"] for i in items).items())),
               "items": items}
    put_json(output / "catalog.json", catalog)
    put_json(output / "source-inventory.json", {"schema_version": 1, "source_root": str(source),
             "file_count": len(files), "bytes": sum(f["bytes"] for f in inventory), "files": inventory})
    put_json(output / "photo-candidates.json", {"schema_version": 1, "count": sum(i["group"] == "photo-candidates" for i in items),
             "items": [i for i in items if i["group"] == "photo-candidates"]})
    lines = ["# 购买 LUT 素材目录", "", f"来源：`{source}`。{len(cubes)} 个源 CUBE，按完整数值映射去重后保留 {len(items)} 个；原文件未改动。", "",
             "标签来自文件名、目录名和随包介绍，不是经过实拍验证的适用性结论。所有条目均保留为待确认资产。", ""]
    for key, title in GROUPS.items():
        subset = [i for i in items if i["group"] == key]
        lines += [f"## {title} · {len(subset)} 款", "", "| 名称 | 包 | 网格 | 文件 / 元数据 |", "|---|---|---|---|"]
        for i in subset:
            lines.append(f"| {i['name']} | {i['pack']} | {i['technical']['grid_size']}³ | [CUBE]({quote(i['path'])}) · [详情]({quote(i['metadata_path'])}) |")
        lines.append("")
    lines += ["## 重复映射", "", "重复项只保留一份可使用文件；各源文件的原名、路径和独立 SHA-256 保存在 metadata.json 的 sources 中。", ""]
    for i in items:
        if len(i["sources"]) > 1:
            lines.append(f"- `{i['id']}`：" + "；".join(s["path"] for s in i["sources"]))
    lines.append("")
    put(output / "CATALOG.md", "\n".join(lines).encode())
    readme = f"""# 三套购买 LUT 的项目素材库

整理日期：{added_date}。共 {len(cubes)} 个源 CUBE，去重后 {len(items)} 款。

- [完整目录](CATALOG.md)：名称、分类、网格、文件与元数据。
- [完整机器索引](catalog.json) / [照片候选索引](photo-candidates.json)：路径相对此目录。
- [原包文件清单](source-inventory.json)：所有源文件的路径、大小和 SHA-256，以及视频/安装程序的原始位置。
- `photo-candidates/`：林馆长 709 拍照版 6 款、XH 5219 标准新版 8 款，优先做照片效果确认。
- `device-review/`：Pocket/Action、Mimo 及注明 Rec.709 gamma 2.4 的文件，输入条件待核实。
- `video/`：XH 新版 V-Log 及林馆长 Blackmagic 视频版本；不自动套用普通照片。
- `legacy/`：旧版对照。与其他目录完全相同的映射以别名保留，不重复存储。
- `needs-conversion/`：星台光（40³ / Adobe RGB）、透亮室内（32³ / Adobe RGB）。未改写或重采样原 LUT。
- `xmp/`：46 个松散 Lightroom 预设（45 个不同文件）；`archives/` 保留原 4 个 ZIP，未解包执行。
- `support/`：11 张随包说明图片。教程视频及安装程序留在原下载目录。

每款的 `metadata.json` 记录稳定 ID、来源、原名、标签依据、输入条件、校验值和重复来源；原始 CUBE 数值与注释均保留。分类不代表 sRGB 已确认，`enabled=false`，没有并入项目自动选择的主 `catalog.json`。同一数值映射的不同用途名称只作为来源别名，不据此推断两种输入条件等同。

项目接入顺序：先从照片候选目录做本地样张对比，核实输入/输出与项目 sRGB 管线后，再将确认的条目加入主库。旧版网页可选择 `photo-candidates/` 批量导入为“待确认”；目前单次调色界面仅使用主库。

用户已说明购买；本地材料没有明确的软件嵌入、在线服务或再分发条款，`重要声明.jpg` 是调色使用说明。授权记录暂存为待补录。整个 `purchased/` 已排除普通 Git，现有 Program 打包脚本只读主库，不包含本目录。

原始下载目录：`{source}`。这里保留 LUT、XMP、ZIP 和说明图；备份教程视频时还需保留原始下载目录。复核：

```bash
.venv/bin/python lut-library/tools/organize_purchased.py --verify --output {output.relative_to(PROJECT) if output.is_relative_to(PROJECT) else output}
```
"""
    put(output / "README.md", readme.encode())
    verify(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--date", default="2026-10-29")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify(args.output)
    elif args.source:
        organize(args.source, args.output, args.date)
    else:
        parser.error("--source is required unless --verify is used")


if __name__ == "__main__":
    main()
