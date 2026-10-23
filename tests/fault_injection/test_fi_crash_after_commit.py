"""故障注入 2：COMMIT 之后、删文件之前进程崩了（C3 §6.1 第 2 条）。

这是唯一一条模拟"真实崩溃残局"的用例：数据已提交、``flag=1``、文件还在。
重启对账的第 ② 步补删 → 文件被删、``flag=0``、日志有补删记录。

用 Gate 0 的 SQL 夹具直接造出这个残局（不需要真的 kill 进程 ——
``KeyboardInterrupt`` 发生在 A 线的 ``sink.on_committed`` 调用点上，
对 B 线而言等价于"提交后没有任何删除动作发生"）。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from tests.helpers.ingest_state import make_ingested_batch, seed_raw_rows, seed_transactions

from account_dashboard.infra.paths import DataPaths
from account_dashboard.infra.reconciliation import run_startup_reconciliation
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.schema_migrator import SchemaMigrator


class _ListHandler(logging.Handler):
    """直接挂在目标 logger 上的收集器（setup_logging 会关 propagate，caplog 抓不到）。"""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def messages(self) -> list[str]:
        return [record.getMessage() for record in self.records]


@pytest.fixture
def crash_scene(tmp_path: Path) -> tuple[Database, DataPaths, _ListHandler]:
    """残局： ingested + flag=1 + 文件在 + 数据已入库。"""
    paths = DataPaths(data_dir=tmp_path)
    paths.ensure_dirs()
    database = Database(paths.db_file)
    SchemaMigrator(database).migrate()

    batch_id = "9" * 32
    stored_name = "8" * 32 + ".csv"
    csv_text = "交易时间,金额,收/支\n2026-06-01,10.00,支出\n"
    (paths.buffer_dir / stored_name).write_text(csv_text, encoding="utf-8")
    with database.conn:
        make_ingested_batch(
            database.conn,
            batch_id=batch_id,
            stored_name=stored_name,
            file_name="支付宝明细.csv",
            pending_delete_flag=1,
            report_json='{"total": 5, "inserted": 5}',
        )
        seed_raw_rows(database.conn, "2026_06", batch_id, 5)
        seed_transactions(database.conn, batch_id, 5)

    handler = _ListHandler()
    logger = logging.getLogger("account_dashboard.reconciliation")
    logger.addHandler(handler)
    # 子 logger 未显式设级时继承 root 的 WARNING，INFO 记录会在
    # 到达 handler 前被 logger 自身级别过滤掉（setup_logging 未运行）
    logger.setLevel(logging.INFO)
    yield database, paths, handler
    logger.removeHandler(handler)
    database.close()


def test_crash_after_commit_is_healed_by_reconciliation(
    crash_scene: tuple[Database, DataPaths, _ListHandler],
) -> None:
    database, paths, handler = crash_scene
    stored_name = "8" * 32 + ".csv"

    report = run_startup_reconciliation(database, paths)

    # 补删生效
    assert not (paths.buffer_dir / stored_name).exists(), "重启后文件应被补删"
    row = database.query_one(
        "SELECT pending_delete_flag, deleted_at, status FROM staging_batch", ()
    )
    assert row is not None
    assert row["pending_delete_flag"] == 0
    assert row["deleted_at"], "补删成功要补写 deleted_at"
    assert row["status"] == "ingested"
    assert report.deleted_files == 1
    assert report.enqueued_files == 0
    assert report.pending_deletes == 0

    # 数据不受影响（事务早就提交了）
    assert database.scalar_int('SELECT COUNT(*) FROM "transaction"') == 5
    assert database.scalar_int("SELECT COUNT(*) FROM raw_2026_06") == 5

    # 日志有补删记录
    assert any("补删" in message for message in handler.messages), handler.messages


def test_crash_scene_with_locked_file_enqueues_instead(
    crash_scene: tuple[Database, DataPaths, _ListHandler], monkeypatch: pytest.MonkeyPatch
) -> None:
    """文件仍被占用（EX-11）：补删失败 → 入队，数据与启动都不受影响。"""
    from account_dashboard.infra.buffer_file import BufferFileManager

    database, paths, _handler = crash_scene
    monkeypatch.setattr(BufferFileManager, "delete_with_retry", lambda self, path, **kw: False)

    report = run_startup_reconciliation(database, paths)

    assert report.deleted_files == 0
    assert report.enqueued_files == 1
    assert report.pending_deletes == 1
    rows = database.query_all("SELECT status, attempts, reason FROM cleanup_queue")
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["attempts"] == 1
    assert "启动补删失败" in rows[0]["reason"]
    assert database.scalar_int('SELECT COUNT(*) FROM "transaction"') == 5, "数据不受影响"
