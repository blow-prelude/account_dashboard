"""主数据层仓储（C2 只开放**只读**指纹查询）。

C2 的边界：本线不得越界入库 —— ``SELECT COUNT(*) FROM "transaction"`` 在 C2 收口时
必须为 0。因此这里只有 ``find_fp_in``：预检用它判断"这一行是否已经入过库"，
其余写方法（``insert_many`` / ``patch`` …）留给 C3。

为什么分片在这里而不是调用方：``IN`` 的参数个数上限随 SQLite 版本变化（旧版本 999），
把分片放在 SQL 旁边，就不会出现"换个调用点就超限"的问题。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from account_dashboard.limits import FP_QUERY_CHUNK


class TransactionRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def find_fp_in(self, fps: Sequence[str], chunk_size: int = FP_QUERY_CHUNK) -> set[str]:
        """返回 ``fps`` 中**已存在**于 ``transaction.fp`` 的那部分。

        只读：不 INSERT、不 UPDATE，也不写 ``raw_*``（I-PC-01 靠这条保证）。
        """
        targets = [fp for fp in dict.fromkeys(fps) if fp]
        if not targets:
            return set()

        size = max(1, chunk_size)
        found: set[str] = set()
        for start in range(0, len(targets), size):
            chunk = targets[start : start + size]
            placeholders = ", ".join("?" for _ in chunk)
            rows = self._conn.execute(
                f'SELECT fp FROM "transaction" WHERE fp IN ({placeholders})', chunk
            ).fetchall()
            found.update(str(row[0]) for row in rows if row[0])
        return found

    def count_all(self) -> int:
        """只在测试与报告里用：C2 期间必须恒为 0。"""
        row = self._conn.execute('SELECT COUNT(*) FROM "transaction"').fetchone()
        return int(row[0])


__all__ = ["TransactionRepo"]
