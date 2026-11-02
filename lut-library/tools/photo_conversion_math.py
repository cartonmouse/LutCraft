"""Versioned, relative-colorimetric sRGB wrappers; no image I/O.

Reference evaluation is float64 with an independent tetrahedral interpolator.
Production CUBE evaluation is separately checked using OpenColorIO float32.
"""
import itertools

import numpy as np
import PyOpenColorIO as ocio

VERSION = "srgb-photo-wrapper-v1"
ADOBE_GAMMA = 563 / 256
WHITE = (0.3127, 0.3290)
SRGB_PRIMARIES = ((0.64, 0.33), (0.30, 0.60), (0.15, 0.06))
ADOBE_PRIMARIES = ((0.64, 0.33), (0.21, 0.71), (0.15, 0.06))
MAX_ERROR = 1 / 255
RMS_ERROR = 0.25 / 255
SEED = 20261030


def rgb_xyz(primaries):
    xy = np.asarray(primaries, dtype=np.float64)
    columns = np.stack((xy[:, 0] / xy[:, 1], np.ones(3),
                        (1 - xy.sum(axis=1)) / xy[:, 1]))
    x, y = WHITE
    white = np.array([x / y, 1, (1 - x - y) / y])
    return columns * np.linalg.solve(columns, white)


SRGB_TO_ADOBE = np.linalg.solve(rgb_xyz(ADOBE_PRIMARIES), rgb_xyz(SRGB_PRIMARIES))
ADOBE_TO_SRGB = np.linalg.inv(SRGB_TO_ADOBE)


def srgb_decode(x):
    x = np.asarray(x, dtype=np.float64)
    out = x / 12.92
    mask = x > 0.04045
    out[mask] = ((x[mask] + 0.055) / 1.055) ** 2.4
    return out


def srgb_encode(x):
    x = np.asarray(x, dtype=np.float64)
    out = x * 12.92  # Versioned extension: ALL negative values use this branch.
    mask = x > 0.0031308
    out[mask] = 1.055 * x[mask] ** (1 / 2.4) - 0.055
    return out


def to_source(x, route):
    linear = srgb_decode(x)
    if route == "adobe_rgb":
        linear = linear @ SRGB_TO_ADOBE.T
        gamma = ADOBE_GAMMA
    elif route == "gamma24":
        gamma = 2.4
    else:
        raise ValueError("Unapproved route: " + route)
    # Only round-off at the boundary is allowed, never a gamut compression.
    if linear.min() < -1e-12 or linear.max() > 1 + 1e-12:
        raise ValueError("sRGB input unexpectedly outside source gamut")
    return np.clip(linear, 0, 1) ** (1 / gamma)


def from_source(x, route):
    if x.min() < -1e-12 or x.max() > 1 + 1e-12:
        raise ValueError("Selected source must have normalized outputs")
    if route == "adobe_rgb":
        linear = np.maximum(x, 0) ** ADOBE_GAMMA @ ADOBE_TO_SRGB.T
    elif route == "gamma24":
        linear = np.maximum(x, 0) ** 2.4
    else:
        raise ValueError("Unapproved route: " + route)
    return srgb_encode(linear)


def load_table(path, size):
    # Syntax and domain are checked by library.inspect_cube before this call.
    with path.open(encoding="utf-8-sig") as f:
        lines = (line for line in f if line.strip() and
                 not line.lstrip().startswith(("#", "TITLE", "LUT_", "DOMAIN_")))
        table = np.loadtxt(lines, dtype=np.float64, comments="#")
    if table.shape != (size ** 3, 3):
        raise ValueError("Wrong source table shape")
    return table


