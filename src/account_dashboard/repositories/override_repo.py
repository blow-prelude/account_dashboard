"""强制新增留痕仓储（P0-1 / EX-21）。

``(batch_id, row_no)`` 是主键，因此「对同一行重复标记」天然幂等 —— 覆盖原因与备注即可。
留痕是**补救手段的审计证据**：用户误判为重复时必须能说清「谁在什么时候、为什么放行」。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from account_dashboard.infra.clock import now_iso


@dataclass(frozen=True, slots=True)
class OverrideRow:
    batch_id: str
    row_no: int
    reason: str
    note: str
    created_at: str


class OverrideRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, batch_id: str, row_no: int, reason: str, note: str = "") -> OverrideRow:
        stamp = now_iso()
        self._conn.execute(
            "INSERT INTO override_mark(batch_id, row_no, reason, note, created_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(batch_id, row_no) DO UPDATE SET "
            "reason = excluded.reason, note = excluded.note, created_at = excluded.created_at",
            (batch_id, row_no, reason, note, stamp),
        )
        record = self.get(batch_id, row_no)
        assert record is not None
        return record

    def get(self, batch_id: str, row_no: int) -> OverrideRow | None:
        row = self._conn.execute(
            "SELECT batch_id, row_no, reason, note, created_at FROM override_mark "
            "WHERE batch_id = ? AND row_no = ?",
            (batch_id, row_no),
        ).fetchone()
        return _to_row(row)

    def list_by_batch(self, batch_id: str) -> dict[int, OverrideRow]:
        rows = self._conn.execute(
            "SELECT batch_id, row_no, reason, note, created_at FROM override_mark "
            "WHERE batch_id = ? ORDER BY row_no",
            (batch_id,),
        ).fetchall()
        result: dict[int, OverrideRow] = {}
        for row in rows:
            record = _to_row(row)
            if record is not None:
                result[record.row_no] = record
        return result

    def delete(self, batch_id: str, row_no: int) -> int:
        cursor = self._conn.execute(
            "DELETE FROM override_mark WHERE batch_id = ? AND row_no = ?", (batch_id, row_no)
        )
        return cursor.rowcount


def _to_row(row: sqlite3.Row | None) -> OverrideRow | None:
    if row is None:
        return None
    return OverrideRow(
        batch_id=str(row["batch_id"]),
        row_no=int(row["row_no"]),
        reason=str(row["reason"]),
        note=str(row["note"] or ""),
        created_at=str(row["created_at"]),
    )
