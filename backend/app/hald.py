"""Bundled sRGB HaldCLUTs, preserving every original PNG sample.

Raster order is red-fastest, green, blue. Trilinear lookup follows the
RawTherapee Hald convention, not its complete RAW processing pipeline.
This loader is for explicit catalog entries, never arbitrary photo uploads.
"""
from functools import lru_cache
import hashlib
import struct

import numpy as np
import pyvips

from .errors import AppError

VERSION = "hald-trilinear-v1"
MAX_BYTES = 64 * 1024 * 1024


def decode(data):
    try:
        if not 0 < len(data) <= MAX_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("需要不超过 64 MiB 的 Hald PNG")
        im = pyvips.Image.new_from_buffer(data, "", access="sequential", fail_on="warning")
        level = next((n for n in range(2, 17) if n ** 3 == im.width), None)
        if im.width != im.height or level is None:
            raise ValueError("Hald 边长必须为 2–16 级的立方")
        if im.bands not in (1, 3) or im.format not in ("uchar", "ushort"):
            raise ValueError("需要无 Alpha 的 8/16 位灰度或 RGB 采样表")
        # These are LUT numbers: no ICC/gamma conversion, autorotation, resize,
        # or 16-to-8-bit conversion, even when image metadata is present.
        depth = 8 if im.format == "uchar" else 16
        values = np.frombuffer(im.write_to_memory(), dtype=np.uint8 if depth == 8 else np.uint16)
        values = values.reshape(-1, im.bands)
        values.flags.writeable = False
        return values, level ** 2, depth
    except (ValueError, pyvips.Error) as exc:
        raise AppError("hald_format", f"HaldCLUT 无效：{exc}。") from exc


def inspect_hald(data):
    values, size, depth = decode(data)
    digest = hashlib.sha256(b"HaldCLUT/trilinear/sRGB/v1\0" + struct.pack(">I", size))
    for start in range(0, len(values), 65536):
        block = values[start:start + 65536].astype(np.float32) / ((1 << depth) - 1)
        if values.shape[1] == 1:
            block = np.repeat(block, 3, axis=1)
        digest.update(block.astype(">f4").tobytes())
    return {"title": "", "lut_type": "HaldCLUT", "grid_size": size, "data_rows": size ** 3,
            "bit_depth": depth, "channels": values.shape[1], "interpolation": "trilinear",
            "domain_min": [0.0] * 3, "domain_max": [1.0] * 3,
            "output_value_range": [float(values.min()) / ((1 << depth) - 1), float(values.max()) / ((1 << depth) - 1)],
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "mapping_sha256": digest.hexdigest()}


class HaldProcessor:
    def __init__(self, data):
        self.values, self.size, self.depth = decode(data)

    def applyRGB(self, pixels):
        if not isinstance(pixels, np.ndarray) or pixels.dtype != np.float32 or pixels.ndim < 2 or pixels.shape[-1] != 3 or not pixels.flags.c_contiguous or not pixels.flags.writeable:
            raise AppError("hald_pixels", "Hald 输入需要连续、可写的 float32 RGB 数组。")
        flat = pixels.reshape(-1, 3)
        if not np.isfinite(flat).all():
            raise AppError("hald_pixels", "Hald 输入包含非有限数值。")
        n = self.size
        for start in range(0, len(flat), 65536):
            target = flat[start:start + 65536]
            position = np.clip(target, 0, 1) * np.float32(n - 1)
            lo = np.minimum(position.astype(np.int32), n - 2)
            delta = position - lo.astype(np.float32)
            index = lo[:, 0] + n * lo[:, 1] + n * n * lo[:, 2]
            r, g, b = (delta[:, c:c + 1] for c in range(3))

            def red(offset):
                a = self.values[index + offset].astype(np.float32)
                z = self.values[index + offset + 1].astype(np.float32)
                return a + r * (z - a)

            low = red(0)
            low += g * (red(n) - low)
            high = red(n * n)
            high += g * (red(n * n + n) - high)
            low += b * (high - low)
            target[:] = low / np.float32((1 << self.depth) - 1)


@lru_cache(maxsize=2)
def processor(path, digest, version=VERSION):
    from pathlib import Path
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise AppError("lut_changed", "LUT 文件校验失败，已停止调色。")
    return HaldProcessor(data)
