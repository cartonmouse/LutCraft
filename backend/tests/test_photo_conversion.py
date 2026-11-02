"""Numerical and loader checks only: no photo fixtures, rendering or image I/O."""
import hashlib
from pathlib import Path
import sys

import numpy as np
import pytest

from app.clf import inspect_clf
from app.errors import AppError
from app import single_pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lut-library/tools"))
from photo_conversion_math import (ADOBE_GAMMA, ADOBE_TO_SRGB, SRGB_TO_ADOBE,
    evaluate, from_source, grid, load_table, processor, reference, source_agreement,
    srgb_decode, srgb_encode, tetra, to_source, write_clf)


def source_file(tmp_path, size=17):
    path = tmp_path / "source.cube"
    # Non-symmetric channel transform catches RGB axis/order mistakes.
    x = grid(np.linspace(0, 1, size))
    table = np.stack((.03 + .7 * x[:, 1] ** 2 + .1 * x[:, 2],
                      .05 + .8 * x[:, 2], .04 + .7 * x[:, 0]), axis=1)
    np.savetxt(path, table, fmt="%.9f", header=f"LUT_3D_SIZE {size}", comments="")
    return path


def test_standard_curves_matrices_and_extended_negative_values():
    np.testing.assert_allclose(srgb_decode(np.array([0, .04045, .5, 1])),
                               [0, .04045 / 12.92, .21404114048223255, 1], atol=1e-15)
    assert ADOBE_GAMMA == 2.19921875
    np.testing.assert_allclose(SRGB_TO_ADOBE @ np.ones(3), np.ones(3), atol=1e-14)
    np.testing.assert_allclose(ADOBE_TO_SRGB @ SRGB_TO_ADOBE, np.eye(3), atol=1e-14)
    # A negative channel must survive conversion until the production blend.
    assert srgb_encode(np.array([-.1]))[0] == pytest.approx(-1.292)
    x = np.random.default_rng(71).random((4096, 3))
    for route in ("adobe_rgb", "gamma24"):
        np.testing.assert_allclose(from_source(to_source(x, route), route), x, atol=3e-8, rtol=0)


@pytest.mark.parametrize("route,size", [("adobe_rgb", 32), ("adobe_rgb", 40), ("gamma24", 32)])
def test_standalone_clf_against_independent_reference_and_production_loader(tmp_path, monkeypatch, route, size):
    source = source_file(tmp_path, size)
    table = load_table(source, size)
    assert source_agreement(table, size, source)["max_error"] < 2e-6
    clf = tmp_path / "lut-library/luts/test.clf"
    clf.parent.mkdir(parents=True)
    write_clf(source, route, clf)
    info = inspect_clf(clf.read_bytes())
    assert info["grid_size"] == size
    assert info["lut_type"] == "CLF"
    assert b"Reference" not in clf.read_bytes()
    source.unlink()  # CLF must work without any external source file.
    monkeypatch.setattr(single_pass, "ROOT", tmp_path)
    row = {"path": "luts/test.clf", "sha256": info["sha256"]}
    cpu = single_pass.load_catalog_processor(row)
    x = np.concatenate((grid(np.linspace(0, 1, 19)), np.random.default_rng(9).random((8192, 3))))
    actual, expected = evaluate(cpu, x), reference(table, size, x, route)
    assert actual.min() < 0 or route == "gamma24"
    for s in (.25, .5, .75, 1):
        error = np.abs(np.clip(actual * s + x * (1 - s), 0, 1) - np.clip(expected * s + x * (1 - s), 0, 1))
        assert error.max() < 1 / 255
        assert np.sqrt((error ** 2).mean()) < .25 / 255
    with pytest.raises(AppError, match="校验失败"):
        single_pass.load_catalog_processor({**row, "sha256": "0" * 64})


def test_original_cube_loader_is_retained_and_paths_are_confined(tmp_path, monkeypatch):
    source = source_file(tmp_path)
    monkeypatch.setattr(single_pass, "ROOT", tmp_path)
    dest = tmp_path / "lut-library/luts/direct.cube"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(source.read_bytes())
    row = {"path": "luts/direct.cube", "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()}
    cpu = single_pass.load_catalog_processor(row)
    x = np.array([[.21, .44, .79], [0, 1, .5]])
    np.testing.assert_allclose(evaluate(cpu, x), tetra(load_table(dest, 17), 17, x), atol=1e-6)
    with pytest.raises(AppError, match="路径无效"):
        single_pass.load_catalog_processor({**row, "path": "../source.cube"})


@pytest.mark.parametrize("mutation", ["entity", "reference", "nan", "wrong_dim", "unknown_node", "oversize"])
def test_rejects_unsafe_or_invalid_clf_before_engine(tmp_path, mutation):
    source = source_file(tmp_path)
    clf = tmp_path / "test.clf"
    write_clf(source, "adobe_rgb", clf)
    data = clf.read_bytes()
    if mutation == "entity":
        data = data.replace(b"<ProcessList", b'<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///private">]><ProcessList', 1)
    elif mutation == "reference":
        data = data.replace(b"<LUT3D ", b'<Reference path="/private" ', 1)
    elif mutation == "nan":
        data = data.replace(b'exponent="2.4"', b'exponent="nan"', 1)
    elif mutation == "wrong_dim":
        data = data.replace(b'dim="17 17 17 3"', b'dim="65 65 65 3"', 1)
    elif mutation == "unknown_node":
        data = data.replace(b"</ProcessList>", b"<FileTransform src='/private'/></ProcessList>")
    else:
        data = b" " * (10 * 1024 * 1024 + 1)
    with pytest.raises(AppError, match="CLF 无效"):
        inspect_clf(data)
