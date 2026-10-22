"""SQLite 连接（ADR-02 / ADR-11）。

单连接 + ``RLock``，不使用连接池：本项目是单用户单账本，
连接池带来的锁竞争与生命周期问题远大于收益。事务边界由
:class:`~account_dashboard.repositories.unit_of_work.UnitOfWork` 显式控制。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any

from account_dashboard.infra.logger import get_logger

_logger = get_logger("db")

BUSY_TIMEOUT_MS = 5000
_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}",
)


class Database:
    def __init__(self, db_path: Path) -> None:
        self.path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._closed = False
        self._conn = sqlite3.connect(
            str(db_path),
            isolation_level=None,  # 手动控制 BEGIN/COMMIT
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        for pragma in _PRAGMAS:
            self._conn.execute(pragma)

    # ── 基础访问 ────────────────────────────────────────────────
    @property
    def conn(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("数据库连接已关闭")
        return self._conn

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, tuple(params or ()))

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.executemany(sql, rows)

    def query_all(self, sql: str, params: Sequence[Any] | None = None) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(sql, tuple(params or ())).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] | None = None) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, tuple(params or ())).fetchone()

    def scalar_int(self, sql: str, params: Sequence[Any] | None = None) -> int:
        row = self.query_one(sql, params)
        if row is None:
            return 0
        value = row[0]
        return int(value) if value is not None else 0

    # ── 事务 ──────────────────────────────────────────────────
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """``BEGIN IMMEDIATE`` 事务；异常必回滚，禁止嵌套。

        用 IMMEDIATE 而非默认 DEFERRED：写锁在事务开始即取得，
        C3 的幂等闸门依赖「取锁即串行」。
        """
        with self._lock:
            if self.conn.in_transaction:
                raise RuntimeError("事务不可嵌套：请在 UnitOfWork 外层统一开启")
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    # ── 维护 ──────────────────────────────────────────────────
    def integrity_check(self) -> bool:
        row = self.query_one("PRAGMA integrity_check")
        if row is None:
            return False
        return str(row[0]).lower() == "ok"

    def close(self) -> None:
        if self._closed:
            return
        with self._lock:
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error as exc:  # pragma: no cover - 只读/损坏库
                _logger.warning("wal checkpoint 失败：%s", exc)
            self._conn.close()
            self._closed = True

    def __enter__(self) -> Database:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def create_database(db_path: Path) -> Database:
    _logger.info("打开数据库 %s", db_path)
    return Database(db_path)