def tetra(table, size, x):
    """R-fast CUBE tetrahedra, vertices ordered by fractional coordinates."""
    q = np.clip(np.asarray(x, dtype=np.float64), 0, 1) * (size - 1)
    base = np.minimum(np.floor(q).astype(np.int64), size - 2)
    fraction = q - base
    order = np.argsort(-fraction, axis=1, kind="stable")
    f = np.take_along_axis(fraction, order, axis=1)
    strides = np.array([1, size, size * size], dtype=np.int64)
    i0 = base @ strides
    i1 = i0 + strides[order[:, 0]]
    i2 = i1 + strides[order[:, 1]]
    i3 = i2 + strides[order[:, 2]]
    return (table[i0] * (1 - f[:, :1]) + table[i1] * (f[:, :1] - f[:, 1:2]) +
            table[i2] * (f[:, 1:2] - f[:, 2:3]) + table[i3] * f[:, 2:3])


def reference(table, size, x, route):
    return from_source(tetra(table, size, to_source(x, route)), route)


def processor(path):
    return ocio.Config.CreateRaw().getProcessor(ocio.FileTransform(
        src=str(path.resolve()), interpolation=ocio.INTERP_TETRAHEDRAL)).getDefaultCPUProcessor()


def write_clf(source, route, target):
    """Embed source table and analytical transforms, with no 3D re-sampling.

    CLF monCurve uses the continuous sRGB approximation (gamma=2.4,
    offset=.055). Its computed knee/slope differ slightly from IEC's rounded
    .04045/12.92. validate() compares the serialized result to the exact
    piecewise reference, including negative values and post-blend clipping.
    """
    def matrix(value):
        m = np.eye(4)
        m[:3, :3] = value
        return ocio.MatrixTransform(matrix=m.ravel().tolist())

    gamma = ADOBE_GAMMA if route == "adobe_rgb" else 2.4
    group = ocio.GroupTransform()
    group.appendTransform(ocio.ExponentWithLinearTransform(
        gamma=[2.4, 2.4, 2.4, 1], offset=[.055, .055, .055, 0], negativeStyle=ocio.NEGATIVE_LINEAR))
    if route == "adobe_rgb":
        group.appendTransform(matrix(SRGB_TO_ADOBE))
    group.appendTransform(ocio.ExponentTransform(value=[1 / gamma] * 3 + [1]))
    group.appendTransform(ocio.FileTransform(src=str(source.resolve()), interpolation=ocio.INTERP_TETRAHEDRAL))
    group.appendTransform(ocio.ExponentTransform(value=[gamma] * 3 + [1]))
    if route == "adobe_rgb":
        group.appendTransform(matrix(ADOBE_TO_SRGB))
    group.appendTransform(ocio.ExponentWithLinearTransform(
        gamma=[2.4, 2.4, 2.4, 1], offset=[.055, .055, .055, 0],
        negativeStyle=ocio.NEGATIVE_LINEAR, direction=ocio.TRANSFORM_DIR_INVERSE))
    raw = ocio.Config.CreateRaw()
    expanded = raw.getProcessor(group).createGroupTransform()
    expanded.write("Academy/ASC Common LUT Format", str(target), raw)


def evaluate(cpu, x):
    out = np.array(x, dtype=np.float32, order="C", copy=True)
    cpu.applyRGB(out)
    if not np.isfinite(out).all():
        raise ValueError("Non-finite OpenColorIO output")
    return out.astype(np.float64)


def grid(axis):
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    return np.stack((r.ravel(), g.ravel(), b.ravel()), axis=1)


def samples():
    """Independent validation samples (never fitted to any individual LUT)."""
    rng = np.random.default_rng(SEED)
    yield "cell_centers", grid((np.arange(64) + 0.5) / 64)
    yield "random_uniform", rng.random((200000, 3))
    yield "dark_biased", rng.random((32768, 3)) ** 3
    a, b = np.meshgrid(np.linspace(0, 1, 129), np.linspace(0, 1, 129), indexing="ij")
    for axis in range(3):
        for side in (0, 1):
            x = np.empty((a.size, 3))
            x[:, axis] = side
            x[:, [i for i in range(3) if i != axis]] = np.stack((a.ravel(), b.ravel()), axis=1)
            yield f"face_{axis}_{side}", x
    axis = np.linspace(0, 1, 4097)
    yield "gray", np.repeat(axis[:, None], 3, axis=1)
    for varying in range(3):
        for ends in itertools.product((0, 1), repeat=2):
            x = np.empty((len(axis), 3))
            x[:, varying] = axis
            x[:, [i for i in range(3) if i != varying]] = ends
            yield f"edge_{varying}_{ends[0]}{ends[1]}", x
    # Both sides of the sRGB knee and of each source-grid crossing on neutral.
    knees = np.array([0, 1e-8, 0.04045 - 1e-7, 0.04045, 0.04045 + 1e-7, 1])
    yield "srgb_knee", grid(knees)


