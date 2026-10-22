"""渠道模板仓储（EX-20 / SDD §8.11）。

唯一性靠 DDL 的部分唯一索引：``channel_template(channel) WHERE is_default=1``。
因此「同渠道至多一个默认」不是应用层自觉，而是数据库保证 —— 应用层只需保证
**先降级后插入**的顺序正确，避免瞬时冲突。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from account_dashboard.infra.clock import now_iso
from account_dashboard.models.enums import Channel

_COLUMNS = "id, channel, name, spec_json, is_default, created_at, updated_at"


@dataclass(frozen=True, slots=True)
class TemplateRow:
    id: str
    channel: str
    name: str
    spec_json: str
    is_default: bool
    created_at: str
    updated_at: str


class TemplateRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list(self, channel: Channel | None = None) -> list[TemplateRow]:
        if channel is None:
            rows = self._conn.execute(
                f"SELECT {_COLUMNS} FROM channel_template ORDER BY channel, is_default DESC, name"
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT {_COLUMNS} FROM channel_template WHERE channel = ? "
                "ORDER BY is_default DESC, name",
                (str(channel),),
            ).fetchall()
        return [record for row in rows if (record := _to_row(row)) is not None]

    def get(self, template_id: str) -> TemplateRow | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM channel_template WHERE id = ?", (template_id,)
        ).fetchone()
        return _to_row(row)

    def get_default(self, channel: Channel) -> TemplateRow | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM channel_template WHERE channel = ? AND is_default = 1",
            (str(channel),),
        ).fetchone()
        return _to_row(row)

    def find_by_name(self, channel: Channel, name: str) -> TemplateRow | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM channel_template WHERE channel = ? AND name = ?",
            (str(channel), name),
        ).fetchone()
        return _to_row(row)

    def insert(
        self,
        *,
        template_id: str,
        channel: Channel,
        name: str,
        spec_json: str,
        is_default: bool,
    ) -> TemplateRow:
        stamp = now_iso()
        self._conn.execute(
            "INSERT INTO channel_template(id, channel, name, spec_json, is_default, created_at, "
            "updated_at) VALUES (?,?,?,?,?,?,?)",
            (template_id, str(channel), name, spec_json, 1 if is_default else 0, stamp, stamp),
        )
        record = self.get(template_id)
        assert record is not None
        return record

    def update_spec(self, template_id: str, *, spec_json: str, is_default: bool) -> TemplateRow:
        self._conn.execute(
            "UPDATE channel_template SET spec_json = ?, is_default = ?, updated_at = ? "
            "WHERE id = ?",
            (spec_json, 1 if is_default else 0, now_iso(), template_id),
        )
        record = self.get(template_id)
        assert record is not None
        return record

    def demote_default(self, channel: Channel) -> int:
        """把该渠道的默认模板降级（``is_default=0``，记录保留可查）。"""
        cursor = self._conn.execute(
            "UPDATE channel_template SET is_default = 0, updated_at = ? "
            "WHERE channel = ? AND is_default = 1",
            (now_iso(), str(channel)),
        )
        return cursor.rowcount


def _to_row(row: sqlite3.Row | None) -> TemplateRow | None:
    if row is None:
        return None
    return TemplateRow(
        id=str(row["id"]),
        channel=str(row["channel"]),
        name=str(row["name"]),
        spec_json=str(row["spec_json"]),
        is_default=bool(row["is_default"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
