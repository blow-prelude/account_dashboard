"""故障注入 4：磁盘满（EX-23 / C3-A §4.7 的两个阶段）。

两个阶段都不得留下半成品 raw 表（断言 ``sqlite_master`` 里 ``raw_%`` 数量不变）：

* **写入时** ``OSError(ENOSPC)`` → SQLite 抛 ``sqlite3.OperationalError`` →
  回滚 + 507 ``E4001``；
* **入库前** ``shutil.disk_usage`` 余量不足 → 不开事务，批次仍 ``prechecked``。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from account_dashboard.api.errors import FileIOError
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


def prepare(client: TestClient, upload, fixtures_dir: Path) -> str:
    batch = upload(fixtures_dir / SAMPLE)
    batch_id = str(batch["id"])
    client.put(f"{PREFIX}/batches/{batch_id}/mapping", json=_mapping(client, batch_id))
    client.post(f"{PREFIX}/batches/{batch_id}/precheck")
    return batch_id


class _EnospcConn:
    """代理连接：对 raw_* 的 DDL/INSERT 抛 ``OperationalError("disk I/O error")``。

    事务（BEGIN/COMMIT/ROLLBACK）与其余 SQL 原样透传给真连接 —— 测的是
    真事务回滚，不是 mock。
    """

    def __init__(self, real: sqlite3.Connection, fail_on: Any) -> None:
        self._real = real
        self._fail_on = fail_on

    def execute(self, sql: str, *args: Any) -> sqlite3.Cursor:
        if self._fail_on(sql):
            raise sqlite3.OperationalError("disk I/O error")
        return self._real.execute(sql, *args)

    def executemany(self, sql: str, rows: Any) -> sqlite3.Cursor:
        if self._fail_on(sql):
            raise sqlite3.OperationalError("disk I/O error")
        return self._real.executemany(sql, rows)

    @property
    def in_transaction(self) -> bool:
        return self._real.in_transaction

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class _ProxyUow:
    """测试替身：事务仍走真 Database（同一连接），但把 conn 换成代理。"""

    def __init__(self, database: Database, conn: sqlite3.Connection) -> None:
        self._database = database
        self._conn = conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    @contextmanager
    def begin(self) -> Iterator[UnitOfWork]:
        with self._database.transaction():
            yield self  # type: ignore[misc]


def _raw_table_count(db: Database) -> int:
    return db.scalar_int(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'raw_%'"
    )


def _make_service(db: Database, paths: DataPaths, **kwargs: Any) -> IngestService:
    buffer = BufferFileManager(paths.buffer_dir)
    return IngestService(
        uow=UnitOfWork(db),
        orchestrator=ImportOrchestrator(uow=UnitOfWork(db), buffer=buffer, database=db),
        sink=NullSink(),
        buffer=buffer,
        **kwargs,
    )


def test_enospc_during_write_rolls_back(
    client: TestClient, upload, fixtures_dir: Path, db: Database, paths: DataPaths
) -> None:
    """写入阶段 ENOSPC：回滚 + 507 E4001，raw_% 表数量不变。"""
    batch_id = prepare(client, upload, fixtures_dir)
    before_tables = _raw_table_count(db)

    service = _make_service(db, paths)
    proxy = _EnospcConn(db.conn, lambda sql: "raw_" in sql)
    service._uow = _ProxyUow(db, proxy)  # type: ignore[assignment]

    with pytest.raises(FileIOError) as excinfo:
        service.confirm(batch_id)
    assert excinfo.value.code.value == "E4001"
    assert excinfo.value.http_status == 507

    # 半成品 raw 表不存在（DDL 随事务回滚），transaction 零行
    assert _raw_table_count(db) == before_tables == 0
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 0

    row = db.query_one("SELECT status FROM staging_batch WHERE id = ?", (batch_id,))
    assert row is not None and row["status"] == "prechecked"


def test_low_disk_space_blocks_before_transaction(
    client: TestClient, upload, fixtures_dir: Path, db: Database, paths: DataPaths
) -> None:
    """预防阶段：余量不足 → 不开事务，批次仍 prechecked。"""
    batch_id = prepare(client, upload, fixtures_dir)

    service = _make_service(db, paths, free_space_probe=lambda: 0)
    with pytest.raises(FileIOError) as excinfo:
        service.confirm(batch_id)
    assert excinfo.value.code.value == "E4001"
    assert excinfo.value.http_status == 507

    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 0
    assert _raw_table_count(db) == 0
    row = db.query_one(
        "SELECT status, ingest_started_at FROM staging_batch WHERE id = ?", (batch_id,)
    )
    assert row is not None and row["status"] == "prechecked"
    # ingest_started_at 不应被写入（事务没开）
    assert row["ingest_started_at"] is None


def test_healthy_disk_passes_precheck(
    client: TestClient, upload, fixtures_dir: Path, db: Database, paths: DataPaths
) -> None:
    """对照组：余量充足时预检不拦路。"""
    batch_id = prepare(client, upload, fixtures_dir)
    report = _make_service(db, paths, free_space_probe=lambda: 10**12).confirm(batch_id)
    assert report.inserted == 669
