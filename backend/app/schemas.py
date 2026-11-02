from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from .library_schemas import SearchIntent


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class LutReference(Strict):
    id: str
    name: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    strength: float = Field(1, ge=0, le=1)
    input_space: Literal["srgb"] = "srgb"
    output_space: Literal["srgb"] = "srgb"
    interpolation: Literal["tetrahedral"] = "tetrahedral"


class Recipe(Strict):
    schema_version: Literal[2] = 2
    preset_id: Literal["natural", "warm", "mono"] = "natural"
    exposure_ev: float = Field(0, ge=-2, le=2)
    warmth: float = Field(0, ge=-1, le=1)
    contrast: float = Field(1, ge=0.5, le=1.5)
    saturation: float = Field(1, ge=0, le=2)
    lut: LutReference | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_v1(cls, value):
        if isinstance(value, dict) and value.get("schema_version") == 1:
            if value.get("lut") is not None:
                raise ValueError("v1 recipes cannot contain a LUT")
            return {**value, "schema_version": 2, "lut": None}
        return value


class LutAction(Strict):
    op: Literal["select", "clear", "strength"]
    id: str | None = None
    strength: float | None = Field(None, ge=0, le=1)

    @model_validator(mode="after")
    def valid_operation(self):
        if self.op == "select" and not self.id:
            raise ValueError("select requires id")
        if self.op != "select" and self.id is not None:
            raise ValueError("only select accepts id")
        if self.op == "clear" and self.strength is not None:
            raise ValueError("clear does not accept strength")
        if self.op == "strength" and self.strength is None:
            raise ValueError("strength is required")
        return self


class Adjustment(Strict):
    field: Literal["exposure_ev", "warmth", "contrast", "saturation"]
    op: Literal["set", "add"]
    value: float


class MemoryAction(Strict):
    op: Literal["set", "clear", "read"]
    key: Literal["style_preference"] = "style_preference"
    value: str = Field("", max_length=500)


class Plan(Strict):
    status: Literal["ready", "search", "clarify", "unsupported"]
    message: str = Field(max_length=1500)
    target_asset_ids: list[str] = Field(default_factory=list, max_length=10)
    preset_id: Literal["natural", "warm", "mono"] | None = None
    adjustments: list[Adjustment] = Field(default_factory=list, max_length=12)
    memory_actions: list[MemoryAction] = Field(default_factory=list, max_length=3)
    lut_action: LutAction | None = None
    search_intent: SearchIntent | None = None
    search_id: str | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def no_conflicting_source(self):
        if self.preset_id and self.lut_action:
            raise ValueError("Choose a complete preset or a LUT patch, not both")
        return self


class PreviewRequest(Strict):
    context_revision: int
    target_asset_ids: list[str] = Field(min_length=1, max_length=10)
    preset_id: Literal["natural", "warm", "mono"] | None = None
    adjustments: list[Adjustment] = Field(default_factory=list, max_length=12)
    lut_action: LutAction | None = None
    personal_preset_id: str | None = None
    search_id: str | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def unique_source(self):
        if self.preset_id and self.personal_preset_id:
            raise ValueError("choose only one recipe source")
        return self


class ResetRequest(Strict):
    context_revision: int
    target_asset_ids: list[str] = Field(min_length=1, max_length=10)


class PresetName(Strict):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class SavePresetRequest(PresetName):
    project_id: str
    asset_id: str
    asset_revision: int = Field(ge=0)


class RenamePresetRequest(PresetName):
    revision: int = Field(ge=0)


class InstructionRequest(Strict):
    context_revision: int
    request_id: str = Field(min_length=8, max_length=100)
    text: str = Field(min_length=1, max_length=2000)


class WorkspaceRequest(Strict):
    context_revision: int
    selected_asset_ids: list[str] = Field(max_length=10)
    viewed_asset_id: str | None = None


class ProjectRequest(Strict):
    name: str = Field("未命名影集", min_length=1, max_length=80)


class PreferenceRequest(Strict):
    context_revision: int
    value: str = Field(max_length=500)
