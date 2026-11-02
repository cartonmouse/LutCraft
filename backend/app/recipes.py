from .schemas import Recipe

PRESETS = {
    "natural": Recipe(),
    "warm": Recipe(
        preset_id="warm", exposure_ev=0.1, warmth=0.2, contrast=1.05, saturation=0.95
    ),
    "mono": Recipe(preset_id="mono", saturation=0),
}


def merge_recipe(base, preset, adjustments):
    result = (PRESETS[preset] if preset else Recipe.model_validate(base)).model_dump()
    for adj in adjustments:
        result[adj.field] = round(
            (result[adj.field] if adj.op == "add" else 0) + adj.value, 6
        )
    return Recipe.model_validate(result).model_dump()
