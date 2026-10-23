"""批次追溯（I8，C3-B §4.6）：随机 5 条主数据可回溯到 raw 行，11 字段一致。

四块齐全（``transaction`` / ``batch`` / ``raw_record`` / ``mapping_snapshot``），
``mapping_snapshot`` 直接读批次字段（只读，本线不写）。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from tests.conftest import API_PREFIX
from tests.helpers.ingest_state import (
    make_ingested_batch,
    seed_raw_rows,
    seed_transactions,
    trace_field_names,
)

from account_dashboard.repositories.database import Database

SNAPSHOT = {
    "occurred_at": 0,
    "amount": 1,
    "direction": 2,
    "counterparty": 3,
    "item": 4,
    "amount_scale": 1,
}


@pytest.fixture
def trace_scene(client: TestClient, db: Database) -> str:
    batch_id = "a1b2c3d4" + "0" * 24
    stored_name = "f" * 32 + ".csv"
    with db.conn:
        make_ingested_batch(
            db.conn,
            batch_id=batch_id,
            stored_name=stored_name,
            file_name="支付宝明细.csv",
            pending_delete_flag=0,
            mapping_snapshot=json.dumps(SNAPSHOT, ensure_ascii=False, sort_keys=True),
        )
        seed_raw_rows(db.conn, "2026_06", batch_id, 12)
        seed_transactions(db.conn, batch_id, 12)
    return batch_id


def test_random_five_transactions_trace_back_to_raw(
    trace_scene: str, client: TestClient, db: Database
) -> None:
    ids = [
        str(row["id"])
        for row in db.query_all('SELECT id FROM "transaction" ORDER BY RANDOM() LIMIT 5')
    ]
    assert len(ids) == 5

    for txn_id in ids:
        response = client.get(f"{API_PREFIX}/transactions/{txn_id}/trace")
        assert response.status_code == 200, response.text
        trace = response.json()["data"]

        # 四块齐全
        assert trace["transaction"]["id"] == txn_id
        assert trace["batch"] is not None
        assert trace["batch"]["file_name"] == "支付宝明细.csv"
        assert trace["raw_record"] is not None
        assert trace["mapping_snapshot"] == SNAPSHOT, "mapping_snapshot 原样返回（只读）"

        # 11 字段一致（raw 与 transaction 的双写口径）
        raw = trace["raw_record"]
        txn = trace["transaction"]
        assert raw["batch_id"] == txn["batch_id"]
        assert raw["row_no"] == txn["row_no"]
        assert raw["occurred_at"] == txn["occurred_at"]
        assert raw["amount_cents"] == txn["amount_cents"]
        assert raw["direction"] == txn["direction"]
        assert raw["counterparty"] == txn["counterparty"]
        assert raw["item"] == txn["item"]
        assert raw["txn_type"] == txn["txn_type"]
        assert raw["payment_method"] == txn["payment_method"]
        assert raw["channel"] == txn["channel"]
        assert raw["fp"] == txn["fp"]
        assert len(trace_field_names()) == 11


def test_trace_back_end_to_end(trace_scene: str, client: TestClient, db: Database) -> None:
    """正向闭环：raw 行 → (batch_id, row_no) → 唯一的 transaction。"""
    raw = db.query_one("SELECT id, batch_id, row_no FROM raw_2026_06 ORDER BY id LIMIT 1")
    assert raw is not None
    txn = db.query_one(
        'SELECT id FROM "transaction" WHERE batch_id = ? AND row_no = ?',
        (raw["batch_id"], raw["row_no"]),
    )
    assert txn is not None

    response = client.get(f"{API_PREFIX}/transactions/{txn['id']}/trace")

    assert response.status_code == 200
    trace = response.json()["data"]
    assert trace["raw_record"]["id"] == raw["id"]
