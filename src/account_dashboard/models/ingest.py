"""入库 / 原始库 / 追溯 / 清理域的对外 DTO（FZ-3 冻结，Gate 0 签字）。

冻结规则同 ``models/staging.py``：字段名与类型一经发布，下游只允许**加字段**
（可选、带默认值），不允许改名、改类型、反转 ``null`` 语义。新增字段同步
``docs/devel/CONTRACT-CHANGELOG.md``。

前端已按这些字段实现（``pages/import.js`` / ``pages/raw.js`` / ``pages/buffer.js``），
逐字段核对过一遍，改名即联调爆炸。

两处**有意为之的不同构**（防"顺手统一"）：

* ``IngestReportDTO.monthly`` 的键是归档表名 ``"raw_2026_06"``；
* ``RawMonthDTO.month`` 是月份键 ``"2026_06"``（前端拼 ``raw_${ym}`` 查表）；
* ``IngestReportDTO.finished_at`` 对应 DB 列 ``committed_at``（DTO 改名）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from account_dashboard.models.staging import BatchDTO


class SkippedRowDTO(BaseModel):
    """被跳过行的明细（D-6：不可解析行既不写 raw 也不写 transaction，报告是唯一留痕）。"""

    row_no: int
    reason: str          # "AMOUNT_PARSE" / "TIME_PARSE" / "DUP"
    field: str | None = None
    raw: str | None = None        # 原始值，截断 64 字符


class IngestReportDTO(BaseModel):
    batch_id: str
    total: int
    inserted: int
    skipped_dup: int
    skipped_invalid: int = 0
    pending: int
    monthly: dict[str, int] = {}          # {"raw_2026_06": 101}
    files_deleted: bool = True
    cleanup_pending: bool = False
    cleanup_id: str | None = None
    finished_at: str                      # DB 列叫 committed_at，DTO 改名（前端按 finished_at）


class IngestReportDetailDTO(IngestReportDTO):
    skipped: list[SkippedRowDTO] = []     # 仅 include_skipped=true 时填充


class RawMonthDTO(BaseModel):
    month: str                            # "2026_06"，无 raw_ 前缀
    count: int


class RawRecordDTO(BaseModel):
    id: int
    batch_id: str
    row_no: int
    occurred_at: str
    amount_cents: int
    direction: str
    counterparty: str | None = None
    item: str | None = None
    txn_type: str | None = None
    payment_method: str | None = None
    platform_category: str | None = None
    platform_status: str | None = None
    channel: str
    fp: str | None = None
    imported_at: str


class RawRecordDetailDTO(RawRecordDTO):
    raw_payload: dict[str, Any]


class TraceTransactionDTO(BaseModel):
    """C4 完整 ``TransactionDTO`` 的子集；C4 扩展时必须保留这些字段名。

    业务字段与 raw 行一一对应（双写口径的 11 字段，见
    ``tests/helpers/ingest_state.py::_TRACE_FIELDS``），另加 ``id`` / ``status``
    两个主数据侧管理字段。
    """

    id: str
    batch_id: str
    row_no: int
    occurred_at: str
    amount_cents: int
    direction: str
    counterparty: str | None = None
    item: str | None = None
    txn_type: str | None = None
    payment_method: str | None = None
    channel: str
    fp: str | None = None
    status: str


class TraceDTO(BaseModel):
    transaction: TraceTransactionDTO
    batch: BatchDTO | None = None
    raw_record: RawRecordDTO | None = None
    mapping_snapshot: dict[str, Any] | None = None


class CleanupItemDTO(BaseModel):
    id: str
    batch_id: str | None = None
    file_path: str
    file_name: str | None = None          # 由 LEFT JOIN staging_batch 派生，DDL 无此列
    reason: str
    attempts: int
    last_error: str | None = None
    status: str                           # pending / done / abandoned
    created_at: str
    updated_at: str


class OrphanCleanupDTO(BaseModel):
    removed: list[str] = []
    # [{"name": ..., "code": "E4003"}]
    failed: list[dict[str, str]] = Field(default_factory=list)


__all__ = [
    "CleanupItemDTO",
    "IngestReportDTO",
    "IngestReportDetailDTO",
    "OrphanCleanupDTO",
    "RawMonthDTO",
    "RawRecordDTO",
    "RawRecordDetailDTO",
    "SkippedRowDTO",
    "TraceDTO",
    "TraceTransactionDTO",
]
