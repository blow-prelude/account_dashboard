"""强制新增留痕仓储（P0-1 / C2-B §4.6）。

幂等键就是主键 ``(batch_id, row_no)``：重复标记同一行时**只更新 reason**，不新增行。
撤销是物理删除（留痕的价值在"谁在什么时候强制新增了哪一行"，撤销后该行本来就
不再被强制，保留空记录只会让审计表越长越乱）。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from account_dashboard.infra.clock import now_iso

_COLUMNS = "batch_id, row_no, reason, note, created_at"


class OverrideRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, batch_id: str, row_no: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM override_mark WHERE batch_id = ? AND row_no = ?",
            (batch_id, row_no),
        ).fetchone()
        return dict(row) if row is not None else None

    def exists(self, batch_id: str, row_no: int) -> bool:
        return self.get(batch_id, row_no) is not None

    def upsert(
        self, batch_id: str, row_no: int, reason: str, note: str | None = None
    ) -> dict[str, Any]:
        """主键即幂等键：存在则只改 reason / note，``created_at`` 保持首次标记时间。"""
        self._conn.execute(
            "INSERT INTO override_mark (batch_id, row_no, reason, note, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(batch_id, row_no) DO UPDATE SET reason = excluded.reason, "
            "note = excluded.note",
            (batch_id, row_no, reason, note, now_iso()),
        )
        stored = self.get(batch_id, row_no)
        assert stored is not None
        return stored

    def list_by_batch(self, batch_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM override_mark WHERE batch_id = ? ORDER BY row_no ASC",
            (batch_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def row_numbers(self, batch_id: str) -> set[int]:
        rows = self._conn.execute(
            "SELECT row_no FROM override_mark WHERE batch_id = ?", (batch_id,)
        ).fetchall()
        return {int(row[0]) for row in rows}

    def delete(self, batch_id: str, row_no: int) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM override_mark WHERE batch_id = ? AND row_no = ?", (batch_id, row_no)
        )
        return cursor.rowcount > 0


__all__ = ["OverrideRepo"]
