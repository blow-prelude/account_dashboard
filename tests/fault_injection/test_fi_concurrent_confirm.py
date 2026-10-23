"""故障注入 3：并发双确认（C3-A §6.1 / U-IG-02）。

两个线程同时 ``confirm`` 同一批次：恰一个成功、另一个 409 ``E2002``，
``transaction`` 无重复 ``fp``（幂等闸门 = 条件 UPDATE + rowcount，靠
``BEGIN IMMEDIATE`` 的写锁天然串行化）。
"""

from __future__ import annotations

import concurrent.futures
import sqlite3
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from account_dashboard.api.errors import BusinessRuleError
from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.infra.paths import DataPaths
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.unit_of_work import UnitOfWork
from account_dashboard.services.import_orchestrator import ImportOrchestrator
from account_dashboard.services.ingest_ports import NullSink
from account_dashboard.services.ingest_service import IngestService

PREFIX = "/api/v1/staging"
SAMPLE = "alipay_sample_gb18030.csv"


def _mapping(client: TestClient, batch_id: str) -> dict[str, Any]:
    preview = client.get(f"{PREFIX}/batches/{batch_id}/preview", params={"limit": 1}).json()["data"]
    payload = dict(preview["detected_fields"])
    payload.update({"direction_map": {}, "amount_scale": 1})
    return payload


def make_service(db: Database, paths: DataPaths) -> IngestService:
    buffer = BufferFileManager(paths.buffer_dir)
    return IngestService(
        uow=UnitOfWork(db),
        orchestrator=ImportOrchestrator(uow=UnitOfWork(db), buffer=buffer, database=db),
        sink=NullSink(),
        buffer=buffer,
    )


def test_concurrent_confirm_exactly_one_wins(
    client: TestClient, upload, fixtures_dir: Path, db: Database, paths: DataPaths
) -> None:
    batch = upload(fixtures_dir / SAMPLE)
    batch_id = str(batch["id"])
    client.put(f"{PREFIX}/batches/{batch_id}/mapping", json=_mapping(client, batch_id))
    client.post(f"{PREFIX}/batches/{batch_id}/precheck")

    # 两个线程、两个服务实例（模拟两个请求），共享同一个 Database
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(make_service(db, paths).confirm, batch_id),
            pool.submit(make_service(db, paths).confirm, batch_id),
        ]
        results = [future.exception() for future in futures]

    successes = [item for item in results if item is None]
    conflicts = [item for item in results if isinstance(item, BusinessRuleError)]
    assert len(successes) == 1, f"应恰一个成功：{results}"
    assert len(conflicts) == 1
    assert conflicts[0].code.value == "E2002"

    # 无重复行、无重复 fp
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 669
    dup_fp = db.scalar_int(
        'SELECT COUNT(*) FROM (SELECT fp FROM "transaction" GROUP BY fp HAVING COUNT(*) > 1)'
    )
    assert dup_fp == 0
    assert db.scalar_int(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'raw_%'"
    ) == 5

    row = db.query_one("SELECT status FROM staging_batch WHERE id = ?", (batch_id,))
    assert row is not None and row["status"] == "ingested"


def test_concurrent_confirm_no_half_written_state(
    client: TestClient, upload, fixtures_dir: Path, db: Database, paths: DataPaths
) -> None:
    """并发下 raw 与 transaction 行数必须相等（不会出现"raw 写了 transaction 没写"）。"""
    batch = upload(fixtures_dir / SAMPLE)
    batch_id = str(batch["id"])
    client.put(f"{PREFIX}/batches/{batch_id}/mapping", json=_mapping(client, batch_id))
    client.post(f"{PREFIX}/batches/{batch_id}/precheck")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(make_service(db, paths).confirm, batch_id) for _ in range(2)]
        for future in futures:
            future.exception()

    txn_count = db.scalar_int('SELECT COUNT(*) FROM "transaction"')
    raw_count = sum(
        db.scalar_int(f"SELECT COUNT(*) FROM {name}")
        for name in (
            str(row["name"])
            for row in db.query_all(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'raw_%'"
            )
        )
    )
    assert txn_count == raw_count == 669
    assert isinstance(db.conn, sqlite3.Connection)
