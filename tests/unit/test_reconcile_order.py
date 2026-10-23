"""启动对账四步的顺序与隔离（C3-B §4.3）。

两条断言：

1. 四步严格按 ①②③④ 执行（spy 记录调用序，顺序不可换）；
2. 任一步抛异常不影响后续步，也不影响启动（对账不阻塞启动是硬约束）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import account_dashboard.infra.reconciliation as recon
from account_dashboard.infra.paths import DataPaths
from account_dashboard.infra.reconciliation import ReconciliationReport, run_startup_reconciliation
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.schema_migrator import SchemaMigrator

_STEPS = ("reset_interrupted", "complete_pending_deletes", "detect_inconsistent", "scan_orphans")


@pytest.fixture
def env(tmp_path: Path) -> tuple[Database, DataPaths]:
    paths = DataPaths(data_dir=tmp_path)
    paths.ensure_dirs()
    database = Database(paths.db_file)
    SchemaMigrator(database).migrate()
    yield database, paths
    database.close()


def test_four_steps_run_in_order(
    env: tuple[Database, DataPaths], monkeypatch: pytest.MonkeyPatch
) -> None:
    database, paths = env
    calls: list[str] = []

    for name in _STEPS:
        original = getattr(recon, f"_{name}")

        def spy(*args: object, _original: object = original, _name: str = name) -> object:
            calls.append(_name)
            assert callable(_original)
            return _original(*args)

        monkeypatch.setattr(recon, f"_{name}", spy)

    report = run_startup_reconciliation(database, paths)

    assert calls == [
        "reset_interrupted",
        "complete_pending_deletes",
        "detect_inconsistent",
        "scan_orphans",
    ], "四步顺序不可换"
    assert isinstance(report, ReconciliationReport)


def test_failing_step_does_not_block_later_steps(
    env: tuple[Database, DataPaths], monkeypatch: pytest.MonkeyPatch
) -> None:
    """第 ② 步炸了，③ ④ 照样跑；报告照样返回 —— 启动不阻塞。"""
    database, paths = env
    calls: list[str] = []

    for name in _STEPS:
        original = getattr(recon, f"_{name}")

        def spy(*args: object, _original: object = original, _name: str = name) -> object:
            calls.append(_name)
            if _name == "complete_pending_deletes":
                raise RuntimeError("模拟补删整体失败")
            assert callable(_original)
            return _original(*args)

        monkeypatch.setattr(recon, f"_{name}", spy)

    report = run_startup_reconciliation(database, paths)

    assert calls == list(_STEPS), "异常被单步隔离，后续步不受影响"
    assert report.deleted_files == 0
    assert report.enqueued_files == 0


def test_missing_buffer_dir_skips_delete_and_orphan_steps(
    env: tuple[Database, DataPaths], monkeypatch: pytest.MonkeyPatch
) -> None:
    """缓冲区目录被移走：② ④ 跳过，① ③ 不依赖目录仍可跑。"""
    database, paths = env
    calls: list[str] = []
    for name in _STEPS:
        original = getattr(recon, f"_{name}")

        def spy(*args: object, _original: object = original, _name: str = name) -> object:
            calls.append(_name)
            assert callable(_original)
            return _original(*args)

        monkeypatch.setattr(recon, f"_{name}", spy)

    report = run_startup_reconciliation(database, DataPaths(data_dir=paths.data_dir / "gone"))

    assert calls == ["reset_interrupted", "detect_inconsistent"]
    assert report.missing_buffer_dir is True
    assert report.orphans == 0
