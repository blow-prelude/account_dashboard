"""缓冲区 DTO 与批次状态机表（FZ-2 冻结对象，C2-B §4.2）。

为什么状态机表也放在这里而不是 ``api/guards.py``：

``repositories/staging_repo.py`` 的具名方法必须**自己**断言流转（C2-B §7"状态机被绕过"
的处置），但分层门禁禁止 ``repositories → api``。把「状态字面量 + 允许矩阵」放进
``models``（叶子层），两边都能引用；``api/guards.py`` 只是它的门面，供接口层调用。

D-1 裁决（矩阵优先）：

* ``PUT /mapping`` 成功即视为「映射已确认」→ 直接置 ``prechecked``；
* ``precheck`` 只允许在 ``prechecked`` 上调用，可重复（override 后刷新）；
* 在 ``mapped_pending`` 上调 precheck → ``409 E2002``「请先确认字段映射」。

这样预检结果永远不会基于未确认的映射，且 7×6 矩阵的其余行不需要改。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from account_dashboard.errors import BusinessRuleError, ErrorCode
from account_dashboard.models.internal import Channel, Direction, MappingSpec

BatchStatus = Literal[
    "uploaded",
    "mapped_pending",
    "prechecked",
    "ingesting",
    "ingested",
    "discarded",
    "failed",
]
BatchAction = Literal["parse", "map", "precheck", "confirm", "discard"]
RowLabel = Literal["new", "dup", "pending_manual"]

BATCH_STATES: tuple[str, ...] = (
    "uploaded",
    "mapped_pending",
    "prechecked",
    "ingesting",
    "ingested",
    "discarded",
    "failed",
)
ACTIONS: tuple[str, ...] = ("parse", "map", "precheck", "confirm", "discard")
# C2 已实现的四个动作；``confirm`` 留给 C3（矩阵里它有列、无格，任何状态调用都是 E2002）
C2_ACTIONS: tuple[str, ...] = ("parse", "map", "precheck", "discard")

STATUS_LABELS: dict[str, str] = {
    "uploaded": "已上传",
    "mapped_pending": "待映射",
    "prechecked": "待确认",
    "ingesting": "入库中",
    "ingested": "已入库",
    "discarded": "已丢弃",
    "failed": "失败",
}
ACTION_LABELS: dict[str, str] = {
    "parse": "解析",
    "map": "保存映射",
    "precheck": "去重预检",
    "confirm": "确认入库",
    "discard": "丢弃",
}

# 允许操作矩阵：{(当前状态, 动作): 允许落到的目标状态集合}
# 与 C2-B §4.2 的表逐格一一对应；C2 只实现四个动作，confirm 列留给 C3。
TRANSITIONS: dict[tuple[str, str], frozenset[str]] = {
    ("uploaded", "parse"): frozenset({"mapped_pending", "failed"}),
    ("failed", "parse"): frozenset({"mapped_pending", "failed"}),
    ("prechecked", "parse"): frozenset({"mapped_pending", "failed"}),
    ("mapped_pending", "map"): frozenset({"prechecked"}),
    ("prechecked", "map"): frozenset({"prechecked"}),
    ("prechecked", "precheck"): frozenset({"prechecked"}),
    ("uploaded", "discard"): frozenset({"discarded"}),
    ("failed", "discard"): frozenset({"discarded"}),
    ("mapped_pending", "discard"): frozenset({"discarded"}),
    ("prechecked", "discard"): frozenset({"discarded"}),
}


def can_transition(current: str, action: str, target: str | None = None) -> bool:
    allowed = TRANSITIONS.get((current, action))
    if allowed is None:
        return False
    return target is None or target in allowed


def assert_transition(current: str, action: str, target: str | None = None) -> None:
    """非法流转一律 ``E2002``（409）；文案告诉用户"下一步该做什么"。"""
    if current not in BATCH_STATES:
        raise BusinessRuleError(ErrorCode.BATCH_STATE_CONFLICT, f"批次状态不合法：{current}")
    if action not in ACTIONS:
        raise BusinessRuleError(ErrorCode.BATCH_STATE_CONFLICT, f"未知操作：{action}")

    allowed = TRANSITIONS.get((current, action))
    if allowed is None:
        raise BusinessRuleError(
            ErrorCode.BATCH_STATE_CONFLICT,
            f"批次当前为「{STATUS_LABELS[current]}」，不能执行「{ACTION_LABELS[action]}」",
            detail={"status": current, "action": action},
        )
    if target is not None and target not in allowed:
        raise BusinessRuleError(
            ErrorCode.BATCH_STATE_CONFLICT,
            f"「{STATUS_LABELS[current]}」不能变为「{STATUS_LABELS.get(target, target)}」",
            detail={"status": current, "action": action, "target": target},
        )


# ── 批次 ──────────────────────────────────────────────────────


class BatchDTO(BaseModel):
    id: str
    file_name: str
    file_size: int
    channel: Channel
    status: BatchStatus
    total_rows: int = 0
    new_count: int = 0
    dup_count: int = 0
    pending_count: int = 0
    encoding: str | None = None
    adapter: str | None = None
    fail_reason: str | None = None
    created_at: str
    updated_at: str


class ParseMetaDTO(BaseModel):
    """解析元信息：只在批次详情返回，用于「为什么行数和平台报的不一样」这类追问。

    ``columns`` 是 B 线追加的可选字段（ADDITIVE）：映射校验要用它判断列索引上界，
    否则每次保存映射都得重新解析一遍文件。
    """

    sheet: str | None = None
    delimiter: str | None = None
    preamble_rows: int = 0
    header_row_no: int = 0
    empty_rows_skipped: int = 0  # 数据区整行空行被跳过数，必须可见、不得静默丢弃
    issues: dict[str, int] = Field(default_factory=dict)
    columns: int = 0


class BatchDetailDTO(BatchDTO):
    header_row_no: int | None = None
    mapped_fields: MappingSpec | None = None
    mapping_snapshot: dict[str, Any] | None = None
    parse_meta: ParseMetaDTO | None = None
    report: dict[str, Any] | None = None  # C3 的 IngestReportDTO；C2 恒为 None
    file_exists: bool = False


class ParseInfoDTO(BaseModel):
    """``POST /parse`` 的响应：批次新状态 + 解析元信息。"""

    batch: BatchDTO
    parse_meta: ParseMetaDTO | None = None
    warnings: list[str] = Field(default_factory=list)


class DiscardReq(BaseModel):
    confirm: bool = True


# ── 预览 ──────────────────────────────────────────────────────


class ParseIssueDTO(BaseModel):
    code: str
    row_no: int
    field: str | None = None
    raw: str | None = None


class PreviewRowDTO(BaseModel):
    row_no: int
    occurred_at: str | None = None
    amount_cents: int | None = None
    direction: Direction | None = None
    counterparty: str | None = None
    item: str | None = None
    cells: list[str] = Field(default_factory=list)  # 与 headers 同序的原始值
    issues: list[ParseIssueDTO] = Field(default_factory=list)
    valid: bool = True


class PreviewDTO(BaseModel):
    batch_id: str
    total_rows: int
    columns: int
    header_row_no: int
    headers: list[str] = Field(default_factory=list)
    suggested_mapping: MappingSpec | None = None
    rows: list[PreviewRowDTO] = Field(default_factory=list)
    limit: int = 20
    truncated: bool = False


# ── 映射与模板 ────────────────────────────────────────────────


class MappingReq(BaseModel):
    """列索引映射；``-1`` 或 ``None`` 表示未映射。"""

    occurred_at: int = -1
    amount: int = -1
    direction: int = -1
    counterparty: int | None = None
    item: int | None = None
    txn_type: int | None = None
    payment_method: int | None = None
    platform_category: int | None = None
    platform_status: int | None = None
    direction_map: dict[str, Direction] = Field(default_factory=dict)  # 渠道值 → direction
    amount_scale: int = 1
    save_template: bool = False


class TemplateReq(BaseModel):
    channel: Channel
    name: str
    spec: MappingSpec
    policy: Literal["abort", "overwrite", "save_as"] = "abort"

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("模板名称不能为空")
        return cleaned[:60]


class TemplateDTO(BaseModel):
    id: str
    channel: Channel
    name: str
    spec: MappingSpec
    is_default: bool = False
    created_at: str
    updated_at: str


class MappingResultDTO(BaseModel):
    batch: BatchDTO
    warnings: list[str] = Field(default_factory=list)
    template: TemplateDTO | None = None


# ── 预检与强制新增 ────────────────────────────────────────────


class PrecheckRowDTO(BaseModel):
    row_no: int
    label: RowLabel
    occurred_at: str | None = None
    amount_cents: int | None = None
    direction: Direction | None = None
    counterparty: str | None = None
    item: str | None = None
    issues: list[ParseIssueDTO] = Field(default_factory=list)
    override: bool = False


class PrecheckResultDTO(BaseModel):
    summary: dict[str, int]  # {"total":669,"new":600,"dup":60,"pending_manual":9}
    rows: list[PrecheckRowDTO] = Field(default_factory=list)
    snapshot_at: str


class OverrideReq(BaseModel):
    row_no: int
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("必须填写强制新增的原因")
        return cleaned[:200]


class OverrideDTO(BaseModel):
    batch_id: str
    row_no: int
    reason: str
    created_at: str
    active: bool = True


class OverrideRevokeDTO(BaseModel):
    removed: bool = False


# ── 缓冲区运维 ────────────────────────────────────────────────


class BufferUsageDTO(BaseModel):
    file_count: int = 0
    total_bytes: int = 0
    threshold: int = 0
    exceeded: bool = False


class OrphanFileDTO(BaseModel):
    name: str
    size: int
    modified_at: str


class EnsureDirDTO(BaseModel):
    path: str
    created: bool = False


__all__ = [
    "ACTIONS",
    "ACTION_LABELS",
    "BATCH_STATES",
    "C2_ACTIONS",
    "STATUS_LABELS",
    "TRANSITIONS",
    "BatchAction",
    "BatchDetailDTO",
    "BatchDTO",
    "BatchStatus",
    "BufferUsageDTO",
    "DiscardReq",
    "EnsureDirDTO",
    "MappingReq",
    "MappingResultDTO",
    "OrphanFileDTO",
    "OverrideDTO",
    "OverrideReq",
    "OverrideRevokeDTO",
    "ParseInfoDTO",
    "ParseIssueDTO",
    "ParseMetaDTO",
    "PrecheckResultDTO",
    "PrecheckRowDTO",
    "PreviewDTO",
    "PreviewRowDTO",
    "RowLabel",
    "TemplateDTO",
    "TemplateReq",
    "assert_transition",
    "can_transition",
]