def validate(table, size, route, path):
    cpu = processor(path)
    strengths = (0.25, 0.5, 0.75, 1.0)
    maxima = {s: 0.0 for s in strengths}
    sums = {s: 0.0 for s in strengths}
    total, outside, raw_max, raw_sum = 0, 0, 0.0, 0.0
    low, high, worst = float("inf"), float("-inf"), None
    groups = []
    def extra_samples():
        knots = from_source(grid(np.linspace(0, 1, size)), route)
        knots = knots[((knots >= 0) & (knots <= 1)).all(axis=1)]
        yield "source_knots", knots
        for delta in (-1e-5, 1e-5, -0.001, 0.001):
            yield f"source_knots_offset_{delta}", np.clip(knots + delta, 0, 1)
        yield "holdout_random", np.random.default_rng(SEED + 1).random((1000000, 3))

    for name, x in itertools.chain(samples(), extra_samples()):
        ref, actual = reference(table, size, x, route), evaluate(cpu, x)
        if not np.isfinite(ref).all():
            raise ValueError("Non-finite reference")
        total += len(x)
        outside += int(((ref < 0) | (ref > 1)).any(axis=1).sum())
        low, high = min(low, float(ref.min())), max(high, float(ref.max()))
        raw = np.abs(ref - actual)
        raw_max, raw_sum = max(raw_max, float(raw.max())), raw_sum + float((raw ** 2).sum())
        group_max = 0.0
        for strength in strengths:
            expected = np.clip(x * (1 - strength) + ref * strength, 0, 1)
            # Reproduce the production float32, encoded-sRGB blend, then clamp.
            blended = (x.astype(np.float32) * np.float32(1 - strength) +
                       actual.astype(np.float32) * np.float32(strength))
            error = np.abs(expected - np.clip(blended, 0, 1))
            value = float(error.max())
            if worst is None or value > worst["error"]:
                point, channel = np.unravel_index(np.argmax(error), error.shape)
                worst = {"group": name, "rgb": x[point].tolist(), "strength": strength,
                         "channel": int(channel), "error": value,
                         "reference_extended": ref[point].tolist(), "baked_extended": actual[point].tolist()}
            maxima[strength] = max(maxima[strength], value)
            sums[strength] += float((error ** 2).sum())
            group_max = max(group_max, value)
        groups.append({"name": name, "samples": len(x), "max_error": group_max})
    metrics = [{"strength": s, "max_error": maxima[s], "rms_error": (sums[s] / (3 * total)) ** 0.5}
               for s in strengths]
    return {"passed": all(m["max_error"] <= MAX_ERROR and m["rms_error"] <= RMS_ERROR for m in metrics),
            "sample_count": total, "seed": SEED, "limits": {"max_error": MAX_ERROR, "rms_error": RMS_ERROR},
            "strengths": metrics, "groups": groups, "worst": worst,
            "extended": {"min": low, "max": high, "out_of_gamut_samples": outside,
                         "out_of_gamut_fraction": outside / total, "max_error": raw_max,
                         "rms_error": (raw_sum / (3 * total)) ** 0.5},
            "scope": "finite deterministic numerical sample suite, not a whole-domain proof or photo effect test"}


def source_agreement(table, size, path):
    x = np.concatenate((np.random.default_rng(SEED).random((8192, 3)), grid(np.array([0, 0.5, 1]))))
    delta = np.abs(tetra(table, size, x) - evaluate(processor(path), x))
    result = {"samples": len(x), "max_error": float(delta.max()), "limit": 2e-6}
    if result["max_error"] > result["limit"]:
        raise ValueError("Independent source interpolation disagrees with OpenColorIO")
    return result
