"""Classify archived LUTs for the project's encoded-sRGB photo pipeline.

Offline metadata inspection only: no downloading, image rendering, LUT evaluation,
conversion, or runtime-library writes. Original occurrences are assessed separately
before merging their exact numeric mappings. See PHOTO-SUITABILITY.md for scope.
"""
from collections import Counter, defaultdict
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
from urllib.parse import quote
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "inventory/2026-10-30/photo-suitability"
PURCHASED = Path(os.environ.get("LUT_PURCHASED_SOURCE", str(Path.home() / "Downloads/baiduCloud/Lut")))
LABELS = {"direct": "可直接用（依据声明）", "conversion_required": "需要转换／适配", "uncertain": "还不确定"}
SUPPORTED_GRIDS = {13, 17, 32, 33, 65}
NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def local(relative):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError("Library path escapes root")
    return path


def header(data):
    lines = []
    for line in data.decode("utf-8-sig").splitlines():
        tokens = line.split("#", 1)[0].split()
        if len(tokens) == 3 and all(NUMBER.fullmatch(t) for t in tokens):
            break
        # Do not copy large serialized editor sessions into the evidence index.
        if len(line) < 2000:
            lines.append(line)
    return "\n".join(lines).strip()


class OriginalReader:
    def __init__(self, stack):
        self.stack, self.archives, self.containers = stack, {}, {}
        self.verified_sources = 0
        downloads = read(ROOT / "collected/2026-10-30/downloads.json")["items"]
        self.downloads = {d["id"]: (local("collected/2026-10-30/" + d["path"]), d["sha256"]) for d in downloads}
        for d in read(ROOT / "free-downloads-2026-10-30.json")["existing_archives"]:
            self.downloads[d["id"]] = (local(d["existing_path"]), d["sha256"])
        self.manifest = read(ROOT / "inventory/2026-10-30/verification-manifest.json")

    def zip(self, path, expected):
        key = str(path)
        if key not in self.archives:
            if sha(path) != expected:
                raise ValueError("Original archive changed: " + key)
            self.containers[key] = expected
            self.archives[key] = self.stack.enter_context(zipfile.ZipFile(path))
        return self.archives[key]

    def member(self, archive, name, cache_key):
        parts = re.split(r"(?i)(?<=\.zip)!", name)
        if len(parts) > 4:
            raise ValueError("Archive nesting exceeds limit")
        for index, part in enumerate(parts):
            p = PurePosixPath(part)
            if p.is_absolute() or ".." in p.parts or "\\" in part:
                raise ValueError("Unsafe archive member")
            info = archive.getinfo(part)
            if info.file_size > 100 * 1024 ** 2:
                raise ValueError("Member exceeds inspection limit")
            if index == len(parts) - 1:
                return archive.read(info)
            cache_key += "!" + part
            if cache_key not in self.archives:
                self.archives[cache_key] = self.stack.enter_context(zipfile.ZipFile(io.BytesIO(archive.read(info))))
            archive = self.archives[cache_key]

    def source(self, source):
        if source["source_id"].startswith("purchased-"):
            path = (PURCHASED / source["path"]).resolve()
            if not path.is_relative_to(PURCHASED.resolve()):
                raise ValueError("Purchased path escapes root")
            data = path.read_bytes()
        else:
            if "archive" in source:
                rel = source["archive"]
                path, expected = local(rel), self.manifest["source_archives"][rel]
            else:
                path, expected = self.downloads[source["download_id"]]
            if path.suffix.lower() == ".zip":
                data = self.member(self.zip(path, expected), source["member"], str(path))
            else:
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != expected:
                    raise ValueError("Downloaded original changed: " + str(path))
        if hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise ValueError("Original occurrence changed: " + str(source))
        self.verified_sources += 1
        return header(data)


def result(category, code, reason, input_space="unspecified", output_space="unspecified", actions=None, evidence=None):
    return {"category": category, "reason_code": code, "reason": reason,
            "declared_input": input_space, "declared_output": output_space,
            "required_actions": actions or [], "evidence_ids": evidence or []}


