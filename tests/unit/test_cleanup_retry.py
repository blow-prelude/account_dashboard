"""待清理队列的手动重试（EX-11，C3-B §5.1）。

场景与 EX-11 一致：删失败入队 →（用户关掉了占用文件的程序）→ 重试成功
→ 队列置 ``done`` + ``flag`` 清零；重复重试幂等，不报错。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.helpers.ingest_state import make_ingested_batch

from account_dashboard.api.errors import BusinessRuleError, EntryValidationError
from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.repositories.cleanup_repo import CleanupRepo
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.schema_migrator import SchemaMigrator
from account_dashboard.repositories.unit_of_work import UnitOfWork
from account_dashboard.services.cleanup_service import CleanupService


@pytest.fixture
def ctx(tmp_path: Path) -> tuple[CleanupService, Database, Path]:
    database = Database(tmp_path / "ledger.db")
    SchemaMigrator(database).migrate()
    buffer_dir = tmp_path / "buffer"
    buffer_dir.mkdir()
    yield (
        CleanupService(uow=UnitOfWork(database), buffer=BufferFileManager(buffer_dir)),
        database,
        buffer_dir,
    )
    database.close()


def _failed_item(ctx: tuple[CleanupService, Database, Path]) -> tuple[str, str, Path]:
    """造一个「提交后删除失败」的队列项，返回 (batch_id, cleanup_id, file)。"""
    svc, database, buffer_dir = ctx
    batch_id = "c" * 32
    stored_name = "d" * 32 + ".csv"
    target = buffer_dir / stored_name
    target.write_text("id,amount\n1,10\n", encoding="utf-8")
    with database.conn:
        make_ingested_batch(
            database.conn,
            batch_id=batch_id,
            stored_name=stored_name,
            file_name="账单.csv",
            pending_delete_flag=1,
        )
    # 模拟提交时的删除失败（不真的去 mock 文件系统，直接写队列）
    with UnitOfWork(database).begin():
        cleanup_id = CleanupRepo(database.conn).enqueue(
            batch_id=batch_id,
            file_path=str(target),
            reason="文件删除失败（E4003）：被占用或无权限",
        )
    return batch_id, cleanup_id, target


def test_retry_marks_done_and_clears_flag(
    ctx: tuple[CleanupService, Database, Path]
) -> None:
    svc, database, buffer_dir = ctx
    batch_id, cleanup_id, target = _failed_item(ctx)

    item = svc.retry(cleanup_id)

    assert item.status == "done"
    assert item.attempts == 1, "重试成功不新增 attempts"
    assert not target.exists(), "文件这次真的删掉了"
    row = database.query_one(
        "SELECT pending_delete_flag, deleted_at FROM staging_batch WHERE id = ?", (batch_id,)
    )
    assert row is not None
    assert row["pending_delete_flag"] == 0
    assert row["deleted_at"], "补删成功要补写 deleted_at"


def test_retry_is_idempotent_when_done(ctx: tuple[CleanupService, Database, Path]) -> None:
    """已 done 的重复重试返回当前状态，不报错（用户重复点"重试"不该看到红条）。"""
    svc, _database, _buffer_dir = ctx
    _batch_id, cleanup_id, _target = _failed_item(ctx)

    first = svc.retry(cleanup_id)
    second = svc.retry(cleanup_id)

    assert first.status == second.status == "done"
    assert second.attempts == first.attempts


def test_retry_failure_bumps_attempts_and_last_error(
    ctx: tuple[CleanupService, Database, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, database, _buffer_dir = ctx
    _batch_id, cleanup_id, _target = _failed_item(ctx)
    monkeypatch.setattr(BufferFileManager, "delete_with_retry", lambda self, path, **kw: False)

    item = svc.retry(cleanup_id)

    assert item.status == "pending", "还删不掉就继续挂着"
    assert item.attempts == 2, "attempts 递增"
    assert item.last_error, "last_error 有值"
    row = database.query_one(
        "SELECT pending_delete_flag FROM staging_batch WHERE id = ?", (item.batch_id,)
    )
    assert row is not None
    assert row["pending_delete_flag"] == 1, "重试失败不动 flag"


def test_retry_unknown_id_is_e2001(ctx: tuple[CleanupService, Database, Path]) -> None:
    svc, _database, _buffer_dir = ctx
    with pytest.raises(BusinessRuleError) as excinfo:
        svc.retry("does-not-exist")
    assert excinfo.value.code.value == "E2001"


def test_list_items_filters_by_status(ctx: tuple[CleanupService, Database, Path]) -> None:
    svc, database, _buffer_dir = ctx
    _batch_id, cleanup_id, _target = _failed_item(ctx)
    svc.retry(cleanup_id)  # → done

    pending = svc.list_items("pending")
    done = svc.list_items("done")
    everything = svc.list_items(None)

    assert pending == []
    assert [item.id for item in done] == [cleanup_id]
    assert len(everything) == 1
    assert everything[0].file_name == "账单.csv", "file_name 由 JOIN 派生（DDL 无此列）"


def test_list_items_rejects_unknown_status(ctx: tuple[CleanupService, Database, Path]) -> None:
    svc, _database, _buffer_dir = ctx
    with pytest.raises(EntryValidationError) as excinfo:
        svc.list_items("bogus")
    assert excinfo.value.code.value == "E1008"
