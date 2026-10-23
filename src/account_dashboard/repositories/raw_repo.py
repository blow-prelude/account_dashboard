"""原始库按月分表（SDD §5.2 / §4.4.3，I7：只增不改）。

``RawTableManager`` 是全项目唯一建 ``raw_YYYY_MM`` 表、唯一往里写行的地方。
两条硬约束：

1. **只增不改** —— 故意不提供 ``update_rows`` / ``delete_rows``（用
   ``hasattr`` 断言进 CI，见 ``tests/integration/test_write_path_gates.py``）。
   审计链的终点不许被改写；要修正数据请走 C4 的重算，不要动原始行。
2. **表名只走 ``infra/raw_naming.table_name``** —— 表名无法参数化，这是全项目
   唯一的 SQL 标识符拼接处，非法月份直接 ``E3002``，**不执行任何 SQL**。

建表时机：只建"有行要写"的月份。样例无 2025-12 数据 → ``raw_2025_12`` 不存在；
``accepted`` 为空时连一个表都不建（EX-09 的全重复批次仍然正常归档）。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import islice
from typing import Any

from account_dashboard.infra.errors import RawTableError
from account_dashboard.infra.raw_naming import RAW_MONTH_RE, table_name
from account_dashboard.models.enums import Direction

# 与 V001__init.sql 的模板注释、tests/helpers/ingest_state.py 逐列一致（16 列）。
# {table} 占位符只接受 raw_naming.table_name() 的返回值（已过正则白名单）。
RAW_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id     TEXT    NOT NULL,
    row_no       INTEGER NOT NULL,
    occurred_at  TEXT    NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    direction    TEXT    NOT NULL CHECK (direction IN ('income','expense','neutral')),
    counterparty TEXT,
    item         TEXT,
    txn_type     TEXT,
    payment_method TEXT,
    platform_category TEXT,
    platform_status   TEXT,
    channel      TEXT    NOT NULL,
    fp           TEXT,
    raw_payload  TEXT    NOT NULL,
    imported_at  TEXT    NOT NULL
)
"""
RAW_TIME_IDX = "CREATE INDEX IF NOT EXISTS idx_{table}_time ON {table}(occurred_at DESC)"
RAW_BATCH_IDX = "CREATE INDEX IF NOT EXISTS idx_{table}_batch ON {table}(batch_id, row_no)"

# 与 FP_QUERY_CHUNK 同源的保守值：SQLite 变量上限 999 的同类考虑，且压住 5 万行峰值内存
RAW_WRITE_CHUNK = 500

_INSERT_SQL = (
    "INSERT INTO {table}(batch_id, row_no, occurred_at, amount_cents, direction, "
    "counterparty, item, txn_type, payment_method, platform_category, platform_status, "
    "channel, fp, raw_payload, imported_at) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


@dataclass(frozen=True, slots=True)
class RawRow:
    """一行待写入原始库的值对象（``raw_payload`` 由调用方用 :func:`dump_raw_payload` 备好）。"""

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
    channel: str = "other"
    fp: str | None = None
    raw_payload: str = "{}"
    imported_at: str = ""


def dump_raw_payload(payload: dict[str, Any]) -> str:
    """整行原貌的落库形态（I7）：保留原始字符串，不做任何单位换算。

    ``sort_keys=True`` 保证同一行两次入库字节一致（可重放校验）；
    ``ensure_ascii=False`` 保证 ``已退款¥26.40`` 这类变体原样可读。
    """
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


class RawTableManager:
    """动态分表写入器。故意不提供 update / delete（I7 靠"没有这个方法"强制）。"""

    def ensure_table(self, conn: sqlite3.Connection, month: str) -> None:
        """按需建表 + 2 个索引（DDL 参与事务回滚，故障注入后无残留半成品表）。"""
        name = table_name(month)  # 非法月份在此抛 E3002，后面一句 SQL 都不执行
        conn.execute(RAW_TABLE_DDL.format(table=name))
        conn.execute(RAW_TIME_IDX.format(table=name))
        conn.execute(RAW_BATCH_IDX.format(table=name))

    def write_rows(
        self,
        conn: sqlite3.Connection,
        month: str,
        rows: Sequence[RawRow] | Iterable[RawRow],
    ) -> int:
        """把一批行写进 ``raw_{month}``；分批 ``executemany``（500/批），返回写入数。"""
        name = table_name(month)
        sql = _INSERT_SQL.format(table=name)
        iterator = iter(rows)
        written = 0
        while True:
            chunk = list(islice(iterator, RAW_WRITE_CHUNK))
            if not chunk:
                break
            conn.executemany(sql, [_params(row) for row in chunk])
            written += len(chunk)
        return written

    def existing_tables(self, conn: sqlite3.Connection) -> list[str]:
        """当前库里的 raw 分表名（升序；只认正则白名单内的，防历史脏表混入）。"""
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'raw_%' "
            "ORDER BY name"
        ).fetchall()
        return [str(row["name"]) for row in rows if _is_raw_table(str(row["name"]))]

    def count_by_batch(self, conn: sqlite3.Connection, batch_id: str) -> int:
        """遍历分表求和 —— 入库后自检用（应等于报告的 ``inserted``）。"""
        total = 0
        for name in self.existing_tables(conn):
            total += int(
                conn.execute(f"SELECT COUNT(*) FROM {name} WHERE batch_id = ?", (batch_id,))
                .fetchone()[0]
            )
        return total


def _params(row: RawRow) -> tuple[Any, ...]:
    return (
        row.batch_id,
        row.row_no,
        row.occurred_at,
        row.amount_cents,
        str(row.direction),
        row.counterparty,
        row.item,
        row.txn_type,
        row.payment_method,
        row.platform_category,
        row.platform_status,
        row.channel,
        row.fp,
        row.raw_payload,
        row.imported_at,
    )


def _is_raw_table(name: str) -> bool:
    return name.startswith("raw_") and bool(RAW_MONTH_RE.match(name[len("raw_") :]))


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """表存在性检查（不执行任何写操作；B 线「缺月返回空」也走这条）。"""
    if not _is_raw_table(table):
        raise RawTableError(
            "原始库表名格式不合法",
            detail={"table": table},
        )
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None and int(row["n"]) > 0


__all__ = [
    "RAW_BATCH_IDX",
    "RAW_TABLE_DDL",
    "RAW_TIME_IDX",
    "RAW_WRITE_CHUNK",
    "RawRow",
    "RawTableManager",
    "dump_raw_payload",
    "table_exists",
]
