"""追溯缺块的处理（C3-B §4.6）：不一律报错。

* 流水不存在 → 404 ``E2010``；
* 流水存在但 raw 表被删（数据分叉）→ **200 + ``raw_record=null``** + WARN 日志。
  这是严重缺陷信号，应暴露在日志而不是给用户一个 500。
"""

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient
from tests.conftest import API_PREFIX
from tests.helpers.ingest_state import make_ingested_batch, seed_transactions

from account_dashboard.repositories.database import Database


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def messages(self) -> list[str]:
        return [record.getMessage() for record in self.records]


def test_missing_raw_table_returns_null_block_with_warn(
    client: TestClient, db: Database
) -> None:
    batch_id = "d" * 32
    with db.conn:
        make_ingested_batch(
            db.conn,
            batch_id=batch_id,
            stored_name="e" * 32 + ".csv",
            file_name="微信账单.xlsx",
            pending_delete_flag=0,
            mapping_snapshot=json.dumps({"occurred_at": 0}, ensure_ascii=False),
        )
        seed_transactions(db.conn, batch_id, 3)
        # 「数据损坏」：raw 表被删掉（D-6 保证正常跳过不会走到这条分支）
        db.conn.execute("DROP TABLE IF EXISTS raw_2026_06")

    handler = _ListHandler()
    logger = logging.getLogger("account_dashboard.trace")
    logger.addHandler(handler)
    try:
        txn_id = str(db.query_one('SELECT id FROM "transaction"')["id"])
        response = client.get(f"{API_PREFIX}/transactions/{txn_id}/trace")
    finally:
        logger.removeHandler(handler)

    assert response.status_code == 200, "缺块不是 500"
    trace = response.json()["data"]
    assert trace["transaction"]["id"] == txn_id
    assert trace["batch"] is not None
    assert trace["raw_record"] is None, "raw 表不在 → 该块为 null"
    assert trace["mapping_snapshot"] == {"occurred_at": 0}
    assert any("缺块" in message for message in handler.messages), handler.messages


def test_missing_transaction_is_e2010(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/transactions/does-not-exist/trace")

    assert response.status_code == 404
    assert response.json()["code"] == "E2010"


def test_missing_batch_block_is_null_with_warn(client: TestClient, db: Database) -> None:
    """批次行被删：batch 块 null + WARN（同样是数据分叉信号）。"""
    batch_id = "a" * 32
    with db.conn:
        seed_transactions(db.conn, batch_id, 1)
        from tests.helpers.ingest_state import seed_raw_rows

        seed_raw_rows(db.conn, "2026_06", batch_id, 1)
        db.conn.execute("DELETE FROM staging_batch")

    handler = _ListHandler()
    logger = logging.getLogger("account_dashboard.trace")
    logger.addHandler(handler)
    try:
        txn_id = str(db.query_one('SELECT id FROM "transaction"')["id"])
        response = client.get(f"{API_PREFIX}/transactions/{txn_id}/trace")
    finally:
        logger.removeHandler(handler)

    assert response.status_code == 200
    trace = response.json()["data"]
    assert trace["batch"] is None
    assert trace["raw_record"] is not None
    assert any("缺块" in message for message in handler.messages), handler.messages
