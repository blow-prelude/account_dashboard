"""渠道模板仓储（EX-20 / SDD §4.4.4）。

DDL 已有部分唯一索引 ``uq_template_default ON channel_template(channel) WHERE is_default=1``，
所以"先降级后插入"必须发生在**同一事务**内：否则中间态（两条 default）会撞索引，
把一次正常的模板保存变成 500。

``uq_template_name`` 约束 ``(channel, name)`` 唯一，因此重名时由
:meth:`TemplateRepo.unique_name` 自动加 ``(2)``、``(3)`` 后缀 —— 这也是 ``save_as``
策略"重名自动加后缀"的落地处。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from account_dashboard.infra.clock import now_iso
from account_dashboard.infra.logger import get_logger
from account_dashboard.models.internal import MappingSpec

_logger = get_logger("template_repo")

_COLUMNS = "id, channel, name, spec_json, is_default, created_at, updated_at"
_NAME_MAX = 60


def _to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    try:
        data["spec"] = MappingSpec.model_validate_json(data["spec_json"])
    except (TypeError, ValueError) as exc:
        _logger.warning("模板 spec 损坏，已跳过该条：%s", exc)
        data["spec"] = None
    data["is_default"] = bool(data["is_default"])
    return data


class TemplateRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list(self, channel: str | None = None) -> list[dict[str, Any]]:
        if channel:
            rows = self._conn.execute(
                f"SELECT {_COLUMNS} FROM channel_template WHERE channel = ? "
                "ORDER BY is_default DESC, created_at ASC",
                (channel,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT {_COLUMNS} FROM channel_template ORDER BY channel ASC, "
                "is_default DESC, created_at ASC"
            ).fetchall()
        return [item for item in (_to_dict(row) for row in rows) if item["spec"] is not None]

    def get(self, template_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM channel_template WHERE id = ?", (template_id,)
        ).fetchone()
        return _to_dict(row) if row is not None else None

    def get_default(self, channel: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM channel_template WHERE channel = ? AND is_default = 1",
            (channel,),
        ).fetchone()
        return _to_dict(row) if row is not None else None

    def name_exists(self, channel: str, name: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM channel_template WHERE channel = ? AND name = ? LIMIT 1",
            (channel, name),
        ).fetchone()
        return row is not None

    def unique_name(self, channel: str, base: str) -> str:
        """``base`` 未被占用则原样返回，否则 ``base (2)``、``base (3)``…"""
        cleaned = (base.strip() or "未命名模板")[:_NAME_MAX]
        if not self.name_exists(channel, cleaned):
            return cleaned
        for index in range(2, 1000):
            candidate = f"{cleaned[: _NAME_MAX - 6]} ({index})"
            if not self.name_exists(channel, candidate):
                return candidate
        raise RuntimeError("模板名称后缀已用尽，请删除部分历史模板")  # pragma: no cover

    def demote_defaults(self, channel: str) -> int:
        cursor = self._conn.execute(
            "UPDATE channel_template SET is_default = 0, updated_at = ? "
            "WHERE channel = ? AND is_default = 1",
            (now_iso(), channel),
        )
        return cursor.rowcount

    def create(
        self,
        *,
        channel: str,
        name: str,
        spec: MappingSpec,
        is_default: bool,
        template_id: str,
    ) -> dict[str, Any]:
        now = now_iso()
        self._conn.execute(
            "INSERT INTO channel_template (id, channel, name, spec_json, is_default, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                template_id,
                channel,
                name,
                json.dumps(spec.model_dump(), ensure_ascii=False, sort_keys=True),
                1 if is_default else 0,
                now,
                now,
            ),
        )
        created = self.get(template_id)
        assert created is not None
        return created


__all__ = ["TemplateRepo"]
