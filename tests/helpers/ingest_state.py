"""C3 的 SQL 夹具（Gate 0）：不 import 任何 A/B 线模块，纯裸 SQL 造状态。

B 线（删除意图 / 自愈 / 追溯）的全部用例靠它在**完全没有 ``IngestService``**
的情况下预置「``ingested`` + ``flag=1`` + raw 行 + transaction 行」；合稿时
A 线也用它预置"重复入库"场景。因此这里刻意不依赖两条线的任何实现，
只依赖 Gate 0 的 ``infra/raw_naming``（表名唯一收口）。

动态建的 ``raw_YYYY_MM`` 与 ``V001__init.sql`` 的模板逐列一致（16 列 + 2 索引）——
A 线合稿后两侧建表形状相同，B 线的查询才不会错位。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from account_dashboard.infra.clock import now_iso
from account_dashboard.infra.raw_naming import table_name

# 与 V001__init.sql 的 raw 模板一致：16 列 + 2 索引（K1）
_RAW_TABLE_DDL = """
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
_RAW_TIME_IDX = "CREATE INDEX IF NOT EXISTS {idx} ON {table}(occurred_at DESC)"
_RAW_BATCH_IDX = "CREATE INDEX IF NOT EXISTS {idx} ON {table}(batch_id, row_no)"

_DIRECTIONS = ("income", "expense", "neutral")
_CHANNELS = ("wechat", "alipay", "bank", "other")

# raw 与 transaction 双写时必须逐项一致的 11 个字段（I8 的追溯口径）
_TRACE_FIELDS = (
    "batch_id",
    "row_no",
    "occurred_at",
    "amount_cents",
    "direction",
    "counterparty",
    "item",
    "txn_type",
    "payment_method",
    "channel",
    "fp",
)


def make_ingested_batch(
    conn: sqlite3.Connection,
    *,
    batch_id: str,
    stored_name: str,
    file_name: str,
    pending_delete_flag: int = 1,
    report_json: str | None = None,
    mapping_snapshot: str | None = None,
) -> None:
    """造一个「已入库」批次（B 线用例的起点状态）。

    ``pending_delete_flag=1`` 表示删除意图待执行（文件应在缓冲区里），
    ``=0`` 配合"文件仍存在"即对账第 ③ 步的不一致场景。
    ``mapping_snapshot`` 是相对 Gate 0 签名单的**新增可选参数**（additive）：
    追溯四块断言需要它，A 线调用时不传即不影响。
    """
    stamp = now_iso()
    conn.execute(
        "INSERT INTO staging_batch(id, file_name, stored_name, file_size, status, "
        "total_rows, report_json, mapping_snapshot, pending_delete_flag, "
        "committed_at, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            batch_id,
            file_name,
            stored_name,
            2048,
            "ingested",
            0,
            report_json,
            mapping_snapshot,
            pending_delete_flag,
            stamp,
            stamp,
            stamp,
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
    """在 ``raw_YYYY_MM`` 里造 ``rows`` 行（表不存在则按 V001 模板建）。

    月份键形如 ``"2026_06"``；行内容由 :func:`_business_values` 确定性生成，
    与 :func:`seed_transactions` 共用同一发生器 —— 追溯用例因此能逐字段比对。
    """
    table = table_name(month)
    conn.execute(_RAW_TABLE_DDL.format(table=table))
    conn.execute(_RAW_TIME_IDX.format(idx=f"idx_{table}_time", table=table))
    conn.execute(_RAW_BATCH_IDX.format(idx=f"idx_{table}_batch", table=table))
    stamp = now_iso()
    payloads: list[tuple[Any, ...]] = []
    for offset in range(rows):
        values = _business_values(start_row_no + offset, batch_id)
        payloads.append(
            (
                values["batch_id"],
                values["row_no"],
                values["occurred_at"],
                values["amount_cents"],
                values["direction"],
                values["counterparty"],
                values["item"],
                values["txn_type"],
                values["payment_method"],
                None,
                None,
                values["channel"],
                values["fp"],
                json.dumps(_original_row(values), ensure_ascii=False, sort_keys=True),
                stamp,
            )
        )
    conn.executemany(
        f"INSERT INTO {table}(batch_id, row_no, occurred_at, amount_cents, direction, "
        "counterparty, item, txn_type, payment_method, platform_category, platform_status, "
        "channel, fp, raw_payload, imported_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        payloads,
    )


def seed_transactions(conn: sqlite3.Connection, batch_id: str, rows: int) -> None:
    """造 ``rows`` 条主数据（``status='pending'``、``category_*`` 为 NULL —— C3 边界自证）。

    行号与 :func:`seed_raw_rows` 的决定论发生器一致，因此同一 ``batch_id``
    下 ``row_no`` 相同的两行在 11 个业务字段上逐项相等。
    """
    stamp = now_iso()
    payloads: list[tuple[Any, ...]] = []
    for offset in range(rows):
        values = _business_values(1 + offset, batch_id)
        payloads.append(
            (
                f"T-{batch_id[:8]}-{values['row_no']:04d}",
                values["occurred_at"],
                values["amount_cents"],
                values["direction"],
                values["counterparty"],
                values["item"],
                values["txn_type"],
                values["payment_method"],
                values["channel"],
                "pending",
                values["batch_id"],
                values["row_no"],
                values["fp"],
                stamp,
                stamp,
            )
        )
    conn.executemany(
        'INSERT INTO "transaction"(id, occurred_at, amount_cents, direction, counterparty, '
        "item, txn_type, payment_method, channel, status, batch_id, row_no, fp, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        payloads,
    )


def trace_field_names() -> tuple[str, ...]:
    """raw 与 transaction 双写口径的 11 个字段名（追溯比对的唯一清单）。"""
    return _TRACE_FIELDS


def _business_values(row_no: int, batch_id: str) -> dict[str, Any]:
    """同一 ``row_no`` 永远得到同一组值 —— raw 与 transaction 因此可逐字段互证。"""
    occurred_at = f"2026-06-{1 + (row_no % 28):02d}T12:00:00"
    amount_cents = 1000 + row_no * 137
    counterparty = f"对方-{row_no:04d}"
    item = f"商品-{row_no:04d}"
    txn_type = "消费"
    payment_method = "微信支付"
    channel = _CHANNELS[row_no % len(_CHANNELS)]
    direction = _DIRECTIONS[row_no % len(_DIRECTIONS)]
    fp = hashlib.sha1(
        f"{occurred_at}|{amount_cents}|{direction}|{counterparty}".encode()
    ).hexdigest()[:16]
    return {
        "batch_id": batch_id,
        "row_no": row_no,
        "occurred_at": occurred_at,
        "amount_cents": amount_cents,
        "direction": direction,
        "counterparty": counterparty,
        "item": item,
        "txn_type": txn_type,
        "payment_method": payment_method,
        "channel": channel,
        "fp": fp,
    }


def _original_row(values: dict[str, Any]) -> dict[str, Any]:
    """raw_payload 的"整行原貌"：保留平台列名与字符串形态（I7），不做单位换算。"""
    return {
        "交易时间": values["occurred_at"],
        "金额": f"{values['amount_cents'] / 100:.2f}",
        "收/支": values["direction"],
        "交易对方": values["counterparty"],
        "商品说明": values["item"],
        "交易类型": values["txn_type"],
        "支付方式": values["payment_method"],
    }
