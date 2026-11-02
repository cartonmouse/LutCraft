"""Repeatable sRGB sample analysis. Measurements are not scene/brand claims."""
import colorsys
import numpy as np

VERSION = "srgb-samples-v1"


def analyze(cpu):
    gray = np.repeat(np.linspace(0, 1, 33, dtype=np.float32)[:, None], 3, axis=1)
    colors = np.array([colorsys.hsv_to_rgb(h / 24, s, v)
                       for h in range(24) for s in (.25, .6, 1) for v in (.25, .5, .9)], dtype=np.float32)
    samples = np.concatenate([gray, colors])
    result = samples.copy()
    cpu.applyRGB(result)
    if not np.isfinite(result).all():
        raise ValueError("non-finite LUT output")
    clipped = np.clip(result, 0, 1)
    mean_delta = float(np.mean(clipped[:33] - gray))
    chroma_before = np.ptp(colors, axis=1).mean()
    chroma_ratio = float(np.ptp(clipped[33:], axis=1).mean() / chroma_before)
    biases = {key: (result[index] - result[index].mean()).round(5).tolist()
              for key, index in [("shadows", 4), ("midtones", 16), ("highlights", 28)]}
    tags = []
    if np.max(np.ptp(clipped, axis=1)) < .025:
        tags.append("黑白")
    elif chroma_ratio < .85:
        tags.append("低饱和")
    elif chroma_ratio > 1.15:
        tags.append("鲜艳")
    if mean_delta > .04:
        tags.append("明亮")
    if float(clipped[1].mean()) > .06:
        tags.append("褪色")
    contrast = float(clipped[24].mean() - clipped[8].mean())
    if contrast < .42:
        tags.append("低对比")
    elif contrast > .58:
        tags.append("高对比")
    mid = biases["midtones"]
    if mid[0] - mid[2] > .04:
        tags.append("暖色")
    elif mid[2] - mid[0] > .04:
        tags.append("冷色")
    if (mid[0] + mid[1]) / 2 - mid[2] > .04:
        tags.append("偏黄")
    summary = "在 sRGB 标准灰阶与色块、100% 强度下测得：" + ("、".join(tags) if tags else "整体变化较轻或依赖具体颜色") + "。场景适用性仍需照片预览验证。"
    return {
        "version": VERSION, "input_space": "srgb", "strength": 1,
        "sample_count": len(samples), "gray_mean_delta": round(mean_delta, 5),
        "chroma_ratio": round(chroma_ratio, 5), "gray_contrast": round(contrast, 5),
        "biases": biases, "out_of_range_fraction": round(float(((result < 0) | (result > 1)).any(axis=1).mean()), 5),
        "output_range": [float(result.min()), float(result.max())],
        "tags": tags, "description": summary,
    }
