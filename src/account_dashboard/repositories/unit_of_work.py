"""工作单元：业务层事务的唯一入口（I9 / I10 / ADR-09）。

约定：

* 一个 ``with uow.begin():`` 对应一个 ``BEGIN IMMEDIATE``；
* 正常退出 COMMIT，任何异常 ROLLBACK 后原样抛出；
* 禁止嵌套（嵌套会让"哪个事务负责回滚"变得不可判定）。

仓储不在这里创建 —— 业务服务按需注入 ``uow.conn``，避免 UoW 变成上帝对象。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from account_dashboard.repositories.database import Database


class UnitOfWork:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._depth = 0

    @property
    def conn(self) -> sqlite3.Connection:
        return self._database.conn

    @property
    def in_transaction(self) -> bool:
        return self._depth > 0

    @contextmanager
    def begin(self) -> Iterator[UnitOfWork]:
        if self._depth:
            raise RuntimeError("事务不可嵌套：UnitOfWork.begin() 已在事务中")
        with self._database.transaction():
            self._depth += 1
            try:
                yield self
            finally:
                self._depth -= 1
