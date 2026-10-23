"""孤儿扫描（EX-13，C3-B §4.3 第 ④ 步）：只报告，不自动删。

缓冲区里放一个无批次文件 → 出现在孤儿清单且**文件仍在**；
半成品（``.part`` / ``.tmp``）不算孤儿（C2 的口径，三处一致）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from account_dashboard.infra.paths import DataPaths
from account_dashboard.infra.reconciliation import run_startup_reconciliation
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.schema_migrator import SchemaMigrator


@pytest.fixture
def env(tmp_path: Path) -> tuple[Database, DataPaths]:
    paths = DataPaths(data_dir=tmp_path)
    paths.ensure_dirs()
    database = Database(paths.db_file)
    SchemaMigrator(database).migrate()
    yield database, paths
    database.close()


def test_orphan_is_reported_but_never_deleted(env: tuple[Database, DataPaths]) -> None:
    database, paths = env
    orphan = paths.buffer_dir / ("f" * 32 + ".csv")
    orphan.write_text("orphan", encoding="utf-8")
    (paths.buffer_dir / "half.part").write_text("part", encoding="utf-8")
    (paths.buffer_dir / "legacy.tmp").write_text("tmp", encoding="utf-8")

    report = run_startup_reconciliation(database, paths)

    assert report.orphans == 1
    assert report.orphan_names == (orphan.name,)
    assert orphan.is_file(), "第 ④ 步只报告，文件必须还在（EX-13 要用户确认后才清理）"
    assert (paths.buffer_dir / "half.part").is_file()
    assert (paths.buffer_dir / "legacy.tmp").is_file()


def test_live_batch_file_is_not_an_orphan(env: tuple[Database, DataPaths]) -> None:
    """未入库批次的文件是"已知"的，不是孤儿。"""
    database, paths = env
    stored_name = "e" * 32 + ".csv"
    (paths.buffer_dir / stored_name).write_text("live", encoding="utf-8")
    # 直接插一个 uploaded 批次（文件按说还在缓冲区里）—— 不用 helper 是因为
    # 它造的是 ingested 批次，而 UPDATE staging_batch 在本线是受门禁约束的
    with database.conn:
        database.conn.execute(
            "INSERT INTO staging_batch(id, file_name, stored_name, file_size, status, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            ("a" * 32, "在用的账单.csv", stored_name, 4, "uploaded", "2026-06-01T00:00:00",
             "2026-06-01T00:00:00"),
        )

    report = run_startup_reconciliation(database, paths)

    assert report.orphans == 0
    assert report.orphan_names == ()
