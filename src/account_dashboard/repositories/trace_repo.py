"""批次追溯仓储（C3-B §4.6；K6 / K7 / I8）。

一条流水的完整来处 = 主数据 → 来源批次 → raw 原始行 → 入库时的映射快照。
本仓储只**读**（K6：``transaction`` 表归 A 线写，B 线只经这里读），
``mapping_snapshot`` 直接读 ``staging_batch`` 字段（I11 只写一次，全程只读，
本线不得写 —— D-5 的守卫在 ``staging_repo`` 那侧）。

D-6 的后果：``skipped_invalid`` 的行不写 raw 也不写 ``transaction``，
所以它们不可能出现在追溯链里 —— 追溯缺块的 WARN 只能由"数据损坏"触发，
这是判断 WARN 是否真缺陷的分界线。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from account_dashboard.infra.errors import InfraError
from account_dashboard.infra.raw_naming import month_key
from account_dashboard.repositories.raw_read_repo import RawReadRepo, RawRecordRow
from account_dashboard.repositories.staging_repo import BatchRow, StagingRepo

# 主数据的追溯字段（TraceTransactionDTO 的形状，C4 扩展时保留这些字段名）
_TXN_COLUMNS = (
    "id, batch_id, row_no, occurred_at, amount_cents, direction, counterparty, item, "
    "txn_type, payment_method, channel, fp, status"
)


@dataclass(frozen=True, slots=True)
class TraceTransactionRow:
    id: str
    batch_id: str
    row_no: int
    occurred_at: str
    amount_cents: int
    direction: str
    counterparty: str | None
    item: str | None
    txn_type: str | None
    payment_method: str | None
    channel: str
    fp: str | None
    status: str


@dataclass(frozen=True, slots=True)
class TraceParts:
    """追溯的四块原料；``batch`` / ``raw_record`` / ``mapping_snapshot`` 允许为 None
    （数据分叉信号，由 service 记 WARN 并以 null 块返回，不一律报错）。"""

    transaction: TraceTransactionRow
    batch: BatchRow | None = None
    raw_record: RawRecordRow | None = None
    mapping_snapshot: dict[str, Any] | None = None


class TraceRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._staging = StagingRepo(conn)
        self._raw = RawReadRepo(conn)

    def trace(self, transaction_id: str) -> TraceParts | None:
        """按流水 id 取四块；流水不存在返回 ``None``（路由映射 404 ``E2010``）。"""
        row = self._conn.execute(
            f'SELECT {_TXN_COLUMNS} FROM "transaction" WHERE id = ?',  # noqa: S608
            (transaction_id,),
        ).fetchone()
        if row is None:
            return None
        transaction = _to_transaction(row)
        batch = self._staging.get(transaction.batch_id)
        raw_record = self._raw_for(transaction)
        return TraceParts(
            transaction=transaction,
            batch=batch,
            raw_record=raw_record,
            mapping_snapshot=_parse_snapshot(batch.mapping_snapshot) if batch else None,
        )

    # ── 内部 ──────────────────────────────────────────────────
    def _raw_for(self, transaction: TraceTransactionRow) -> RawRecordRow | None:
        """月份由 ``occurred_at`` 推出（K8：不信任文件名）；推不出或表不在 → None。"""
        try:
            month = month_key(transaction.occurred_at)
        except InfraError:
            return None
        return self._raw.find_by_batch_row(month, transaction.batch_id, transaction.row_no)


def _to_transaction(row: sqlite3.Row) -> TraceTransactionRow:
    return TraceTransactionRow(
        id=str(row["id"]),
        batch_id=str(row["batch_id"]),
        row_no=int(row["row_no"]),
        occurred_at=str(row["occurred_at"]),
        amount_cents=int(row["amount_cents"]),
        direction=str(row["direction"]),
        counterparty=row["counterparty"],
        item=row["item"],
        txn_type=row["txn_type"],
        payment_method=row["payment_method"],
        channel=str(row["channel"]),
        fp=row["fp"],
        status=str(row["status"]),
    )


def _parse_snapshot(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
