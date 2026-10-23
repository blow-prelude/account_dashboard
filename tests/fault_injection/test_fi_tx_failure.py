"""故障注入 1：入库事务中途失败（C3-A §6.1 / C3 基线 §6.1）。

注入点在 ``TransactionRepo.insert_many`` **内部按批计数**（第 2 批抛
``RuntimeError``）—— 不 mock 整个 repo，测的是真事务：

* 批次回 ``prechecked``（闸门与写操作同事务，崩溃即回滚，D-8）；
* raw 与 transaction **均无残留**，``raw_%`` 表数量不变（DDL 参与回滚）；
* 500 ``E3001``；
* 可立即重试成功。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from account_dashboard.api.errors import AppError, TransactionError
from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.infra.paths import DataPaths
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.transaction_repo import TransactionRepo
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


def _confirm(client: TestClient, batch_id: str) -> dict[str, Any]:
    response = client.post(f"{PREFIX}/batches/{batch_id}/confirm")
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


def make_service(
    db: Database,
    paths: DataPaths,
    *,
    insert_batch_hook: Any = None,
) -> IngestService:
    buffer = BufferFileManager(paths.buffer_dir)
    return IngestService(
        uow=UnitOfWork(db),
        orchestrator=ImportOrchestrator(uow=UnitOfWork(db), buffer=buffer, database=db),
        sink=NullSink(),
        buffer=buffer,
        insert_batch_hook=insert_batch_hook,
    )


def _raw_table_count(db: Database) -> int:
    return db.scalar_int(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'raw_%'"
    )


def test_tx_failure_rolls_back_everything(
    client: TestClient, upload, fixtures_dir: Path, db: Database, paths: DataPaths
) -> None:
    """insert_many 第 2 批抛错 → 全回滚 + 500 E3001 + 可立即重试成功。"""
    batch_id = prepare(client, upload, fixtures_dir)

    def explode_on_second_batch(index: int, size: int) -> None:
        if index == 1:  # 第 2 批（669 行 / 500 每批 → 共 2 批）
            raise RuntimeError("注入：第 2 批写入失败")

    service = make_service(db, paths, insert_batch_hook=explode_on_second_batch)
    with pytest.raises(TransactionError) as excinfo:
        service.confirm(batch_id)

    assert excinfo.value.code.value == "E3001"
    assert excinfo.value.http_status == 500

    # 批次回 prechecked（ingesting 是瞬态，崩溃即回滚）
    row = db.query_one("SELECT status FROM staging_batch WHERE id = ?", (batch_id,))
    assert row is not None and row["status"] == "prechecked"
    # raw 与 transaction 均无残留；raw_% 表数量不变（DDL 也回滚了）
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 0
    assert _raw_table_count(db) == 0

    # 可立即重试成功（同一批次、同一装配，去掉注入）
    report = make_service(db, paths).confirm(batch_id)
    assert report.inserted == 669
    assert _raw_table_count(db) == 5
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 669


def test_tx_failure_keeps_existing_tables_untouched(
    client: TestClient, upload, fixtures_dir: Path, db: Database, paths: DataPaths, tmp_path: Path
) -> None:
    """已有 5 张 raw 表时再注入失败：表数量不变、旧数据不动（出口检查表原话）。"""
    first = prepare(client, upload, fixtures_dir)
    _confirm(client, first)
    assert _raw_table_count(db) == 5
    assert db.scalar_int("SELECT COUNT(*) FROM raw_2026_06") == 101

    # 另一份 600 行的全新数据（必然 2 批：500 + 100）
    fresh = tmp_path / "fresh_600.csv"
    lines = ["交易时间,交易分类,交易对方,商品说明,收/支,金额,收/付款方式,交易状态"]
    for index in range(600):
        lines.append(
            f"2026-11-{index % 28 + 1:02d} 10:00:00,餐饮美食,新商户{index},新品{index},"
            f"支出,{index % 90 + 1}.50,微信,交易成功"
        )
    fresh.write_text("\n".join(lines) + "\n", encoding="utf-8")

    batch = upload(fresh)
    second = str(batch["id"])
    client.put(f"{PREFIX}/batches/{second}/mapping", json=_mapping(client, second))
    client.post(f"{PREFIX}/batches/{second}/precheck")

    def explode_on_second_batch(index: int, size: int) -> None:
        if index == 1:
            raise RuntimeError("注入：第 2 批写入失败")

    with pytest.raises(TransactionError):
        make_service(db, paths, insert_batch_hook=explode_on_second_batch).confirm(second)

    # 新表一张都没建（DDL 回滚），旧表旧数据原样
    assert _raw_table_count(db) == 5
    assert db.scalar_int("SELECT COUNT(*) FROM raw_2026_06") == 101
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 669
    row = db.query_one("SELECT status FROM staging_batch WHERE id = ?", (second,))
    assert row is not None and row["status"] == "prechecked"


def test_tx_failure_over_http_returns_e3001(
    client: TestClient,
    upload,
    fixtures_dir: Path,
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP 层：500 E3001（前端 catch 提示「已回滚，可重试」）。"""
    batch_id = prepare(client, upload, fixtures_dir)

    original = TransactionRepo.insert_many

    def flaky(self: TransactionRepo, rows: Any, **kwargs: Any) -> int:
        calls = {"n": 0}

        def hook(index: int, size: int) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("注入：第 2 批写入失败")

        return original(self, rows, batch_hook=hook)

    monkeypatch.setattr(TransactionRepo, "insert_many", flaky)

    response = client.post(f"{PREFIX}/batches/{batch_id}/confirm")
    assert response.status_code == 500
    assert response.json()["code"] == "E3001"

    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 0
    assert _raw_table_count(db) == 0
    row = db.query_one("SELECT status FROM staging_batch WHERE id = ?", (batch_id,))
    assert row is not None and row["status"] == "prechecked"

    monkeypatch.undo()
    retry = client.post(f"{PREFIX}/batches/{batch_id}/confirm")
    assert retry.status_code == 200, retry.text
    assert retry.json()["data"]["inserted"] == 669


def test_operational_error_is_not_swallowed(
    client: TestClient, upload, fixtures_dir: Path, db: Database, paths: DataPaths
) -> None:
    """裸 sqlite3.OperationalError 也要走 E3001/E3003 分级，不能变成 500 E5001。"""
    batch_id = prepare(client, upload, fixtures_dir)

    def boom(index: int, size: int) -> None:
        raise sqlite3.OperationalError("no such table: transaction")

    with pytest.raises(AppError) as excinfo:
        make_service(db, paths, insert_batch_hook=boom).confirm(batch_id)

    # 不含 full/disk/locked/busy → E3001（500）
    assert excinfo.value.code.value == "E3001"
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 0
