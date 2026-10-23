"""RawTableManager（U-RT-01/02/03，C3-A §4.3 / §6.1）。

三条硬断言：

* **无改/删方法** —— I7 靠"没有这个方法"强制，``hasattr`` 进 CI；
* **非法月份不执行任何 SQL** —— 表名拼接是全项目唯一的标识符注入面；
* **只建有数据的月份** —— 无数据月份不建表（EX-09 的全重复批次连一个表都不建）。
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from account_dashboard.api.errors import TransactionError
from account_dashboard.infra.raw_naming import month_key, table_name
from account_dashboard.models.enums import Direction
from account_dashboard.repositories.raw_repo import (
    RawRow,
    RawTableManager,
    dump_raw_payload,
    table_exists,
)

MONTHS = ("2026_06", "2026_07", "2026_08")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _row(row_no: int, *, month: str = "2026_06") -> RawRow:
    return RawRow(
        batch_id="batch-1",
        row_no=row_no,
        occurred_at=f"{month.replace('_', '-')}-01T10:00:00",
        amount_cents=1234,
        direction=Direction.EXPENSE,
        counterparty="某某便利店",
        item="咖啡饮品",
        channel="alipay",
        fp=f"fp-{row_no}",
        raw_payload=dump_raw_payload({"金额": "12.34", "交易状态": "退款成功"}),
        imported_at="2026-10-22T10:00:00",
    )


def _raw_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'raw_%' ORDER BY name"
    ).fetchall()
    return [str(row["name"]) for row in rows]


# ── U-RT-01：只增不改 ──────────────────────────────────────────
def test_manager_has_no_update_or_delete_methods() -> None:
    manager = RawTableManager()
    for name in ("update_rows", "delete_rows", "update", "delete", "delete_row", "patch"):
        assert hasattr(manager, name) is False, f"RawTableManager 不得提供 {name}（I7）"


def test_public_surface_is_minimal() -> None:
    """公开方法只有三个写路径 + 两个自检；多一个就是在给"改原始库"开门。"""
    public = {name for name in dir(RawTableManager) if not name.startswith("_")}
    assert public == {"ensure_table", "write_rows", "existing_tables", "count_by_batch"}


# ── U-RT-02：非法月份 ─────────────────────────────────────────
@pytest.mark.parametrize(
    "bad", ["2026_6", "raw_;DROP", "2026-06", "", "raw_2026_06", "raw_2026_06;"]
)
def test_illegal_month_rejected_without_sql(bad: str) -> None:
    conn = _conn()
    manager = RawTableManager()
    with pytest.raises(TransactionError) as excinfo:
        manager.ensure_table(conn, bad)
    assert excinfo.value.code.value == "E3002"
    assert excinfo.value.http_status == 500
    # 不执行任何 SQL：库里一张 raw_% 表都不许有
    assert _raw_tables(conn) == []

    with pytest.raises(TransactionError):
        manager.write_rows(conn, bad, [_row(1)])
    assert _raw_tables(conn) == []


def test_month_key_derives_from_occurred_at() -> None:
    assert month_key("2026-10-21T19:48:03") == "2026_10"
    assert month_key("2026-06-01 08:00:00") == "2026_06"
    assert table_name("2026_10") == "raw_2026_10"
    with pytest.raises(TransactionError):
        month_key("不是时间")


# ── U-RT-03：只建有数据的月份 ─────────────────────────────────
def test_only_months_with_rows_get_tables() -> None:
    conn = _conn()
    manager = RawTableManager()
    manager.ensure_table(conn, "2026_06")
    manager.ensure_table(conn, "2026_07")
    assert _raw_tables(conn) == ["raw_2026_06", "raw_2026_07"]
    assert manager.existing_tables(conn) == ["raw_2026_06", "raw_2026_07"]
    assert table_exists(conn, "raw_2026_06") is True
    assert table_exists(conn, "raw_2025_12") is False
    with pytest.raises(TransactionError):
        table_exists(conn, "raw_;DROP")


def test_empty_accepted_creates_no_table() -> None:
    """EX-09：全重复批次一行都不写，一个表都不建（由 service 保证，这里验证原语）。"""
    conn = _conn()
    manager = RawTableManager()
    assert manager.write_rows(conn, "2026_06", []) == 0
    assert _raw_tables(conn) == []  # write_rows 不建表；建表是 ensure_table 的职责


# ── 列与索引 ──────────────────────────────────────────────────
def test_table_has_16_columns_and_2_indexes() -> None:
    conn = _conn()
    RawTableManager().ensure_table(conn, "2026_06")
    columns = [str(row["name"]) for row in conn.execute("PRAGMA table_info(raw_2026_06)")]
    assert columns == [
        "id",
        "batch_id",
        "row_no",
        "occurred_at",
        "amount_cents",
        "direction",
        "counterparty",
        "item",
        "txn_type",
        "payment_method",
        "platform_category",
        "platform_status",
        "channel",
        "fp",
        "raw_payload",
        "imported_at",
    ]
    indexes = {
        str(row["name"])
        for row in conn.execute("PRAGMA index_list(raw_2026_06)")
        if row["origin"] == "c"
    }
    assert indexes == {"idx_raw_2026_06_time", "idx_raw_2026_06_batch"}


# ── 分批写入 ──────────────────────────────────────────────────
def test_write_rows_chunks_and_counts() -> None:
    conn = _conn()
    manager = RawTableManager()
    manager.ensure_table(conn, "2026_06")
    written = manager.write_rows(conn, "2026_06", [_row(i) for i in range(1, 1001)])
    assert written == 1000  # 500/批 × 2 批
    assert conn.execute("SELECT COUNT(*) FROM raw_2026_06").fetchone()[0] == 1000
    assert manager.count_by_batch(conn, "batch-1") == 1000


def test_write_rows_accepts_iterator() -> None:
    """rows 可以是生成器（service 侧不二次物化 list 的前提）。"""
    conn = _conn()
    manager = RawTableManager()
    manager.ensure_table(conn, "2026_06")
    written = manager.write_rows(conn, "2026_06", (_row(i) for i in range(1, 4)))
    assert written == 3


# ── raw_payload 保真 ──────────────────────────────────────────
def test_dump_payload_is_deterministic_and_lossless() -> None:
    payload_a = {"金额": "12.34", "交易状态": "退款成功", "交易订单号": "202600000000000000\t"}
    payload_b = {"交易订单号": "202600000000000000\t", "交易状态": "退款成功", "金额": "12.34"}
    text_a = dump_raw_payload(payload_a)
    text_b = dump_raw_payload(payload_b)
    # sort_keys：键序不同 → 字节一致（可重放校验）
    assert text_a == text_b
    # ensure_ascii=False：中文原样保留；制表符在 JSON 里转义，解析后必须还原
    assert "退款成功" in text_a
    assert "\\t" in text_a
    assert json.loads(text_a)["交易订单号"] == "202600000000000000\t"
    assert "12.34" in text_a


def test_raw_row_roundtrip_through_db() -> None:
    conn = _conn()
    manager = RawTableManager()
    manager.ensure_table(conn, "2026_06")
    manager.write_rows(conn, "2026_06", [_row(7)])
    row = conn.execute("SELECT * FROM raw_2026_06").fetchone()
    assert row["row_no"] == 7
    assert row["amount_cents"] == 1234
    assert row["direction"] == "expense"
    assert row["channel"] == "alipay"
    assert "退款成功" in row["raw_payload"]
