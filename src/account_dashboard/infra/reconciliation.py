"""启动对账（C1 只做只读清点，自愈动作在 C3 实现）。

SDD §7.6 定义了四步对账。C1 阶段 ``raw_*`` 表还不存在、也没有入库流程，
因此这里只统计可观测的状态，真正的「中断批次置回待确认」「补删删除意图」
在 C3 补齐 —— 接口（``ReconciliationReport``）保持不变。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from account_dashboard.infra.logger import get_logger
from account_dashboard.infra.paths import DataPaths
from account_dashboard.repositories.database import Database

_logger = get_logger("reconciliation")


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    interrupted_batches: int = 0
    pending_deletes: int = 0
    orphans: int = 0
    missing_buffer_dir: bool = False


def run_startup_reconciliation(database: Database, paths: DataPaths) -> ReconciliationReport:
    interrupted = _count(database, "SELECT COUNT(*) FROM staging_batch WHERE status='ingesting'")
    pending = _count(
        database,
        "SELECT COUNT(*) FROM staging_batch WHERE status='ingested' AND pending_delete_flag=1",
    )
    orphans = _count_orphans(database, paths.buffer_dir)
    missing_dir = not paths.buffer_dir.is_dir()

    if interrupted or pending or orphans or missing_dir:
        _logger.warning(
            "启动对账：中断批次=%s 待补删=%s 孤儿文件=%s 缓冲区缺失=%s",
            interrupted,
            pending,
            orphans,
            missing_dir,
        )
    else:
        _logger.info("启动对账：无异常")
    return ReconciliationReport(
        interrupted_batches=interrupted,
        pending_deletes=pending,
        orphans=orphans,
        missing_buffer_dir=missing_dir,
    )


def _count(database: Database, sql: str) -> int:
    try:
        return database.scalar_int(sql)
    except sqlite3.Error as exc:  # pragma: no cover - 表缺失只可能出现在异常库
        _logger.warning("对账查询失败：%s", exc)
        return 0


def _count_orphans(database: Database, buffer_dir: Path) -> int:
    if not buffer_dir.is_dir():
        return 0
    rows = database.query_all("SELECT stored_name FROM staging_batch")
    known = {str(row["stored_name"]) for row in rows}
    return sum(
        1
        for entry in buffer_dir.iterdir()
        if entry.is_file() and not entry.name.endswith(".tmp") and entry.name not in known
    )