def assess(source, head):
    sid = source["source_id"]
    member = source.get("member", source.get("path", ""))
    text = head.lower()
    # Explicit contradictory output claims take precedence over keyword matches.
    if "srgb" in text and "rec.1886" in text:
        return result("uncertain", "conflicting_output_declarations", "文件头同时称输出为 sRGB、Gamma 为 Rec.1886，输出定义冲突；已知输入为 D-Log。",
                      "DJI Phantom4 D-Log", "conflicting sRGB / Rec.1886", ["确认作者实际输出曲线，再规划输入及输出转换；不能直接套用照片。"])
    if re.search(r"color profile:.*adobe\s*rgb|color profile:.*adobergb", head, re.I):
        return result("conversion_required", "adobe_rgb_profile", "Export LUT 文件头声明 Adobe RGB (1998)，与项目 sRGB 编码域不同。",
                      "Adobe RGB (1998)", "Adobe RGB (1998); inferred from Export LUT same-profile workflow",
                      ["核实对应 ICC 配置，建立 sRGB → Adobe RGB (1998) → LUT → sRGB。"], ["export-lut-profile"])
    if re.search(r"color profile:.*rec.?709.*2[._]?4", head, re.I):
        return result("conversion_required", "rec709_gamma24_profile", "文件头声明 Rec.709 Gamma 2.4，不能当作 sRGB 传递函数。",
                      "Rec.709 Gamma 2.4", "Rec.709 Gamma 2.4; inferred from Export LUT same-profile workflow",
                      ["核实对应配置，建立 sRGB ↔ Rec.709 Gamma 2.4 的前后转换。"], ["export-lut-profile", "display-spaces"])
    if "input and output: rec.709 / bt.1886" in text:
        return result("conversion_required", "bt1886_declared", "文件头明确指定 Rec.709 / BT.1886 输入与输出。",
                      "Rec.709 / BT.1886", "Rec.709 / BT.1886", ["确定黑白电平和传递函数参数后，建立与 sRGB 的前后转换。"], ["display-spaces"])
    if sid == "xmosaique":
        return result("direct", "vendor_srgb_workflow", "随库来源说明明确声明整套 18 款支持 sRGB 输入并返回同一空间。", "sRGB supported", "sRGB supported", evidence=["xmosaique-srgb"])
    if "input and output:" in text and "srgb" in text:
        return result("direct", "header_srgb_io", "文件头明确声明 sRGB 输入、输出。", "sRGB supported", "sRGB supported")
    if sid == "on1-free" and "color & mood lut pack. input: rec.709 / srgb" in text:
        return result("direct", "header_srgb_creative", "Color & Mood 创意包明确声明支持 sRGB；按同一显示域输出理解，未做数值或效果验证。", "sRGB supported", "same display domain; inferred creative-LUT workflow")
    if sid == "iwltbap-free":
        base = PurePosixPath(member).name
        if re.search(r"(?:-STD| - Standard)\.cube$", base, re.I) or re.search(r"/(?:01 - Standard|STANDARD)/", member, re.I):
            return result("direct", "iwltbap_standard_srgb", "随包手册明确指定 Standard/STD 版本用于 sRGB 与 Rec.709 普通图像；按同域创意输出理解。", "sRGB supported", "same display domain; inferred creative-LUT workflow", evidence=["iwltbap-standard", "iwltbap-standard-older"])
        if re.search(r'TITLE "IWLTBAP Kodachrome.*sRGB', head, re.I):
            return result("direct", "iwltbap_kodachrome_srgb", "Kodachrome 创意 LUT 的 TITLE 明确列出支持 sRGB；按同域创意输出理解，K99 仍是作者标注的实验版本。", "sRGB supported", "same display domain; inferred creative-LUT workflow")
        if re.search(r"log|cine-?d|cinestyle|protune|flat|\bLTR\b|\bRTL\b|\bLTL\b", member, re.I):
            # Parse source path as a label only; a generic LOG label is not a full transform definition.
            return result("conversion_required", "specialized_profile", "路径／文件名标明 Log、相机曲线或空间转换用途，需要匹配指定编码；通用 LOG 标签不足以生成转换。",
                          member, "see filename/header; exact gamma/gamut may be unspecified",
                          ["优先选同款 Standard 版本；若保留此版本，先补齐输入色域、曲线及输出定义。", "技术转换 LUT 单独归档，不作为独立照片风格；不要对已渲染照片盲目反向恢复 Log。"], ["iwltbap-standard"])
    if sid == "lutify-free":
        match = re.search(r"-([A-Za-z0-9]+)-to-([A-Za-z0-9]+)\.cube$", member, re.I)
        if match:
            input_space, output_space = match.groups()
            if input_space == output_space == "Rec709":
                return result("uncertain", "rec709_gamma_unspecified", "Rec709-to-Rec709 版本没有声明传递函数，暂不认定与 sRGB 等同。", input_space, output_space, ["确认 Rec.709 的具体曲线及 sRGB 照片使用说明。"])
            return result("conversion_required", "lutify_specialized_io", "文件名／IDT、ODT 指定非 sRGB 工作空间，需要输入与输出适配。", input_space, output_space,
                          ["根据文件名及 IDT/ODT 注释确认完整曲线与色域，再定义 sRGB 前后转换；不能只靠 DWG/RWG 等简称实施。", "优先复核同款 Rec709-to-Rec709 版本；不同输入版本保留各自声明。"])
    if sid == "purchased-kodak" and "Log灰片" in member:
        return result("conversion_required", "purchased_log_version", "已购包 Log 灰片用途目录，不适配当前 sRGB 直套流程；目录说明标注 V-Log，旧版细节待核对。", source.get("input_profile", "Log-labelled"), "unspecified",
                      ["优先复核同款标准版；如需本版本，确认 V-Log 具体色域、曲线和输出空间。"], ["purchased-input-notes"])
    if sid == "phlearn-free":
        return result("uncertain", "photo_instructions_without_profile", "手册支持照片并提供 Photoshop 安装步骤，但未说明照片 ICC/编码域；视频步骤仅写 Rec.709。", "unspecified for photos", "unspecified for photos", ["确认照片输入、输出是否支持 sRGB。"], ["phlearn-guide"])
    if sid.startswith("purchased-"):
        return result("uncertain", "device_or_709_without_profile", "设备／软件用途或 709、标准版名称不能独立证明与 sRGB 兼容。", source.get("input_profile", "unspecified"), "unspecified", ["核实卖家的具体输入、输出曲线与色域；保留旧照片候选记录。"], ["purchased-input-notes"])
    if re.search(r"rec.?709|\b709\b", head + " " + member, re.I):
        return result("uncertain", "rec709_gamma_unspecified", "只声明 Rec.709/709，缺少确切传递函数或 sRGB 支持说明。", "Rec.709; gamma unspecified", "unspecified", ["补齐输入、输出定义，不能仅凭能导入或照片用途归为直接使用。"])
    return result("uncertain", "input_output_unspecified", "现有文件头和随包资料未给出足够的输入、输出色彩空间说明。", actions=["查明输入、输出色域与曲线；后续再按计划做效果测试。"])


