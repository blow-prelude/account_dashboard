"""C3 的 SQL 夹具（Gate 0，双方只读）。

存在的意义是 **B 线的独立性**：B 线（删除意图/自愈/追溯）要能在完全没有
``IngestService`` 的情况下造出「``ingested`` + ``flag=1`` + raw 行 + transaction 行」
的状态。因此这里全是裸 SQL，**不 import 任何 A/B 线模块** —— raw 表的 DDL 与
``repositories/raw_repo.py`` 的模板逐列一致，是故意的重复（改 raw 列定义时两边
都要改，有 ``test_raw_payload_fidelity`` 与 B 线用例兜底）。

严禁在这里放业务逻辑：夹具只负责「把数据库摆成某个状态」。
"""

from __future__ import annotations

import sqlite3
from typing import Any

# 与 repositories/raw_repo.py 的 RAW_TABLE_DDL 逐列一致（16 列 + 2 索引）
_RAW_DDL = """
CREATE TABLE IF NOT EXISTS raw_{month} (
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

_TXN_COLUMNS = (
    "id, occurred_at, amount_cents, direction, category_l1, category_l2, counterparty, "
    "item, txn_type, payment_method, channel, status, note, hint_l1, hint_l2, batch_id, "
    "row_no, fp, override_reason, override_at, created_at, updated_at"
)


def make_ingested_batch(
    conn: sqlite3.Connection,
    *,
    batch_id: str,
    stored_name: str,
    file_name: str,
    pending_delete_flag: int = 1,
    report_json: str | None = None,
) -> None:
    """造一个 ``ingested`` 批次（可选带 ``report_json`` 与删除意图旗标）。"""
    conn.execute(
        "INSERT INTO staging_batch(id, file_name, stored_name, file_size, channel, status, "
        "total_rows, new_count, dup_count, pending_count, encoding, adapter, header_row_no, "
        "mapped_fields, mapping_snapshot, parse_meta, report_json, pending_delete_flag, "
        "deleted_at, fail_reason, ingest_started_at, committed_at, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            batch_id,
            file_name,
            stored_name,
            1024,
            "alipay",
            "ingested",
            0,
            0,
            0,
            0,
            "gb18030",
            "alipay_csv",
            23,
            None,
            None,
            None,
            report_json,
            pending_delete_flag,
            None,
            None,
            "2026-10-22T10:00:00",
            "2026-10-22T10:00:01",
            "2026-10-22T09:59:00",
            "2026-10-22T10:00:01",
        ),
    )


def seed_raw_rows(
    conn: sqlite3.Connection,
    month: str,
    batch_id: str,
    rows: int,
    *,
    start_row_no: int = 1,
) -> None:
    """在 ``raw_{month}`` 里造 ``rows`` 行（行号从 ``start_row_no`` 起，按序递增）。"""
    conn.execute(_RAW_DDL.format(month=month))
    payload: list[tuple[Any, ...]] = []
    for index in range(rows):
        row_no = start_row_no + index
        payload.append(
            (
                batch_id,
                row_no,
                f"{month.replace('_', '-')}-01T10:00:00",
                1000 + row_no,
                "expense",
                f"对方{row_no}",
                f"商品{row_no}",
                None,
                None,
                None,
                None,
                "alipay",
                f"fp-{batch_id}-{row_no}",
                '{"交易时间": "x"}',
                "2026-10-22T10:00:01",
            )
        )
    conn.executemany(
        f"INSERT INTO raw_{month}(batch_id, row_no, occurred_at, amount_cents, direction, "
        "counterparty, item, txn_type, payment_method, platform_category, platform_status, "
        "channel, fp, raw_payload, imported_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        payload,
    )


def seed_transactions(
    conn: sqlite3.Connection,
    batch_id: str,
    rows: int,
    *,
    start_row_no: int = 1,
) -> None:
    """造 ``rows`` 行 ``transaction``（``status`` 恒 ``pending``，与 C3 写入口径一致）。"""
    payload: list[tuple[Any, ...]] = []
    for index in range(rows):
        row_no = start_row_no + index
        payload.append(
            (
                f"txn-{batch_id}-{row_no}",
                f"2026-10-22T10:00:{row_no % 60:02d}",
                1000 + row_no,
                "expense",
                None,
                None,
                f"对方{row_no}",
                f"商品{row_no}",
                None,
                None,
                "alipay",
                "pending",
                None,
                None,
                None,
                batch_id,
                row_no,
                f"fp-{batch_id}-{row_no}",
                None,
                None,
                "2026-10-22T10:00:01",
                "2026-10-22T10:00:01",
            )
        )
    placeholders = ", ".join("?" for _ in _TXN_COLUMNS.split(", "))
    conn.executemany(
        f'INSERT INTO "transaction"({_TXN_COLUMNS}) VALUES ({placeholders})',
        payload,
    )


def raw_row_count(conn: sqlite3.Connection, month: str) -> int:
    """``raw_{month}`` 的行数；表不存在返回 0（B 线「缺月是常态」的同一口径）。"""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name = ?",
        (f"raw_{month}",),
    ).fetchone()
    if row is None or int(row["n"]) == 0:
        return 0
    return int(conn.execute(f"SELECT COUNT(*) AS n FROM raw_{month}").fetchone()["n"])


def all_raw_tables(conn: sqlite3.Connection) -> list[str]:
    """当前库里的 raw 分表名（升序）。"""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'raw_%' ORDER BY name"
    ).fetchall()
    return [str(row["name"]) for row in rows]


__all__ = [
    "all_raw_tables",
    "make_ingested_batch",
    "raw_row_count",
    "seed_raw_rows",
    "seed_transactions",
]
