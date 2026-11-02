"""Numerical Hald fixtures, not generated photo previews."""
import hashlib

import numpy as np
import pyvips
import pytest

from app.hald import HaldProcessor, inspect_hald
from app.errors import AppError
from app import single_pass


def png(values, level, depth=16):
    side = level ** 3
    values = np.ascontiguousarray(values, dtype=np.uint16 if depth == 16 else np.uint8)
    bands = values.size // (side * side)
    im = pyvips.Image.new_from_memory(values.data, side, side, bands, "ushort" if depth == 16 else "uchar")
    im = im.copy(interpretation="rgb16" if depth == 16 else "srgb")
    return im.pngsave_buffer(bitdepth=depth)


@pytest.mark.parametrize("depth", [8, 16])
def test_identity_axes_precision_and_clamping(depth):
    n = 4
    b, g, r = np.meshgrid(*(np.arange(n) for _ in range(3)), indexing="ij")
    rgb = np.stack((r, g, b), -1).reshape(-1, 3)
    data = png(rgb * (((1 << depth) - 1) // (n - 1)), 2, depth)
    info = inspect_hald(data)
    assert info["bit_depth"] == depth and info["grid_size"] == 4
    x = np.random.default_rng(123).uniform(-.5, 1.5, (70000, 3)).astype(np.float32)
    actual = x.copy()
    HaldProcessor(data).applyRGB(actual)
    np.testing.assert_allclose(actual, np.clip(x, 0, 1), atol=2e-7, rtol=0)


def test_nonsymmetric_channel_mapping_and_grayscale():
    b, g, r = np.meshgrid(*(np.arange(4) / 3 for _ in range(3)), indexing="ij")
    # Multilinear polynomial is reproduced by trilinear interpolation. It also
    # distinguishes trilinear from tetrahedral and catches reversed RGB axes.
    values = np.stack((r * g, .2 + .6 * b, .1 + .5 * g * b), -1).reshape(-1, 3)
    data = png(np.rint(values * 65535), 2)
    x = np.random.default_rng(4).random((3000, 3)).astype(np.float32)
    expected = np.stack((x[:, 0] * x[:, 1], .2 + .6 * x[:, 2], .1 + .5 * x[:, 1] * x[:, 2]), -1)
    actual = x.copy()
    HaldProcessor(data).applyRGB(actual)
    np.testing.assert_allclose(actual, expected, atol=1 / 65535, rtol=0)
    gray = png(np.rint(r.reshape(-1, 1) * 255), 2, 8)
    HaldProcessor(gray).applyRGB(x)
    np.testing.assert_array_equal(x[:, 0], x[:, 1])
    np.testing.assert_array_equal(x[:, 0], x[:, 2])


def test_loader_requires_explicit_hald_format_and_matching_hash(tmp_path, monkeypatch):
    data = png(np.arange(192, dtype=np.uint16).reshape(-1, 3), 2)
    p = tmp_path / "lut-library/luts/fixture.png"
    p.parent.mkdir(parents=True)
    p.write_bytes(data)
    monkeypatch.setattr(single_pass, "ROOT", tmp_path)
    row = {"path": "luts/fixture.png", "sha256": hashlib.sha256(data).hexdigest(), "format": "HaldCLUT"}
    assert isinstance(single_pass.load_catalog_processor(row), HaldProcessor)
    with pytest.raises(AppError, match="不受支持"):
        single_pass.load_catalog_processor({**row, "format": "photo"})
    with pytest.raises(AppError, match="校验失败"):
        single_pass.load_catalog_processor({**row, "sha256": "0" * 64})


def test_rejects_invalid_tables_and_pixels():
    for data in (b"not png", pyvips.Image.black(10, 10, bands=3).pngsave_buffer(),
                 pyvips.Image.black(8, 8, bands=4).pngsave_buffer()):
        with pytest.raises(AppError, match="HaldCLUT 无效"):
            inspect_hald(data)
    cpu = HaldProcessor(png(np.zeros((64, 3)), 2))
    for x in (np.zeros((2, 3), dtype=np.float64), np.array([[np.nan, 0, 0]], dtype=np.float32),
              np.zeros((2, 3, 3), dtype=np.float32)[:, ::2]):
        with pytest.raises(AppError):
            cpu.applyRGB(x)
