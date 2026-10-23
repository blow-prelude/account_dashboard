"""故障注入 2 的合稿增强（M5）：真实 confirm 后崩溃 → 重启对账补删。

B 线的 ``test_fi_crash_after_commit.py`` 用 SQL 夹具造残局，验证对账第 ② 步；
本用例走**真实 A 线 confirm**（生产同构装配：``IngestService`` + 真实
``CleanupService`` 作 sink，与 ``api/deps.py`` 一致），把
``sink.on_committed`` 换成抛 ``KeyboardInterrupt`` 的实现，模拟
「事务已提交、删文件前进程崩了」—— 合稿文档 M5 的闭环断言：

① 真实 confirm（事务提交）② sink 前崩溃 ③ 数据在、批次 ingested、
flag=1、文件仍在 ④ 重启对账补删 → flag=0、文件消失。

不走 HTTP：``KeyboardInterrupt`` 是 BaseException，会被 anyio 传输层当成
取消语义吞掉（``pytest.raises`` 拿到的是 ``CancelledError``）；服务层直调
走的是与端点同一条 ``confirm`` 代码路径，等价且干净。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.infra.paths import DataPaths
from account_dashboard.infra.reconciliation import run_startup_reconciliation
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.unit_of_work import UnitOfWork
from account_dashboard.services.cleanup_service import CleanupService
from account_dashboard.services.import_orchestrator import ImportOrchestrator
from account_dashboard.services.ingest_service import IngestService

PREFIX = "/api/v1/staging"
SAMPLE = "alipay_sample_gb18030.csv"


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def messages(self) -> list[str]:
        return [record.getMessage() for record in self.records]


def _mapping(client: Any, batch_id: str) -> dict[str, Any]:
    preview = client.get(f"{PREFIX}/batches/{batch_id}/preview", params={"limit": 1}).json()[
        "data"
    ]
    payload = dict(preview["detected_fields"])
    payload.update({"direction_map": {}, "amount_scale": 1})
    return payload


def _ingest_service(db: Database, paths: DataPaths) -> IngestService:
    """与 ``api/deps.py::get_ingest_service`` 同构（M2 后 sink 是 CleanupService）。"""
    buffer = BufferFileManager(paths.buffer_dir)
    return IngestService(
        uow=UnitOfWork(db),
        orchestrator=ImportOrchestrator(uow=UnitOfWork(db), buffer=buffer, database=db),
        sink=CleanupService(uow=UnitOfWork(db), buffer=buffer),
        buffer=buffer,
        data_dir=paths.data_dir,
    )


def test_real_confirm_crash_is_healed_on_restart(
    client: Any,
    upload: Any,
    fixtures_dir: Path,
    db: Database,
    paths: DataPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M5 闭环：真实入库 → sink 前崩溃 → 重启补删。"""

    def crash(self: CleanupService, batch_id: str, file_path: str) -> Any:
        raise KeyboardInterrupt("模拟进程在 COMMIT 之后、删文件之前崩溃")

    monkeypatch.setattr(CleanupService, "on_committed", crash)

    batch = upload(fixtures_dir / SAMPLE)
    batch_id = str(batch["id"])
    client.put(f"{PREFIX}/batches/{batch_id}/mapping", json=_mapping(client, batch_id))
    client.post(f"{PREFIX}/batches/{batch_id}/precheck")

    # ① 真实 confirm：事务已提交；② KeyboardInterrupt 从 sink 调用点穿出
    with pytest.raises(KeyboardInterrupt):
        _ingest_service(db, paths).confirm(batch_id)

    # ③ 崩溃残局断言：数据在、批次 ingested、flag=1、文件仍在
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 669
    assert db.scalar_int("SELECT COUNT(*) FROM raw_2026_06") == 101
    row = db.query_one(
        "SELECT status, pending_delete_flag FROM staging_batch WHERE id = ?", (batch_id,)
    )
    assert row is not None
    assert row["status"] == "ingested", "事务已提交，崩溃不得回滚已入库数据"
    assert row["pending_delete_flag"] == 1, "删除意图已置位，等对账补删"
    stored = db.query_one("SELECT stored_name FROM staging_batch WHERE id = ?", (batch_id,))
    assert stored is not None
    stored_name = str(stored["stored_name"])
    assert (paths.buffer_dir / stored_name).exists(), "文件应仍在"

    handler = _ListHandler()
    logger = logging.getLogger("account_dashboard.reconciliation")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        # ④ 重启（跑启动对账）→ B 线第 ② 步补删
        report = run_startup_reconciliation(db, paths)
    finally:
        logger.removeHandler(handler)

    assert not (paths.buffer_dir / stored_name).exists(), "重启后应补删"
    healed = db.query_one(
        "SELECT pending_delete_flag, deleted_at, status FROM staging_batch WHERE id = ?",
        (batch_id,),
    )
    assert healed is not None
    assert healed["pending_delete_flag"] == 0
    assert healed["deleted_at"], "补删成功要补写 deleted_at"
    assert healed["status"] == "ingested"
    assert report.deleted_files == 1
    assert report.pending_deletes == 0
    assert any("补删" in message for message in handler.messages), handler.messages

    # 数据全程未受影响（669 行原样）
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 669
