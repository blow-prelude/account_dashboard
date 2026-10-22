"""健康快照（唯一允许 ``api`` 探活的入口）。

把「查库 + 数目录」的细节留在业务层，路由只负责包一层统一响应 ——
这样 ``api/routers`` 不必 import ``sqlite3`` 或 ``repositories``（SDD §2.2）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from account_dashboard import __version__
from account_dashboard.infra.logger import get_logger
from account_dashboard.infra.paths import DataPaths
from account_dashboard.models.common import BacklogDTO, HealthDTO
from account_dashboard.repositories.database import Database

_logger = get_logger("health")


class HealthService:
    def __init__(self, database: Database | None, paths: DataPaths | None) -> None:
        self._database = database
        self._paths = paths

    @classmethod
    def from_app_state(cls, state: object) -> HealthService:
        database = getattr(state, "database", None)
        paths = getattr(state, "paths", None)
        return cls(
            database if isinstance(database, Database) else None,
            paths if isinstance(paths, DataPaths) else None,
        )

    def snapshot(self) -> HealthDTO:
        db_ok = self._database_ok()
        return HealthDTO(
            status="ok" if db_ok else "degraded",
            version=__version__,
            data_dir=str(self._paths.data_dir) if self._paths is not None else "",
            db_ok=db_ok,
            backlog=BacklogDTO(
                cleanup=self._cleanup_backlog() if db_ok else 0,
                orphans=self._orphan_count() if db_ok else 0,
            ),
        )

    def _database_ok(self) -> bool:
        if self._database is None:
            return False
        try:
            return self._database.query_one("SELECT 1") is not None
        except (sqlite3.Error, RuntimeError) as exc:
            _logger.warning("健康检查数据库不可用：%s", exc)
            return False

    def _cleanup_backlog(self) -> int:
        assert self._database is not None
        try:
            return self._database.scalar_int(
                "SELECT COUNT(*) FROM cleanup_queue WHERE status = 'pending'"
            )
        except sqlite3.Error:
            return 0

    def _orphan_count(self) -> int:
        """缓冲区里存在、但没有任何批次记录的文件数（EX-13 的只读视图）。"""
        assert self._database is not None
        buffer_dir = self._paths.buffer_dir if self._paths is not None else None
        if not isinstance(buffer_dir, Path) or not buffer_dir.is_dir():
            return 0
        try:
            known = {
                str(row["stored_name"])
                for row in self._database.query_all("SELECT stored_name FROM staging_batch")
            }
        except sqlite3.Error:
            return 0
        return sum(
            1
            for entry in buffer_dir.iterdir()
            if entry.is_file() and not entry.name.endswith(".tmp") and entry.name not in known
        )
