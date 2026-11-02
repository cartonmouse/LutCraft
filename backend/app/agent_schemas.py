"""Version-independent business contract. No runtime identities in model arguments."""

from typing import Literal

from pydantic import Field, model_validator

from .schemas import Adjustment, LutAction, Strict
from .library_schemas import SearchIntent, StyleArgs


class EmptyArgs(Strict):
    pass


class Scope(Strict):
    kind: Literal["selected", "viewed", "all", "ordinals", "ids"] = "selected"
    ordinals: list[int] = Field(default_factory=list, max_length=10)
    asset_ids: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def matches_kind(self):
        if bool(self.ordinals) != (self.kind == "ordinals"):
            raise ValueError("ordinals required only for ordinal scope")
        if bool(self.asset_ids) != (self.kind == "ids"):
            raise ValueError("asset_ids required only for id scope")
        return self


class PreviewArgs(Strict):
    scope: Scope = Field(default_factory=Scope)
    preset_id: Literal["natural", "warm", "mono"] | None = None
    adjustments: list[Adjustment] = Field(default_factory=list, max_length=12)
    lut_action: LutAction | None = None
    personal_preset_id: str | None = Field(None, max_length=100)
    search_id: str | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def valid_source(self):
        if self.preset_id and self.personal_preset_id:
            raise ValueError("Only one complete recipe source is allowed")
        if not (
            self.preset_id
            or self.personal_preset_id
            or self.adjustments
            or self.lut_action
        ):
            raise ValueError("Specify an adjustment")
        return self


class ResetArgs(Strict):
    scope: Scope = Field(default_factory=Scope)


class StylesArgs(Strict):
    kind: Literal["all", "builtin", "lut", "personal"] = "all"
    query: str = Field("", max_length=80)


class OperationArgs(Strict):
    operation_id: str = Field(min_length=1, max_length=100)


class MemoryArgs(Strict):
    op: Literal["read", "set", "clear"]
    value: str = Field("", max_length=500)

    @model_validator(mode="after")
    def value_for_set(self):
        if self.op == "set" and not self.value.strip():
            raise ValueError("Preference cannot be empty")
        if self.op != "set" and self.value:
            raise ValueError("Only set accepts a value")
        return self


TOOLS = {
    "lut_search": (SearchIntent, "按中文需求检索当前用户可用且兼容的 LUT，返回候选与依据；无匹配时不得硬选。"),
    "lut_get_style": (StyleArgs, "读取当前用户 LUT 的效果描述、兼容性、来源及建议强度。"),
    "lut_get_context": (
        EmptyArgs,
        "读取当前项目、照片编号、选图、完整配方和明确偏好；不能查看照片像素。",
    ),
    "lut_list_styles": (
        StylesArgs,
        "列出当前用户已有的内置预设、LUT 和个人预设。名称含糊时先询问。",
    ),
    "lut_preview": (
        PreviewArgs,
        "为明确范围生成调色预览；本轮最多一次；需要用户在网页确认才能批量应用。",
    ),
    "lut_reset_preview": (ResetArgs, "生成清除调色与 LUT 的预览，仍需网页确认。"),
    "lut_get_operation": (
        OperationArgs,
        "读取当前项目真实任务状态，不得根据回复文本推断已完成。",
    ),
    "lut_project_memory": (
        MemoryArgs,
        "读写当前项目偏好；写入或清除仅在用户明确要求时使用。",
    ),
}


class BridgeCall(Strict):
    # Supplied by a verified host adapter, never exposed as model tool parameters.
    agent_id: str = Field(min_length=1, max_length=100)
    runtime_session: str = Field(min_length=1, max_length=300)
    call_id: str = Field(min_length=1, max_length=200)
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict = Field(default_factory=dict)


class BridgeHello(Strict):
    agent_id: str = Field(min_length=1, max_length=100)
    runtime_version: str = Field(min_length=1, max_length=100)


def tool_catalog():
    return [
        {"name": name, "description": desc, "parameters": schema.model_json_schema()}
        for name, (schema, desc) in TOOLS.items()
    ]
