"""删除意图（C3-B §4.1，K3/K4）：``CleanupService.on_committed`` 的两条分支。

删成功 → ``flag`` 清零 + ``deleted_at`` 写入 + 不入队；
删失败 → 入队且批次仍 ``ingested``（数据已提交，绝不能回滚入库）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from tests.helpers.ingest_state import make_ingested_batch

from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.repositories.cleanup_repo import CleanupRepo
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.schema_migrator import SchemaMigrator
from account_dashboard.repositories.unit_of_work import UnitOfWork
from account_dashboard.services.cleanup_service import CleanupService
from account_dashboard.services.ingest_ports import DeleteFailureSink


@pytest.fixture
def service(tmp_path: Path) -> tuple[CleanupService, Database, Path]:
    database = Database(tmp_path / "ledger.db")
    SchemaMigrator(database).migrate()
    buffer_dir = tmp_path / "buffer"
    buffer_dir.mkdir()
    svc = CleanupService(uow=UnitOfWork(database), buffer=BufferFileManager(buffer_dir))
    yield svc, database, buffer_dir
    database.close()


def _seed(database: Database, buffer_dir: Path, *, flag: int = 1) -> tuple[str, Path]:
    batch_id = "b" * 32
    stored_name = "a" * 32 + ".csv"
    target = buffer_dir / stored_name
    target.write_text("id,amount\n1,10\n", encoding="utf-8")
    with database.conn:
        make_ingested_batch(
            database.conn,
            batch_id=batch_id,
            stored_name=stored_name,
            file_name="账单.csv",
            pending_delete_flag=flag,
        )
    return batch_id, target


def test_service_satisfies_sink_protocol(service: tuple[CleanupService, Database, Path]) -> None:
    """Gate 0 的 Protocol 用 runtime_checkable 声明，合稿 M2 靠它替换 NullSink。"""
    assert isinstance(service[0], DeleteFailureSink)


def test_delete_success_clears_flag_and_leaves_no_queue(
    service: tuple[CleanupService, Database, Path],
) -> None:
    svc, database, buffer_dir = service
    batch_id, target = _seed(database, buffer_dir)

    outcome = svc.on_committed(batch_id, str(target))

    assert outcome.deleted is True
    assert outcome.cleanup_id is None
    assert not target.exists(), "文件必须真的被删掉"
    row = database.query_one(
        "SELECT pending_delete_flag, deleted_at, status FROM staging_batch WHERE id = ?",
        (batch_id,),
    )
    assert row is not None
    assert row["pending_delete_flag"] == 0
    assert row["deleted_at"], "删除成功要落 deleted_at"
    assert row["status"] == "ingested"
    assert database.query_all("SELECT * FROM cleanup_queue") == [], "删成功不入队"


def test_delete_failure_enqueues_and_keeps_batch_ingested(
    service: tuple[CleanupService, Database, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """EX-11：删不掉只能入队 —— 数据已提交，批次仍是 ingested，队列 +1。"""
    svc, database, buffer_dir = service
    batch_id, target = _seed(database, buffer_dir)

    monkeypatch.setattr(BufferFileManager, "delete_with_retry", lambda self, path, **kw: False)

    outcome = svc.on_committed(batch_id, str(target))

    assert outcome.deleted is False
    assert outcome.cleanup_id, "deleted=False 时 cleanup_id 必填（D-7）"
    assert target.exists(), "删不掉不能动文件"
    batch = database.query_one(
        "SELECT pending_delete_flag, status FROM staging_batch WHERE id = ?", (batch_id,)
    )
    assert batch is not None
    assert batch["pending_delete_flag"] == 1, "入队不清零：flag 仍表示删除意图待执行"
    assert batch["status"] == "ingested", "不能因为删不掉就回滚入库"
    rows = database.query_all(
        "SELECT id, batch_id, file_path, reason, attempts, last_error, status FROM cleanup_queue"
    )
    assert len(rows) == 1
    assert rows[0]["id"] == outcome.cleanup_id
    assert rows[0]["batch_id"] == batch_id
    assert rows[0]["file_path"] == str(target)
    assert rows[0]["attempts"] == 1
    assert rows[0]["last_error"], "失败原因要留痕"
    assert rows[0]["status"] == "pending"


def test_second_failure_accumulates_attempts(
    service: tuple[CleanupService, Database, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一路径重复入队只累加 attempts，不插第二行（启动对账可能反复触发）。"""
    svc, database, buffer_dir = service
    batch_id, target = _seed(database, buffer_dir)
    monkeypatch.setattr(BufferFileManager, "delete_with_retry", lambda self, path, **kw: False)

    svc.on_committed(batch_id, str(target))
    svc.on_committed(batch_id, str(target))

    rows = database.query_all("SELECT attempts FROM cleanup_queue")
    assert len(rows) == 1
    assert rows[0]["attempts"] == 2


def test_half_failure_states_are_explainable_and_self_healing(
    service: tuple[CleanupService, Database, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """§4.1 硬约束的行为面：清零与入队是两个独立小事务。

    合并成一个事务时"清零成功但入队失败"的中间态无法解释；分开之后，
    任一半途失败都能被下次对账自愈（删除是幂等的）：

    * 文件删了、清零失败 → ``flag`` 仍为 1，文件已不在；
      下次对账 ② 补删时 ``FileNotFoundError`` 视为成功 → 清零。
    * 删除失败、入队炸了 → 异常上抛，``flag`` 仍为 1，队列空；
      下次对账 ② 会重新尝试删除。
    """
    svc, database, buffer_dir = service
    batch_id, target = _seed(database, buffer_dir)

    def boom(self: object, *args: object, **kwargs: object) -> int:
        raise sqlite3.OperationalError("db is locked")

    # 场景一：删除成功但清零失败
    monkeypatch.setattr(CleanupRepo, "clear_pending_delete", boom)
    with pytest.raises(sqlite3.OperationalError):
        svc.on_committed(batch_id, str(target))
    monkeypatch.undo()

    assert not target.exists(), "文件已经删掉了"
    row = database.query_one(
        "SELECT pending_delete_flag FROM staging_batch WHERE id = ?", (batch_id,)
    )
    assert row is not None
    assert row["pending_delete_flag"] == 1, "清零失败 → 删除意图仍在"

    # 自愈：对账补删遇到"文件已不在"视为成功，补上清零
    from account_dashboard.infra.paths import DataPaths
    from account_dashboard.infra.reconciliation import run_startup_reconciliation

    paths = DataPaths(data_dir=buffer_dir.parent)
    report = run_startup_reconciliation(database, paths)
    row = database.query_one(
        "SELECT pending_delete_flag, deleted_at FROM staging_batch WHERE id = ?", (batch_id,)
    )
    assert row is not None
    assert row["pending_delete_flag"] == 0
    assert row["deleted_at"]
    assert report.deleted_files == 1