def format_blockers(item):
    t, blockers = item["technical"], []
    if t["grid_size"] not in SUPPORTED_GRIDS:
        blockers.append(f"当前导入器不支持 {t['grid_size']}³ 网格；后续重采样至支持网格或扩展导入器。")
    if t["bytes"] > 10 * 1024 ** 2:
        blockers.append("文件超过当前导入器 10 MB 限制。")
    if t["domain_min"] != [0, 0, 0] or t["domain_max"] != [1, 1, 1]:
        blockers.append("输入域不是当前导入器要求的 0–1。")
    if not item["engine_format_supported"] and not blockers:
        blockers.append("既有结构检查标记当前导入器不支持；需要核实具体格式原因。")
    return blockers


def classify_cube(item, reader):
    assessments = []
    for source in item["sources"]:
        head = reader.source(source)
        assessment = assess(source, head)
        assessment.update({"origin": source, "original_header": head})
        assessments.append(assessment)
    categories = {a["category"] for a in assessments}
    # Unknown metadata on an exact duplicate does not negate an explicit sRGB
    # declaration. Conflicting positive declarations do require review.
    conflict = any(a["reason_code"] == "conflicting_output_declarations" for a in assessments)
    conflict |= "direct" in categories and "conversion_required" in categories
    category = ("uncertain" if conflict else "direct" if "direct" in categories else
                "conversion_required" if "conversion_required" in categories else "uncertain")
    blockers = format_blockers(item)
    if category == "direct" and blockers:
        category = "conversion_required"
    reasons = sorted({a["reason"] for a in assessments})
    if conflict:
        reasons.insert(0, "同一数值映射存在冲突的输入／输出声明；保留各来源，待核实。")
    elif category == "direct" and "uncertain" in categories:
        reasons.insert(0, "部分来源缺少说明；直接使用依据来自同一数值映射的其他来源明确声明。")
    role = "utility_or_technical" if any(re.search(r"/\d*\s*-?\s*utility/", a["origin"].get("member", ""), re.I) for a in assessments) else "creative_look_or_variant"
    return {"id": item["id"], "name": item["name"], "aliases": item["aliases"],
            "format": "cube", "path": item["path"], "original_sha256": item["original_sha256"],
            "mapping_sha256": item["technical"]["mapping_sha256"],
            "grid_size": item["technical"]["grid_size"], "category": category, "asset_role": role,
            "reasons": reasons, "format_blockers": blockers,
            "source_assessments": assessments, "conflicting_declarations": conflict,
            "multiple_declared_contexts": len({(a["declared_input"], a["declared_output"]) for a in assessments}) > 1,
            "required_actions": sorted({s for a in assessments for s in a["required_actions"]} | set(blockers)),
            "runtime_ids": item["runtime_ids"], "enabled": item["enabled"],
            "effect_test_status": item["effect_test_status"], "historical_preview_refs": item["historical_preview_refs"],
            "classification_basis": "static_metadata_only"}


