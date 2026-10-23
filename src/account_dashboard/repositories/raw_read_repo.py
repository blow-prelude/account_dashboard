"""原始库只读仓储（C3-B §4.5；K1 / K2 / K8）。

三处口径必须与 A 线一致，否则前端查到空表或数字对不上：

* 月份键 ``"2026_06"``（**无** ``raw_`` 前缀）—— 前端 ``raw.js`` 用
  ``x.month.slice(5)`` 取月份、拼 ``raw_${ym}`` 查表；
* 表名一律经 ``infra/raw_naming.table_name()``（全项目唯一拼接处）；
* ``count`` 就是 ``SELECT COUNT(*) FROM raw_YYYY_MM``，与 ``IngestReportDTO.monthly``
  逐月相等。

两条纪律：列表查询**显式列名**（raw 表是动态建的，``SELECT *`` 会让列序漂移
把 DTO 静默错位）；表存在性先查 ``sqlite_master``，**不依赖异常**（缺月是常态，
按月归档视图里没有某个月不是错误）。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from account_dashboard.infra.raw_naming import month_of_table, table_name
from account_dashboard.models.ingest import RawRecordDTO

# raw 表的 16 列（K1：与 V001__init.sql 模板逐列一致；raw_payload 只在详情里查）
_RAW_COLUMNS = (
    "id, batch_id, row_no, occurred_at, amount_cents, direction, counterparty, item, "
    "txn_type, payment_method, platform_category, platform_status, channel, fp, imported_at"
)
_RAW_COLUMNS_WITH_PAYLOAD = f"{_RAW_COLUMNS}, raw_payload"


@dataclass(frozen=True, slots=True)
class RawRecordRow:
    id: int
    batch_id: str
    row_no: int
    occurred_at: str
    amount_cents: int
    direction: str
    counterparty: str | None
    item: str | None
    txn_type: str | None
    payment_method: str | None
    platform_category: str | None
    platform_status: str | None
    channel: str
    fp: str | None
    imported_at: str
    # 仅详情查询填充；列表不带（5 万行时 JSON 会爆）
    raw_payload: str | None = None


class RawReadRepo:
    """只读：没有任何写方法（I7 靠"没有这个方法"强制，与 A 线的 ``RawTableManager`` 对称）。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── 月份枚举 ───────────────────────────────────────────────
    def existing_months(self) -> list[str]:
        """库里实际存在的 raw 月份（降序）；无数据的月份不会出现。"""
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'raw_%'"
        ).fetchall()
        months = [m for m in (month_of_table(str(row["name"])) for row in rows) if m is not None]
        return sorted(months, reverse=True)

    def table_exists(self, month: str) -> bool:
        name = table_name(month)  # 非法月份 → E3002；调用方（路由）已先做 E1008 校验
        row = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        return row is not None

    def count(self, month: str) -> int:
        table = table_name(month)
        row = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
        return int(row[0]) if row is not None else 0

    # ── 分页 / 详情 ────────────────────────────────────────────
    def page(
        self, month: str, page: int, page_size: int
    ) -> tuple[list[RawRecordRow], int]:
        """按 ``occurred_at DESC`` 分页；月份表不存在 → 空列表 + total=0（不是错误）。"""
        if not self.table_exists(month):
            return [], 0
        table = table_name(month)
        total = self.count(month)
        rows = self._conn.execute(
            f"SELECT {_RAW_COLUMNS} FROM {table} "  # noqa: S608
            "ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?",
            (page_size, (page - 1) * page_size),
        ).fetchall()
        return [_to_record(row, with_payload=False) for row in rows], total

    def find_by_batch_row(self, month: str, batch_id: str, row_no: int) -> RawRecordRow | None:
        """追溯主键 ``(batch_id, row_no)`` 查询（K7；索引 ``idx_raw_*_batch`` 由 A 线建）。"""
        if not self.table_exists(month):
            return None
        table = table_name(month)
        row = self._conn.execute(
            f"SELECT {_RAW_COLUMNS} FROM {table} WHERE batch_id = ? AND row_no = ?",  # noqa: S608
            (batch_id, row_no),
        ).fetchone()
        return _to_record(row, with_payload=False) if row is not None else None

    def detail(self, record_id: int) -> RawRecordRow | None:
        """按 id 查详情（带 ``raw_payload``）；id 只在其所属月份的分表里唯一，逐表找。"""
        for month in self.existing_months():
            table = table_name(month)
            row = self._conn.execute(
                f"SELECT {_RAW_COLUMNS_WITH_PAYLOAD} FROM {table} WHERE id = ?",  # noqa: S608
                (record_id,),
            ).fetchone()
            if row is not None:
                return _to_record(row, with_payload=True)
        return None


def _to_record(row: sqlite3.Row, *, with_payload: bool) -> RawRecordRow:
    # 列表查询不选 raw_payload 列，with_payload=False 时不能去取（列序漂移的防御）
    payload = row["raw_payload"] if with_payload else None
    return RawRecordRow(
        id=int(row["id"]),
        batch_id=str(row["batch_id"]),
        row_no=int(row["row_no"]),
        occurred_at=str(row["occurred_at"]),
        amount_cents=int(row["amount_cents"]),
        direction=str(row["direction"]),
        counterparty=row["counterparty"],
        item=row["item"],
        txn_type=row["txn_type"],
        payment_method=row["payment_method"],
        platform_category=row["platform_category"],
        platform_status=row["platform_status"],
        channel=str(row["channel"]),
        fp=row["fp"],
        imported_at=str(row["imported_at"]),
        raw_payload=str(payload) if with_payload and payload is not None else None,
    )


def to_record_dto(row: RawRecordRow) -> RawRecordDTO:
    """``RawRecordRow`` → FZ-3 冻结的 ``RawRecordDTO``（列表与追溯共用，字段名不可漂移）。"""
    return RawRecordDTO(
        id=row.id,
        batch_id=row.batch_id,
        row_no=row.row_no,
        occurred_at=row.occurred_at,
        amount_cents=row.amount_cents,
        direction=row.direction,
        counterparty=row.counterparty,
        item=row.item,
        txn_type=row.txn_type,
        payment_method=row.payment_method,
        platform_category=row.platform_category,
        platform_status=row.platform_status,
        channel=row.channel,
        fp=row.fp,
        imported_at=row.imported_at,
    )
