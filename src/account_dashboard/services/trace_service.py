"""批次追溯（C3-B §4.6；I8：任一条主数据都能回到原始行与当时的映射快照）。

缺块的处理**不一律报错**（与 C3 基线的"三者缺一 → E2010"按 D-6 修正）：

* 流水不存在 → 路由返回 404 ``E2010``；
* 流水存在但 ``batch`` / ``raw_record`` 缺失 → **200 + 该块为 null** + WARN 日志。
  这是数据分叉信号，属严重缺陷，应暴露在日志而不是给用户一个 500。

WARN 只能由"数据损坏"触发：``skipped_invalid`` 的行不写 raw 也不写
``transaction``（D-6），正常跳过不可能出现在追溯链里。
"""

from __future__ import annotations

from account_dashboard.infra.logger import get_logger
from account_dashboard.models.enums import BatchStatus, Channel
from account_dashboard.models.ingest import TraceDTO, TraceTransactionDTO
from account_dashboard.models.staging import BatchDTO
from account_dashboard.repositories.raw_read_repo import to_record_dto
from account_dashboard.repositories.staging_repo import BatchRow
from account_dashboard.repositories.trace_repo import TraceRepo
from account_dashboard.repositories.unit_of_work import UnitOfWork

_logger = get_logger("trace")


class TraceService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow
        self._repo = TraceRepo(uow.conn)

    def trace(self, transaction_id: str) -> TraceDTO | None:
        """流水不存在返回 ``None``（路由映射 404 ``E2010``）。"""
        parts = self._repo.trace(transaction_id)
        if parts is None:
            return None
        if parts.batch is None or parts.raw_record is None:
            _logger.warning(
                "追溯缺块（数据分叉信号）：流水 %s → batch=%s raw_record=%s",
                transaction_id,
                "缺失" if parts.batch is None else "在",
                "缺失" if parts.raw_record is None else "在",
            )
        return TraceDTO(
            transaction=TraceTransactionDTO(
                id=parts.transaction.id,
                batch_id=parts.transaction.batch_id,
                row_no=parts.transaction.row_no,
                occurred_at=parts.transaction.occurred_at,
                amount_cents=parts.transaction.amount_cents,
                direction=parts.transaction.direction,
                counterparty=parts.transaction.counterparty,
                item=parts.transaction.item,
                txn_type=parts.transaction.txn_type,
                payment_method=parts.transaction.payment_method,
                channel=parts.transaction.channel,
                fp=parts.transaction.fp,
                status=parts.transaction.status,
            ),
            batch=_to_batch_dto(parts.batch) if parts.batch is not None else None,
            raw_record=to_record_dto(parts.raw_record) if parts.raw_record is not None else None,
            mapping_snapshot=parts.mapping_snapshot,
        )


def _to_batch_dto(row: BatchRow) -> BatchDTO:
    """``BatchRow`` → FZ-2 冻结的 ``BatchDTO``（字段名不可漂移）。"""
    return BatchDTO(
        id=row.id,
        file_name=row.file_name,
        file_size=row.file_size,
        channel=Channel(row.channel),
        status=BatchStatus(row.status),
        total_rows=row.total_rows,
        new_count=row.new_count,
        dup_count=row.dup_count,
        pending_count=row.pending_count,
        encoding=row.encoding,
        adapter=row.adapter,
        fail_reason=row.fail_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


__all__ = ["TraceService"]
