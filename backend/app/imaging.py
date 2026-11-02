import os
from pathlib import Path
from uuid import uuid4
import pyvips
from .errors import AppError
from .schemas import Recipe

pyvips.cache_set_max_mem(64 * 1024 * 1024)
pyvips.cache_set_max(100)


def inspect(path: Path, max_pixels=24_000_000):
    signature = path.read_bytes()[:8]
    kind = (
        "png"
        if signature == b"\x89PNG\r\n\x1a\n"
        else "jpg"
        if signature[:3] == b"\xff\xd8\xff"
        else None
    )
    if not kind:
        raise AppError("image_format", "仅支持真实 JPEG 和 PNG 图片。")
    image = pyvips.Image.new_from_file(
        str(path), access="sequential", fail_on="warning"
    )
    if image.width * image.height > max_pixels:
        raise AppError("image_size", "图片不能超过 2400 万像素。")
    if image.get_typeof("n-pages") and image.get("n-pages") > 1:
        raise AppError("image_frames", "首版暂不支持多帧图片。")
    # libvips PNG loaders can expose only the first APNG frame; detect acTL too.
    if kind == "png":
        with path.open("rb") as f:
            f.read(8)
            while chunk := f.read(8):
                if len(chunk) != 8:
                    break
                length, name = int.from_bytes(chunk[:4], "big"), chunk[4:]
                if name == b"acTL":
                    raise AppError("image_frames", "首版暂不支持动画 PNG。")
                if name == b"IEND":
                    break
                f.seek(length + 4, 1)
    image = image.autorot()
    return {"width": image.width, "height": image.height, "format": kind}


def clamp(image, low=0, high=1):
    return (image < low).ifthenelse(low, (image > high).ifthenelse(high, image))


def render(source: Path, target: Path, recipe: dict, max_edge=2560, lut_processor=None):
    r = Recipe.model_validate(recipe)
    im = pyvips.Image.new_from_file(
        str(source), access="sequential", fail_on="warning"
    ).autorot()
    if im.get_typeof("icc-profile-data"):
        try:
            im = im.icc_transform("srgb", embedded=True)
        except pyvips.Error as exc:
            raise AppError("icc_invalid", "图片色彩配置无法转换为 sRGB。") from exc
    else:
        im = im.colourspace("srgb")
    if im.format == "ushort":
        im = (im / 257).cast("uchar")
    if im.format != "uchar":
        im = clamp(im, 0, 255).cast("uchar")
    scale = min(1, max_edge / max(im.width, im.height))
    if scale < 1:
        im = (
            im.premultiply().resize(scale).unpremultiply().cast("uchar")
            if im.hasalpha()
            else im.resize(scale)
        )
    if r.lut and r.lut.strength and im.hasalpha():
        # LUT evaluation eagerly consumes RGB. Keep the resized source in memory
        # so alpha can be joined later without rereading a sequential decoder.
        im = im.copy_memory()
    alpha = im[-1] if im.hasalpha() else None
    rgb = im.extract_band(0, n=3).cast("float") / 255
    if r.exposure_ev:
        linear = (rgb <= 0.04045).ifthenelse(
            rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4
        )
        linear = clamp(linear * 2**r.exposure_ev)
        rgb = (linear <= 0.0031308).ifthenelse(
            linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055
        )
    rgb *= [1 + 0.12 * r.warmth, 1 + 0.02 * r.warmth, 1 - 0.12 * r.warmth]
    rgb = (rgb - 0.5) * r.contrast + 0.5
    grey = rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722
    rgb = grey + (rgb - grey) * r.saturation
    if r.lut:
        if lut_processor is None:
            raise AppError("lut_processor", "未加载 LUT，无法生成该配方。")
        if r.lut.strength:
            from .luts import np, require_engine

            require_engine()
            rgb = clamp(rgb).cast("float")
            pixels = np.frombuffer(rgb.write_to_memory(), dtype=np.float32).reshape(rgb.height, rgb.width, 3).copy()
            # Keep the blend scratch space bounded instead of retaining two
            # additional full-resolution RGB float buffers per photo.
            for row in range(0, rgb.height, 128):
                block = pixels[row:row + 128]
                if r.lut.strength < 1:
                    before = block.copy()
                    lut_processor.applyRGB(block)
                    block *= r.lut.strength
                    before *= 1 - r.lut.strength
                    block += before
                else:
                    lut_processor.applyRGB(block)
                if not np.isfinite(block).all():
                    raise AppError("lut_values", "LUT 产生了非有限数值，请换一个 LUT。")
            rgb = pyvips.Image.new_from_memory(pixels.data, rgb.width, rgb.height, 3, "float")
    out = (clamp(rgb) * 255).round("rint").cast("uchar").copy(interpretation="srgb")
    if alpha is not None:
        out = out.bandjoin(alpha)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{uuid4().hex}{target.suffix}")
    try:
        if target.suffix == ".png":
            out.pngsave(str(temp), strip=True, compression=6)
        else:
            out.jpegsave(str(temp), Q=92, strip=True, subsample_mode="off")
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return target
