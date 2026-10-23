"""缓冲区 / 导入链路的对外 DTO（FZ-2 冻结，SDD §6.3）。

冻结规则：字段名与类型一经发布，下游只允许**加字段**（可选、带默认值），
不允许改名、改类型、反转 ``null`` 语义。新增字段请同步 `CONTRACT-CHANGELOG`。

C2 阶段没有 ``report`` 字段：导入报告属于 C3 的 ``IngestReportDTO``，
届时以「新增可选字段」的方式加进 ``BatchDetailDTO``，而不是现在占一个 ``dict`` 位。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from account_dashboard.models.enums import BatchStatus, Channel, DedupLabel, Direction

TemplatePolicy = Literal["abort", "overwrite", "save_as"]


class ParseIssueDTO(BaseModel):
    """行级问题（EX-06/07）。"""

    code: str
    row_no: int
    field: str | None = None
    raw_value: str | None = None


class ParseMetaDTO(BaseModel):
    """解析元信息：用于回答「为什么行数和平台报的不一样」。"""

    sheet: str | None = None
    delimiter: str | None = None
    preamble_rows: int = 0
    header_row_no: int = 0
    empty_rows_skipped: int = 0
    column_count: int = 0
    columns: list[str] = Field(default_factory=list)
    issues: dict[str, int] = Field(default_factory=dict)


class ParseInfoDTO(BaseModel):
    """解析结果的「本轮」摘要（不落库，随 parse 响应返回）。"""

    adapter: str
    encoding: str
    header_row_no: int
    total_rows: int
    empty_rows_skipped: int = 0
    columns: list[str] = Field(default_factory=list)
    issues: dict[str, int] = Field(default_factory=dict)


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


class BatchDetailDTO(BatchDTO):
    header_row_no: int | None = None
    mapped_fields: MappingReq | None = None
    mapping_snapshot: dict[str, Any] | None = None
    parse_meta: ParseMetaDTO | None = None
    file_exists: bool = False


class ParseResultDTO(BaseModel):
    """``POST /batches/{id}/parse`` 的载荷：批次快照 + 本轮解析摘要。"""

    batch: BatchDTO
    parse: ParseInfoDTO


class MappingReq(BaseModel):
    """列索引映射；``-1`` 或 ``None`` 表示未映射。

    ``amount_scale`` 语义：``1`` 表示原始列单位是**元**（默认），
    ``100`` 表示原始列单位是**分**（个别银行导出如此）。
    """

    occurred_at: int = -1
    amount: int = -1
    direction: int = -1
    counterparty: int | None = None
    item: int | None = None
    txn_type: int | None = None
    payment_method: int | None = None
    platform_category: int | None = None
    platform_status: int | None = None
    direction_map: dict[str, Direction] = Field(default_factory=dict)
    amount_scale: int = 1
    save_template: bool = False
    template_name: str | None = None
    template_policy: TemplatePolicy = "abort"


class MappingResultDTO(BaseModel):
    batch_id: str
    mapping: MappingReq
    columns: list[str] = Field(default_factory=list)
    template_id: str | None = None
    status: BatchStatus


class TemplateReq(BaseModel):
    channel: Channel
    name: str = "默认"
    spec: MappingReq
    policy: TemplatePolicy = "abort"


class TemplateDTO(BaseModel):
    id: str
    channel: Channel
    name: str
    spec: MappingReq
    is_default: bool = False
    created_at: str
    updated_at: str


class PreviewRowDTO(BaseModel):
    row_no: int
    occurred_at: str | None = None
    amount_cents: int | None = None
    direction: Direction | None = None
    counterparty: str | None = None
    item: str | None = None
    txn_type: str | None = None
    payment_method: str | None = None
    platform_category: str | None = None
    platform_status: str | None = None
    fingerprint: str | None = None
    issues: list[ParseIssueDTO] = Field(default_factory=list)


class PreviewDTO(BaseModel):
    """前 N 行 + 字段识别结果（只读，不落库）。"""

    batch_id: str
    header_row_no: int
    header_recognized: bool = True
    columns: list[str] = Field(default_factory=list)
    detected_fields: dict[str, int] = Field(default_factory=dict)
    rows: list[PreviewRowDTO] = Field(default_factory=list)
    total_rows: int = 0
    empty_rows_skipped: int = 0
    issues: dict[str, int] = Field(default_factory=dict)
    limit: int = 20
    message: str = ""


class PrecheckRowDTO(BaseModel):
    row_no: int
    label: DedupLabel
    occurred_at: str | None = None
    amount_cents: int | None = None
    direction: Direction | None = None
    counterparty: str | None = None
    item: str | None = None
    fingerprint: str | None = None
    issues: list[ParseIssueDTO] = Field(default_factory=list)
    override: bool = False


class PrecheckResultDTO(BaseModel):
    batch_id: str
    summary: dict[str, int] = Field(default_factory=dict)
    rows: list[PrecheckRowDTO] = Field(default_factory=list)
    snapshot_at: str
    issues: dict[str, int] = Field(default_factory=dict)
    message: str = ""


class OverrideReq(BaseModel):
    row_no: int
    reason: str = Field(min_length=1, max_length=200)
    note: str = ""


class OverrideDTO(BaseModel):
    batch_id: str
    row_no: int
    reason: str
    note: str = ""
    created_at: str


class RemovedDTO(BaseModel):
    removed: bool


class DiscardReq(BaseModel):
    """丢弃需要二次确认（SDD §6.2.2）。"""

    confirm: bool = False


class OrphanFileDTO(BaseModel):
    name: str
    size_bytes: int
    modified_at: str


class OrphanCleanupReq(BaseModel):
    """``POST /staging/orphans/cleanup`` 的请求体（C3-B 新增，前端已按此调用）。"""

    names: list[str] = Field(min_length=1, max_length=200)


class BufferUsageDTO(BaseModel):
    file_count: int = 0
    total_bytes: int = 0
    threshold_bytes: int = 0
    exceeded: bool = False
    oldest_at: str | None = None


class EnsureDirDTO(BaseModel):
    path: str
    created: bool = False
