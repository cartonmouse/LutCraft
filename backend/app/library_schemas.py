"""Bounded library contracts; these contain data, never execution instructions."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Short = Annotated[str, Field(min_length=1, max_length=80)]


class LibraryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class Metadata(LibraryModel):
    description: str = Field("", max_length=1200)
    category: str = Field("", max_length=80)
    tags: list[Short] = Field(default_factory=list, max_length=24)
    aliases: list[Short] = Field(default_factory=list, max_length=24)
    use_cases: list[Short] = Field(default_factory=list, max_length=12)
    cautions: str = Field("", max_length=800)
    publisher: str = Field("", max_length=160)
    source_page: str = Field("", max_length=1000)
    license_note: str = Field("", max_length=1200)
    input_space: Literal["srgb", "unknown", "other"] = "unknown"
    output_space: Literal["srgb", "unknown", "other"] = "unknown"
    compatibility_basis: str = Field("", max_length=800)
    recommended_strength: float | None = Field(None, ge=0, le=1)
    strength_basis: str = Field("", max_length=500)


class MetadataPatch(LibraryModel):
    revision: int = Field(ge=0)
    metadata: Metadata = Field(default_factory=Metadata)
    enabled: bool | None = None
    compatibility: Literal["unknown", "confirmed", "incompatible"] | None = None
    accept_suggestions: list[Short] = Field(default_factory=list, max_length=16)


class SearchIntent(LibraryModel):
    query: str = Field(min_length=1, max_length=500)
    desired_features: list[Short] = Field(default_factory=list, max_length=12)
    avoid_features: list[Short] = Field(default_factory=list, max_length=12)
    excluded_features: list[Short] = Field(default_factory=list, max_length=12)
    exact_name: str | None = Field(None, max_length=80)
    limit: int = Field(5, ge=1, le=5)


class SearchRequest(SearchIntent):
    project_id: str | None = Field(None, min_length=1, max_length=100)


class StyleArgs(LibraryModel):
    id: str = Field(min_length=1, max_length=100)


class CandidatePreview(LibraryModel):
    search_id: str = Field(min_length=1, max_length=100)
    lut_id: str = Field(min_length=1, max_length=100)
    context_revision: int = Field(ge=0)
    target_asset_ids: list[str] = Field(min_length=1, max_length=10)
    strength: float = Field(0.75, ge=0, le=1)