def main():
    catalog_path = ROOT / "inventory/2026-10-30/catalog.json"
    catalog = read(catalog_path)
    evidence = read(ROOT / "photo-suitability-evidence.json")
    auxiliary_path = ROOT / "inventory/2026-10-30/auxiliary.json"
    baseline_paths = [catalog_path, auxiliary_path, ROOT / "catalog.json", ROOT.parent / "backend/app/luts.py", ROOT.parent / "backend/app/imaging.py"]
    baseline = {str(p.relative_to(ROOT.parent)): sha(p) for p in baseline_paths}
    for e in evidence["items"]:
        if "path" in e and sha(local(e["path"])) != e["sha256"]:
            raise ValueError("Reviewed evidence changed: " + e["id"])
    with ExitStack() as stack:
        reader = OriginalReader(stack)
        cubes = [classify_cube(i, reader) for i in catalog["items"]]
        verified_sources = reader.verified_sources
    halds = []
    for item in catalog["haldcluts"]:
        halds.append({"id": item["id"], "name": item["name"], "format": "haldclut", "path": item["path"],
                      "original_sha256": item["original_sha256"], "asset_role": item["asset_role"],
                      "category": "conversion_required", "declared_input": "sRGB", "declared_output": "sRGB",
                      "reason": "随包 README 声明默认 sRGB；当前项目仅接收 CUBE，需要 HaldCLUT 格式转换或引擎支持。",
                      "required_actions": ["保持 sRGB 数值定义并将 HaldCLUT 转为支持的 CUBE 网格，检查轴顺序与采样；本轮未转换。"],
                      "evidence_ids": ["rawtherapee-srgb"], "sources": item["sources"],
                      "enabled": item["enabled"], "effect_test_status": item["effect_test_status"], "classification_basis": "static_metadata_only"})
    counts = Counter(c["category"] for c in cubes)
    auxiliary = []
    for item in read(auxiliary_path)["items"]:
        auxiliary.append({"id": item["id"], "name": item["name"], "path": item["path"], "format": item["format"],
                          "original_sha256": item["sha256"], "category": "uncertain", "known_format_adaptation_required": True,
                          "reason": "当前照片管线不直接支持此格式；本轮保留为附属格式，未复核其内部色彩定义或可转换性，也未认定与同名 CUBE 等效。",
                          "required_actions": ["优先核对已有同款 CUBE；只有明确色彩定义及功能可表达为逐像素映射后，才规划转换或引擎适配。"],
                          "sources": item["sources"], "enabled": item["enabled"], "effect_test_status": item["effect_test_status"],
                          "classification_basis": "format_inventory_only"})
    registry = read(ROOT / "sources.json")["items"]
    per_source = []
    for source in registry:
        rows = [c for c in cubes if any(a["origin"]["source_id"] == source["id"] for a in c["source_assessments"])]
        if rows:
            per_source.append({"id": source["id"], "name": source["name"], "mapping_count": len(rows), **{k: sum(c["category"] == k for c in rows) for k in LABELS}})
    summary = {"cube_mappings": len(cubes), "cube_categories": dict(counts), "source_cube_occurrences": verified_sources,
               "hald_files": len(halds), "hald_looks": sum(h["asset_role"] != "identity_template" for h in halds),
               "hald_identity_templates": sum(h["asset_role"] == "identity_template" for h in halds),
               "cube_mappings_with_format_blockers": sum(bool(c["format_blockers"]) for c in cubes),
               "uncertain_with_known_format_blockers": sum(c["category"] == "uncertain" and bool(c["format_blockers"]) for c in cubes),
               "conflicting_declarations": sum(c["conflicting_declarations"] for c in cubes),
               "utility_cube_mappings": sum(c["asset_role"] == "utility_or_technical" for c in cubes),
               "auxiliary_files_pending_review": len(auxiliary), "auxiliary_format_counts": dict(Counter(a["format"] for a in auxiliary)),
               "runtime_mappings_unchanged": sum(c["enabled"] for c in cubes),
               "new_effect_tests": 0, "conversions_performed": 0, "new_lut_downloads": 0, "activation_changes": 0}
    assert len(cubes) == len({c["id"] for c in cubes}) == catalog["summary"]["unique_cube_mappings"]
    assert verified_sources == catalog["summary"]["source_cube_files"]
    assert sum(counts.values()) == len(cubes)
    assert len(halds) == len({h["id"] for h in halds}) == catalog["summary"]["hald_unique_files"]
    assert all(not c["format_blockers"] and any(a["category"] == "direct" for a in c["source_assessments"]) for c in cubes if c["category"] == "direct")
    assert baseline == {str(p.relative_to(ROOT.parent)): sha(p) for p in baseline_paths}
    output = {"schema_version": 1, "date": "2026-10-30", "scope": "static photo suitability; no effect testing", "path_base": "lut-library/",
              "classification_labels": LABELS, "summary": summary, "per_source": per_source, "input_baseline_sha256": baseline,
              "policy": {"photo_pipeline": "ICC-normalized encoded sRGB → raw LUT → interpreted as sRGB",
                         "direct_basis": "Explicit sRGB support and importer compatibility, including documented same-display-domain creative LUT workflows; not empirical effect validation.",
                         "conversion_required": "A non-sRGB profile or known format adaptation is required; exact conversion parameters may still need confirmation. No conversion performed.",
                         "merge_policy": "Assess every source occurrence; explicit sRGB evidence can qualify an exact duplicate with missing metadata, but conflicting positive declarations remain uncertain.",
                         "auxiliary_scope": "Separate format-only review; not independent visual looks and not added to CUBE mapping counts."},
              "evidence_index": "photo-suitability-evidence.json", "cube_items": cubes, "hald_items": halds, "auxiliary_items": auxiliary}
    write_json(OUT / "catalog.json", output)
    receipt = {k: output[k] for k in ["schema_version", "date", "scope", "summary", "per_source", "input_baseline_sha256", "evidence_index"]}
    receipt["catalog_path"] = str((OUT / "catalog.json").relative_to(ROOT))
    receipt["catalog_sha256"] = sha(OUT / "catalog.json")
    receipt["script_sha256"] = sha(Path(__file__))
    receipt["evidence_sha256"] = sha(ROOT / "photo-suitability-evidence.json")
    write_json(ROOT / "photo-suitability-receipt-2026-10-30.json", receipt)
    write_reports(output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def esc(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def asset_link(row):
    return f"[{esc(row['name'])}]({quote('../../../' + row['path'], safe='/')})"


def write_reports(output):
    for category, label in LABELS.items():
        rows = [i for i in output["cube_items"] if i["category"] == category]
        lines = [f"# {label} — {len(rows)} 种 CUBE 映射", "", "仅按文件头、随包资料、来源说明和当前导入器限制分类；未做效果测试。", "",
                 "文件名可能重复，映射 ID 用于区分标准版、Log 版等不同数值映射。详细来源、原始文件头和处理事项见 [机器索引](catalog.json)。", "",
                 "| 文件 | 映射 ID | 网格 | 来源 | 理由／格式限制 |", "|---|---|---:|---|---|"]
        for row in rows:
            sources = sorted({a["origin"]["source_id"] for a in row["source_assessments"]})
            lines.append(f"| {asset_link(row)} | {row['id']} | {row['grid_size']} | {', '.join(sources)} | {esc('；'.join(row['reasons'] + row['format_blockers']))} |")
        (OUT / (category + ".md")).write_text("\n".join(lines) + "\n", encoding="utf-8")
    lines = ["# HaldCLUT — 需要格式转换", "", "默认 sRGB。292 个风格文件与 1 个 Identity 模板单列，不与 CUBE 做跨格式等效合并。当前项目不直接接收 HaldCLUT。", "", "| 文件 | 用途 |", "|---|---|"]
    for row in output["hald_items"]:
        lines.append(f"| {asset_link(row)} | {'Identity 基准模板，不是风格' if row['asset_role'] == 'identity_template' else '风格，待转换及后续验证'} |")
    (OUT / "hald.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    lines = ["# 附属格式 — 需补资料与格式适配", "", "这些文件不计入 CUBE 映射数。本轮没有跨格式等效判断或内部色彩定义复核；当前引擎不直接接收，优先找已有同款 CUBE。", "", "| 文件 | 格式 |", "|---|---|"]
    for row in output["auxiliary_items"]:
        lines.append(f"| {asset_link(row)} | {row['format'].upper()} |")
    (OUT / "auxiliary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
