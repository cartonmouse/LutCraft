"""Build a metadata-only conversion plan for the reviewed 372 CUBE mappings.

No LUT sampling, baking, color transforms, image loading, networking or activation.
The original classification and active runtime catalog remain immutable inputs.
"""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import struct
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "inventory/2026-10-30/conversion-plan"
LABELS = {
    "defined_route": "转换链定义明确，优先实施",
    "conditional": "条件式方案，先补参数或工作流依据",
    "prefer_standard": "优先同款标准版，避免转换相机版",
    "insufficient": "资料不足，暂不制定可执行转换",
    "utility_archive": "技术工具保留，不制作独立照片风格",
}
ROUTES = {
    "adobe_rgb": {"decision": "defined_route", "priority": "P1", "chain": "sRGB 解码 → D65 线性 sRGB 至 Adobe RGB 矩阵 → Adobe RGB 编码 → 原 LUT → Adobe RGB 解码 → 线性 Adobe RGB 至 sRGB 矩阵 → 扩展 sRGB 编码",
                  "basis": "文件头指定 AdobeRGB1998.icc；Export LUT 作者说明该配置对应应用图像的空间。按该工具同配置工作流推断输出亦为 Adobe RGB。",
                  "preconditions": ["固定 Adobe RGB (1998) 与 sRGB 标准参数及实现版本；以相对编码值为基准，不叠加观察环境补偿。", "保持输出范围扩展至项目混合后再裁切；若另选 ICC CMM 路线，固定配置哈希、意图、黑点补偿与裁切位置并另建版本。", "未来验证数值误差、色域越界及源 LUT 插值；尚未做转换或效果验收。"],
                  "evidence": ["export-lut", "adobe-rgb", "srgb", "local-profiles", "project-pipeline"]},
    "gamma24": {"decision": "defined_route", "priority": "P1", "chain": "sRGB 解码 → 纯 Gamma 2.4 编码 → 原 LUT → Gamma 2.4 解码 → sRGB 编码",
                "basis": "文件头指向 Export LUT 自带 Rec709gamma2.4.icc，曲线比泛称 Rec.709 明确；同配置输出是根据工具工作流的推断。",
                "preconditions": ["锁定 Rec.709 原色、D65、归一化全范围和纯 2.4 曲线；实施前核对原插件 ICC 或采用有版本记录的明确标准实现。", "本机 ITU-709.icc 的 TRC 不是纯 Gamma 2.4，不可直接代替。", "未来验证暗部采样与数值精度；未验证作者原始 Lightroom 效果。"],
                "evidence": ["export-lut", "srgb", "local-profiles", "project-pipeline"]},
    "bt1886": {"decision": "conditional", "priority": "P2", "chain": "sRGB 相对线性值 → 已确认参数的 BT.1886 逆 EOTF → 原 LUT → 同参数 BT.1886 EOTF → sRGB 编码",
               "basis": "文件头明确输入输出为 Rec.709 / BT.1886，但未说明黑电平、白电平、归一化方式和满／窄范围约定。",
               "preconditions": ["确认或明确记录 LB、LW、范围及归一化定义；不可静默把 BT.1886 当作 sRGB。", "若采用 LB=0、归一化 LW=1，才退化为纯 Gamma 2.4；这是待确认的工程假设，不是已知作者参数。", "不要仅凭视频码值惯例把 CUBE 0–1 直接缩放到 16–235 或 64–940。"],
               "evidence": ["bt1886", "srgb"]},
    "working_space": {"decision": "conditional", "priority": "P2", "chain": "优先在匹配作者版本的色彩管理流程中，以已确认的 sRGB 输入变换 → 原工作空间 Look → sRGB 输出变换导出；数学编码变换仅作为另有标记的适配方案",
                      "basis": "Lutify 文件名标注 ACEScct、DWG 或 RWG 输入输出；仅有空间简称不等于完整照片渲染工作流。",
                      "preconditions": ["ACEScct 已有 AP1/ACES 白点与曲线标准；DWG/RWG 仍要确认各自搭配 DaVinci Intermediate/Log3G10，不能只按色域简称推断。", "锁定 fylm.ai/ACES 版本、输入变换、输出显示变换和 gamut compress 选项；文件头节点列表不能完整替代作者工程。", "sRGB 已是显示参考图像，简单解码成线性后转 Log 不能还原场景曝光；不得直接叠加未匹配的 ACES 显示渲染。"],
                      "evidence": ["fylm-export", "fylm-aces", "acescct", "davinci-wg", "red-rwg"]},
    "iw_standard": {"decision": "prefer_standard", "priority": "reuse", "chain": "使用已经接入的同款 Standard/STD/K 系列版本；不新增衍生 CUBE",
                    "basis": "同款普通图像版本已在当前 50 种库中；Log 版本只是该风格的另一输入路线。",
                    "preconditions": ["对应关系依据官方命名和原包来源，不声称已做视觉等效验证。", "同名有多个网格／修订版时保留全部候选，优先核对同原包来源；不以文件名猜定唯一版本。"],
                    "evidence": ["iwltbap-standard-local", "runtime-catalog"]},
    "lutify_standard": {"decision": "prefer_standard", "priority": "P2-family", "chain": "优先核实同风格 Rec709-to-Rec709，或由作者原始 Look 重新导出 sRGB-to-sRGB；不逐一包装相机 IDT 版本",
                        "basis": "125 种相机／扫描输入映射归属于 5 个风格；每个风格已有 Rec709-to-Rec709 对应文件，但尚未接入运行库。",
                        "preconditions": ["官方 fylm.ai 文档提供 sRGB 输入、输出导出路线，且其 Rec709 显示目标说明为 BT.1886/100 cd/m²；仍需确认本包版本及两端实际变换。", "对应的 5 种 Rec709 文件不在本次 372 种中，不能重复算入或自动启用。", "不要把相机版中已经烘焙的 IDT、色彩匹配、Look、ODT 视为可单独无损拆出的节点；VLog/KineLog3 同数值异标签保留复核。"],
                        "evidence": ["fylm-export", "fylm-aces", "source-headers"]},
    "purchased_log": {"decision": "insufficient", "priority": "hold", "chain": "保留原件；取得完整输入／输出说明后重新制定方案，优先复核同款标准版",
                      "basis": "柯达 5219 包只提供 Log/V-Log 用途线索，没有充分的输出空间、范围、版本或场景到显示映射说明。",
                      "preconditions": ["向作者取得具体输入色域/曲线（含版本）、输出曲线、满/窄范围以及是否包含技术变换。", "8 个新版可定位同编号标准版，但标准版本身也待确认；6 个旧版没有足够依据作一一等效映射。"],
                      "evidence": ["purchased-input-notes-local"]},
    "utility": {"decision": "utility_archive", "priority": "archive", "chain": "保留为技术转换／基础处理工具，不将其包装成独立照片风格",
                "basis": "来源目录为 Utility，包含 Log→显示、显示→Log、Log→Log、Generic 曲线等工具。当前照片已经在 sRGB 流程中。",
                "preconditions": ["只有将来具体转换链需要且输入输出定义完整时才引用；技术 LUT 不提供新的创意风格承诺。", "不反求整张 LUT 来恢复已渲染照片的场景动态范围，不自动抵消或重复应用技术曲线。"],
                "evidence": ["iwltbap-standard-local", "source-headers"]},
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def family(name):
    return re.sub(r"(?: - |-|_)(?:STANDARD|STD|LOG|VLOG|V-LOG|S-LOG2|S-LOG3|C-LOG)$", "", Path(name).stem.upper())


def lutify_family(name):
    match = re.search(r"Lutify\.me-([^-]+)-", name)
    return match.group(1) if match else None


def inspect_profile(path):
    """Read ICC tags, not sample colors or construct a color transform."""
    data = path.read_bytes()
    count = struct.unpack_from(">I", data, 128)[0]
    tags = {}
    for i in range(count):
        sig, offset, size = struct.unpack_from(">4sII", data, 132 + i * 12)
        sig = sig.decode("ascii")
        if sig not in {"rTRC", "gTRC", "bTRC", "wtpt", "rXYZ", "gXYZ", "bXYZ"}:
            continue
        value = data[offset:offset + size]
        tag = {"type": value[:4].decode("ascii"), "bytes": size}
        if tag["type"] == "curv":
            tag["count"] = struct.unpack_from(">I", value, 8)[0]
            if tag["count"] == 1:
                tag["gamma"] = struct.unpack_from(">H", value, 12)[0] / 256
        elif tag["type"] == "para":
            tag["function"] = struct.unpack_from(">H", value, 8)[0]
            tag["parameters"] = [struct.unpack_from(">i", value, n)[0] / 65536 for n in range(12, len(value) - 3, 4)]
        elif tag["type"] == "XYZ ":
            tag["xyz"] = [struct.unpack_from(">i", value, n)[0] / 65536 for n in (8, 12, 16)]
        tags[sig] = tag
    return {"path": str(path), "sha256": sha(path), "tags": tags, "used_for_conversion": False}


def main():
    frozen_path = ROOT / "inventory/2026-10-30/photo-suitability/catalog.json"
    snapshot = read(frozen_path)
    assert sha(frozen_path) == read(ROOT / "photo-suitability-receipt-2026-10-30.json")["catalog_sha256"]
    inventory = {x["id"]: x for x in read(ROOT / "inventory/2026-10-30/catalog.json")["items"]}
    active = read(ROOT / "catalog.json")["items"]
    assert len(active) == 50
    active_map = {x["technical"]["mapping_sha256"]: x for x in active}
    protected = [frozen_path, ROOT / "catalog.json", ROOT / "photo-activation-receipt-2026-10-30.json", ROOT / "inventory/2026-10-30/catalog.json", ROOT / "inventory/2026-10-30/auxiliary.json", ROOT.parent / "backend/app/imaging.py", ROOT.parent / "backend/app/luts.py"]
    before = {str(p.relative_to(ROOT.parent)): sha(p) for p in protected}
    references = read(ROOT / "conversion-plan-evidence.json")
    for evidence in references["items"]:
        if "path" in evidence and sha(ROOT / evidence["path"]) != evidence["sha256"]:
            raise ValueError("Reviewed evidence changed: " + evidence["id"])
    iw_standards, lutify_standards = defaultdict(list), defaultdict(list)
    for row in snapshot["cube_items"]:
        for assessment in row["source_assessments"]:
            source = assessment["origin"]
            if source["source_id"] == "iwltbap-free" and assessment["category"] == "direct":
                iw_standards[family(source["member"])].append(row)
            if source["source_id"] == "lutify-free" and assessment["declared_input"] == assessment["declared_output"] == "Rec709":
                lutify_standards[lutify_family(source["member"])].append(row)
    rows, file_hashes = [], {}
    for item in snapshot["cube_items"]:
        if item["category"] != "conversion_required":
            continue
        hashes = {a["origin"]["source_id"] for a in item["source_assessments"]}
        assert len(hashes) == 1
        sid = next(iter(hashes))
        reason_codes = {a["reason_code"] for a in item["source_assessments"]}
        related = []
        style_family = None
        if "adobe_rgb_profile" in reason_codes:
            route = "adobe_rgb"
        elif "rec709_gamma24_profile" in reason_codes:
            route = "gamma24"
        elif "bt1886_declared" in reason_codes:
            route = "bt1886"
        elif sid == "lutify-free":
            style_family = lutify_family(item["source_assessments"][0]["origin"]["member"])
            related = lutify_standards[style_family]
            spaces = {(a["declared_input"], a["declared_output"]) for a in item["source_assessments"]}
            route = "working_space" if all(i == o and i in {"ACEScct", "DWG", "RWG"} for i, o in spaces) else "lutify_standard"
        elif sid == "iwltbap-free":
            route = "utility" if item["asset_role"] == "utility_or_technical" else "iw_standard"
            if route == "iw_standard":
                families = {family(a["origin"]["member"]) for a in item["source_assessments"]}
                related = [candidate for key in families for candidate in iw_standards[key]]
                assert related, item["name"]
        elif sid == "purchased-kodak":
            route = "purchased_log"
            source_path = item["source_assessments"][0]["origin"]["path"]
            match = re.search(r"/XH-5219-([1-8])\.cube$", source_path)
            if match:
                target_name = "XH_5219_" + match.group(1) + ".cube"
                related = [r for r in snapshot["cube_items"] if any(a["origin"].get("path", "").endswith("/" + target_name) for a in r["source_assessments"])]
        else:
            raise ValueError("Unreviewed source: " + sid)
        plan = ROUTES[route]
        related = list({r["id"]: r for r in related}.values())
        candidates = []
        for candidate in related:
            runtime = active_map.get(candidate["mapping_sha256"])
            source_members = {a["origin"].get("download_id", a["origin"].get("archive")) for a in item["source_assessments"]}
            same_archives = {a["origin"].get("download_id", a["origin"].get("archive")) for a in candidate["source_assessments"]} & source_members
            candidates.append({"mapping_id": candidate["id"], "name": candidate["name"], "path": candidate["path"],
                               "grid_size": candidate["grid_size"], "runtime_path": runtime["path"] if runtime else None,
                               "classification": candidate["category"], "runtime_id": runtime["id"] if runtime else None,
                               "same_original_archives": sorted(x for x in same_archives if x), "match_basis": "publisher family/name; visual equivalence not tested"})
        tech = inventory[item["id"]]["technical"]
        digest = sha(ROOT / item["path"])
        assert digest == item["original_sha256"]
        file_hashes[item["path"]] = digest
        observations = []
        if tech["output_value_range"][0] < 0 or tech["output_value_range"][1] > 1:
            observations.append("原 LUT 数据存在 0–1 以外输出；不得在解码/变换前默默截断，须先明确负值和超白语义。")
        if item["format_blockers"]:
            observations.extend(item["format_blockers"])
        if sid == "lutify-free" and len({a["declared_input"] for a in item["source_assessments"]}) > 1:
            observations.append("同映射有不同输入标签，不能将数值重复视为输入空间等同。")
        rows.append({"mapping_id": item["id"], "name": item["name"], "source_id": sid, "path": item["path"],
                     "source_sha256": digest, "mapping_sha256": item["mapping_sha256"], "grid_size": item["grid_size"],
                     "decision": plan["decision"], "route_id": route, "priority": plan["priority"], "style_family": style_family,
                     "basis": plan["basis"], "proposed_chain": plan["chain"], "implementation_gates": plan["preconditions"],
                     "evidence_ids": plan["evidence"], "observations": observations, "output_value_range": tech["output_value_range"],
                     "related_standard_candidates": candidates,
                     "source_contexts": [{"origin": a["origin"], "declared_input": a["declared_input"], "declared_output": a["declared_output"],
                                          "relevant_headers": [s for s in a["original_header"].splitlines() if re.search(r"IDT|ODT|Color profile|Input|Output|Gamut compress|TITLE", s, re.I)]} for a in item["source_assessments"]],
                     "execute_now": False, "plan_only": True, "converted": False, "activated": False, "new_effect_tests": 0})
    assert len(rows) == len({r["mapping_id"] for r in rows}) == 372
    assert not {r["mapping_sha256"] for r in rows} & set(active_map)
    for r in rows:
        assert set(r["evidence_ids"]).issubset({e["id"] for e in references["items"]})
    profile_root = Path("/System/Library/ColorSync/Profiles")
    profiles = [inspect_profile(profile_root / name) for name in ("AdobeRGB1998.icc", "sRGB Profile.icc", "ITU-709.icc") if (profile_root / name).exists()]
    summary = {"reviewed_cube_mappings": len(rows), "decisions": dict(Counter(r["decision"] for r in rows)),
               "routes": dict(Counter(r["route_id"] for r in rows)), "active_runtime_count_unchanged": len(active),
               "source_occurrences_preserved": sum(len(r["source_contexts"]) for r in rows),
               "source_asset_hashes_verified": len(file_hashes), "existing_out_of_range_mappings": sum(bool(r["output_value_range"][0] < 0 or r["output_value_range"][1] > 1) for r in rows),
               "new_lut_downloads": 0, "new_converted_luts": 0, "lut_evaluations": 0, "new_effect_tests": 0, "activation_changes": 0}
    assert before == {str(p.relative_to(ROOT.parent)): sha(p) for p in protected}
    data = {"date": "2026-10-30", "scope": "conversion planning only; no baking, rendering or runtime changes", "path_base": "lut-library/",
            "labels": LABELS, "summary": summary, "routes": ROUTES, "input_sha256": before, "local_profile_inspection": profiles,
            "proposed_target": {"encoding": "sRGB encoded → sRGB encoded", "domain": [0, 1], "format": "3D .cube only", "initial_grid": 65,
                                "max_bytes": 10485760, "source_interpolation": "tetrahedral, matching current engine",
                                "output_range_policy": "Keep extended output until existing encoded-sRGB strength blend, then clamp, unless an explicitly versioned alternative gamut policy is selected.",
                                "validation_status": "not_started; all numeric sampling and visual testing deferred"}, "items": rows}
    write(OUT / "catalog.json", data)
    write(OUT / "source-hashes.json", file_hashes)
    for category, label in LABELS.items():
        group = [r for r in rows if r["decision"] == category]
        lines = [f"# {label} — {len(group)} 种映射", "", "仅方案，不代表已转换或通过效果验证。完整参数、所有来源与标准版候选见 [机器索引](catalog.json)。", "", "| 名称 | 来源 | 网格 | 方案 | 标准版候选 |", "|---|---|---:|---|---|"]
        for r in group:
            link = quote("../../../" + r["path"], safe="/")
            targets = "；".join(f"[{c['name']} · {c['grid_size']}³]({quote('../../../' + (c['runtime_path'] or c['path']), safe='/')})" + ("（已接入）" if c["runtime_id"] else "（待确认）") for c in r["related_standard_candidates"])
            lines.append(f"| [{r['name']}]({link}) `{r['mapping_id']}` | {r['source_id']} | {r['grid_size']} | {r['route_id']}：{r['basis']} {'；'.join(r['observations'])} | {targets or '—'} |")
        (OUT / (category + ".md")).write_text("\n".join(lines) + "\n", encoding="utf-8")
    write(ROOT / "conversion-plan-receipt-2026-10-30.json", {"date": data["date"], "scope": data["scope"], "summary": summary,
          "catalog_path": str((OUT / "catalog.json").relative_to(ROOT)), "catalog_sha256": sha(OUT / "catalog.json"),
          "source_hash_manifest_sha256": sha(OUT / "source-hashes.json"), "input_sha256": before, "script_sha256": sha(Path(__file__)),
          "evidence_path": "conversion-plan-evidence.json", "evidence_sha256": sha(ROOT / "conversion-plan-evidence.json")})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
