"""User-facing receipts built from persisted operations, never model claims."""
from collections import defaultdict

FIELDS = {"exposure_ev": "曝光", "warmth": "冷暖", "contrast": "对比度", "saturation": "饱和度"}
PRESETS = {"natural": "自然本色", "warm": "暖调时光", "mono": "经典黑白"}


def scope(ordinals):
    return "第 " + "、".join(str(n) for n in ordinals) + " 张"


def value(field, number):
    return f"{number:+.2f} EV" if field == "exposure_ev" else f"{number:.2f}"


def lut_label(recipe):
    lut = recipe.get("lut")
    return f"{lut['name']} · LUT 强度 {lut['strength'] * 100:g}%" if lut else "不使用 LUT"


def plan_summary(items, preview_asset_id, before=None, search=None, request=None, personal_name=None):
    """Freeze selection evidence and actual per-image changes when making a plan.

    For legacy operations without before-values, report final values only.
    """
    groups = defaultdict(list)
    for item in items:
        groups[lut_label(item["recipe"])].append(item["ordinal"])
    if personal_name:
        title = f"个人预设「{personal_name}」"
    elif request and request.preset_id:
        title = f"内置预设「{PRESETS[request.preset_id]}」"
    elif len(groups) == 1:
        title = next(iter(groups))
        if title == "不使用 LUT":
            title = "基础调色 · 不使用 LUT"
    else:
        title = "按照片分别设置 LUT 与强度"
    sample = next((i["ordinal"] for i in items if i["asset_id"] == preview_asset_id), None)
    lines = [f"方案：{title}",
             f"处理范围：{scope(i['ordinal'] for i in items)}；预览样张：{scope([sample])}。"]
    if len(groups) > 1 or personal_name or (request and request.preset_id):
        lines.extend(f"{scope(nums)}：{label}。" for label, nums in groups.items())
    if search:
        selected = {i["recipe"]["lut"]["id"] for i in items if i["recipe"].get("lut")}
        matched = [c for c in search.get("candidates", []) if c["id"] in selected]
        if matched:
            mode = "语义与关键词检索" if search["mode"] == "hybrid" else "关键词与同义词检索"
            lines.append(f"检索需求：「{search['query']}」；使用{mode}。")
            if search.get("message"):
                lines.append(search["message"])
            for candidate in matched:
                reasons = "；".join(candidate.get("reasons", [])) or "从本轮候选中选择"
                lines.append(f"{candidate['name']} 的匹配依据：{reasons}。")
                if candidate.get("description"):
                    lines.append("效果资料：" + candidate["description"])
                if candidate.get("strength_basis"):
                    lines.append("强度参考：" + candidate["strength_basis"])
                else:
                    lines.append("当前强度用于试用，尚无已验证的最佳强度记录。")
                if candidate.get("conflicts"):
                    lines.append("需要留意：" + "；".join(candidate["conflicts"]))
    changes = defaultdict(list)
    for item in items:
        recipe = item["recipe"]
        prior = before.get(item["asset_id"]) if before is not None else None
        if prior is None:
            text = "最终基础参数：" + "，".join(f"{label} {value(field, recipe[field])}" for field, label in FIELDS.items())
        else:
            edits = [f"{label} {value(field, prior[field])} → {value(field, recipe[field])}"
                     for field, label in FIELDS.items() if prior[field] != recipe[field]]
            text = "基础调整：" + "，".join(edits) if edits else "基础参数保持不变"
        changes[text].append(item["ordinal"])
    lines.extend(f"{scope(nums)}：{text}。" for text, nums in changes.items())
    return "\n".join(lines)


def status_message(op):
    sample = next((i["ordinal"] for i in op["items"] if i["asset_id"] == op["preview_asset_id"]), None)
    target = scope(i["ordinal"] for i in op["items"])
    state = op["status"]
    if state == "previewing":
        return f"正在为{scope([sample])}生成预览，尚未应用。"
    if state == "ready":
        return f"{scope([sample])}的预览已生成，尚未应用。请查看前后对比，满意后点击「确认应用」。"
    if state in ("queued", "running"):
        return f"预览已确认，正在将方案应用到{target}。"
    if state in ("succeeded", "partial_failed"):
        done = sum(i["status"] == "succeeded" for i in op["items"])
        return f"应用已完成：{done} 张成功，{len(op['items']) - done} 张失败。" + ("可在导出照片中下载结果。" if done else "")
    if state == "failed":
        stage = "应用" if op["preview_url"] else "预览生成"
        return f"{stage}失败：{op['error'] or '请重试。'}" + ("" if op["preview_url"] else "已有照片效果未改变。")
    return {
        "stale": "此预览已失效，请根据当前照片状态重新生成。",
        "superseded": "此方案已被后续预览替代，未应用此方案。",
        "discarded": "此预览已放弃，未应用此方案。",
        "interrupted": "任务已中断，请查看已有结果并重试未完成项。",
    }.get(state, "请在图片区查看本次任务状态。")
