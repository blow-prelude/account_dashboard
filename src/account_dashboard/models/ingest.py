"""入库与追溯链路的对外 DTO（FZ-3 冻结，Gate 0 签字后谁都不改）。

冻结规则同 ``models/staging.py``：字段名与类型一经发布，下游只允许**加字段**
（可选、带默认值），要改走 ``CONTRACT-CHANGELOG``。前端已按这些字段实现
（``pages/import.js`` 的报告页、``pages/raw.js`` 的浏览与追溯），字段名不可漂移。

两处**有意为之的不同构**（写进注释，防止后人"修整齐"）：

* ``IngestReportDTO.monthly`` 的键是归档表名 ``raw_2026_06``（带前缀）；
* ``RawMonthDTO.month`` 是月份键 ``2026_06``（不带前缀）。
  前端 ``raw.js`` 用 ``month.slice(5)`` 拼 ``raw_${ym}`` 查表，两边不能互换。

导入方向：本模块 import ``models.staging``（``TraceDTO.batch``），
``models.staging`` **不** import 本模块 —— ``BatchDetailDTO.report`` 的前向引用
由 ``models/__init__.py`` 在包装载时补齐（见那里的注释）。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from account_dashboard.models.enums import Channel, Direction
from account_dashboard.models.staging import BatchDTO

_RAW_TRUNCATE = 64


class SkippedRowDTO(BaseModel):
    """被跳过一行的留痕（D-6：不可解析行的报告是唯一留痕，文件会被删）。"""

    row_no: int
    reason: str  # "AMOUNT_PARSE" / "TIME_PARSE" / "DIRECTION_UNKNOWN" / "DUP"
    field: str | None = None
    raw: str | None = None  # 原始值，截断 64 字符


class IngestReportDTO(BaseModel):
    """导入报告四数字（前端报告页的唯一数据源，EX-22：不用预检数字替代）。"""

    batch_id: str
    total: int
    inserted: int
    skipped_dup: int
    skipped_invalid: int = 0
    pending: int
    monthly: dict[str, int] = Field(default_factory=dict)  # {"raw_2026_06": 101}
    files_deleted: bool = True
    cleanup_pending: bool = False
    cleanup_id: str | None = None
    finished_at: str  # DB 列叫 committed_at，DTO 字段改名（前端已按 finished_at）

    @classmethod
    def from_stored(
        cls,
        report_json: str | None,
        *,
        pending_delete_flag: int = 1,
        committed_at: str | None = None,
    ) -> IngestReportDTO | None:
        """从 ``staging_batch.report_json`` 还原报告（confirm 响应与 report 端点共用口径）。

        ``files_deleted`` / ``cleanup_pending`` / ``cleanup_id`` **不落库**：
        唯一事实源是 ``pending_delete_flag``（B 线维护：删成功清零、失败留 1 并
        入待清理队列）。confirm 响应里的同名字段取自 sink 的即时返回；这里按
        当前旗标推导，因此 B 线补删/重试成功后报告会自己变新，不会留过期副本。
        """
        if not report_json:
            return None
        data = json.loads(report_json)
        files_deleted = pending_delete_flag == 0
        return cls(
            batch_id=str(data.get("batch_id", "")),
            total=int(data.get("total", 0)),
            inserted=int(data.get("inserted", 0)),
            skipped_dup=int(data.get("skipped_dup", 0)),
            skipped_invalid=int(data.get("skipped_invalid", 0)),
            pending=int(data.get("pending", 0)),
            monthly={str(key): int(value) for key, value in (data.get("monthly") or {}).items()},
            files_deleted=files_deleted,
            cleanup_pending=not files_deleted,
            cleanup_id=None,
            finished_at=committed_at or str(data.get("finished_at", "")),
        )


class IngestReportDetailDTO(IngestReportDTO):
    """``report?include_skipped=true`` 时才填 ``skipped``（D-6 的明细）。"""

    skipped: list[SkippedRowDTO] = Field(default_factory=list)


class RawMonthDTO(BaseModel):
    month: str  # "2026_06"，无 raw_ 前缀（与 monthly 的键有意不同构）
    count: int


class RawRecordDTO(BaseModel):
    """原始库一行的只读投影（列表不带 ``raw_payload``，5 万行时 JSON 会爆）。"""

    id: int
    batch_id: str
    row_no: int
    occurred_at: str
    amount_cents: int
    direction: Direction
    counterparty: str | None = None
    item: str | None = None
    txn_type: str | None = None
    payment_method: str | None = None
    platform_category: str | None = None
    platform_status: str | None = None
    channel: Channel
    fp: str | None = None
    imported_at: str


class RawRecordDetailDTO(RawRecordDTO):
    raw_payload: dict[str, Any]


class TraceTransactionDTO(BaseModel):
    """追溯里的主数据块（C4 完整 ``TransactionDTO`` 的子集，扩展时保留这些字段名）。"""

    id: str
    batch_id: str
    row_no: int
    occurred_at: str
    amount_cents: int
    direction: Direction
    counterparty: str | None = None
    item: str | None = None
    channel: Channel
    status: str


class TraceDTO(BaseModel):
    """批次追溯四块（C3 基线原为三块，补 ``transaction`` 后前端已按四块实现）。"""

    transaction: TraceTransactionDTO
    batch: BatchDTO | None = None
    raw_record: RawRecordDTO | None = None
    mapping_snapshot: dict[str, Any] | None = None


class CleanupItemDTO(BaseModel):
    id: str
    batch_id: str | None = None
    file_path: str
    file_name: str | None = None  # 由 LEFT JOIN staging_batch 派生，DDL 无此列
    reason: str
    attempts: int
    last_error: str | None = None
    status: str  # pending / done / abandoned
    created_at: str
    updated_at: str


class OrphanCleanupDTO(BaseModel):
    removed: list[str] = Field(default_factory=list)
    failed: list[dict[str, str]] = Field(default_factory=list)  # [{"name":..,"code":"E4003"}]


def truncate_raw(value: str | None) -> str | None:
    """``SkippedRowDTO.raw`` 的截断口径（64 字符，超长加省略标记）。"""
    if value is None:
        return None
    text = str(value)
    if len(text) <= _RAW_TRUNCATE:
        return text
    return text[:_RAW_TRUNCATE] + "…"


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
    "truncate_raw",
]
