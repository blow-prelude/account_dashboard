"""批次仓储与状态机落地点（C2-B §4.2 / SDD §4.4.4）。

三条硬规矩：

1. **改状态只能走这里的具名方法**，方法内部先 ``assert_transition`` 再执行
   ``UPDATE ... WHERE id = ? AND status = ?``（条件更新），业务层无法绕过；
2. **无物理删除**：批次是审计对象，丢弃只是 ``status='discarded'``；
3. JSON 字段（``mapped_fields`` / ``parse_meta`` / ``report_json``）读写必须无损 ——
   ``json.loads`` 失败时返回 ``None`` 并记 WARN，绝不让脏数据把接口打成 500。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any
from uuid import uuid4

from account_dashboard.errors import BusinessRuleError, ErrorCode
from account_dashboard.infra.clock import now_iso
from account_dashboard.infra.logger import get_logger
from account_dashboard.models.staging import assert_transition

_logger = get_logger("staging_repo")

_COLUMNS = (
    "id, file_name, stored_name, file_size, channel, status, total_rows, new_count, "
    "dup_count, pending_count, encoding, adapter, header_row_no, mapped_fields, "
    "mapping_snapshot, parse_meta, report_json, pending_delete_flag, deleted_at, "
    "fail_reason, ingest_started_at, committed_at, created_at, updated_at"
)

# 排序白名单：主键 + 同秒批次的稳定次序（created_at 只到秒，批量上传必然撞车）
_ALLOWED_SORTS = {
    "created_at": "created_at ASC, rowid ASC",
    "-created_at": "created_at DESC, rowid DESC",
}


def _loads(value: Any) -> Any:
    if value is None or value == "":
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError) as exc:
        _logger.warning("批次 JSON 字段损坏，已按 None 处理：%s", exc)
        return None


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for key in ("mapped_fields", "mapping_snapshot", "parse_meta", "report_json"):
        if key in data:
            data[key] = _loads(data[key])
    return data


class StagingRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── 读 ────────────────────────────────────────────────────
    def get(self, batch_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM staging_batch WHERE id = ?", (batch_id,)
        ).fetchone()
        return _to_dict(row) if row is not None else None

    def get_or_raise(self, batch_id: str) -> dict[str, Any]:
        batch = self.get(batch_id)
        if batch is None:
            raise BusinessRuleError(
                ErrorCode.BATCH_NOT_FOUND,
                "找不到该批次，可能已被清理，请刷新列表",
                detail={"batch_id": batch_id},
            )
        return batch

    def list(
        self,
        *,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
        sort: str = "-created_at",
    ) -> tuple[list[dict[str, Any]], int]:
        order = _ALLOWED_SORTS.get(sort, _ALLOWED_SORTS["-created_at"])
        where = "WHERE status = ?" if status else ""
        params: list[Any] = [status] if status else []

        total = self._conn.execute(
            f"SELECT COUNT(*) FROM staging_batch {where}", params
        ).fetchone()[0]
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM staging_batch {where} ORDER BY {order}, rowid DESC "
            "LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
        return [_to_dict(row) for row in rows], int(total)

    def stored_names(self) -> set[str]:
        rows = self._conn.execute("SELECT stored_name FROM staging_batch").fetchall()
        return {str(row[0]) for row in rows}

    def count_by_status(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) FROM staging_batch GROUP BY status"
        ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    # ── 写（全部经状态机）────────────────────────────────────
    def create(
        self,
        *,
        file_name: str,
        stored_name: str,
        file_size: int,
        channel: str = "other",
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        now = now_iso()
        new_id = batch_id or uuid4().hex
        self._conn.execute(
            "INSERT INTO staging_batch (id, file_name, stored_name, file_size, channel, "
            "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'uploaded', ?, ?)",
            (new_id, file_name, stored_name, file_size, channel, now, now),
        )
        return self.get_or_raise(new_id)

    def mark_parsed(
        self,
        batch_id: str,
        *,
        encoding: str,
        adapter: str,
        header_row_no: int,
        parse_meta: dict[str, Any],
        total_rows: int,
        channel: str | None = None,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {
            "encoding": encoding,
            "adapter": adapter,
            "header_row_no": header_row_no,
            "parse_meta": _dumps(parse_meta),
            "total_rows": total_rows,
            "fail_reason": None,
        }
        current = self.get_or_raise(batch_id)
        if channel and current["channel"] == "other":
            # 用户没指定渠道时，采用适配器识别出的渠道（wechat/alipay/bank）
            values["channel"] = channel
        return self._apply(batch_id, action="parse", target="mapped_pending", values=values)

    def mark_parse_failed(self, batch_id: str, *, fail_reason: str) -> dict[str, Any]:
        return self._apply(
            batch_id,
            action="parse",
            target="failed",
            values={"fail_reason": fail_reason[:500]},
        )

    def mark_mapped(self, batch_id: str, *, mapped_fields: dict[str, Any]) -> dict[str, Any]:
        # D-1：映射保存成功即视为"映射已确认"，直接进入 prechecked
        return self._apply(
            batch_id,
            action="map",
            target="prechecked",
            values={"mapped_fields": _dumps(mapped_fields)},
        )

    def mark_prechecked(
        self,
        batch_id: str,
        *,
        new_count: int,
        dup_count: int,
        pending_count: int,
    ) -> dict[str, Any]:
        """预检结果缓存；``total_rows`` 刻意不改（预检前后必须相等，I-PC-01）。"""
        return self._apply(
            batch_id,
            action="precheck",
            target="prechecked",
            values={
                "new_count": new_count,
                "dup_count": dup_count,
                "pending_count": pending_count,
            },
        )

    def mark_discarded(self, batch_id: str) -> dict[str, Any]:
        return self._apply(
            batch_id, action="discard", target="discarded", values={"deleted_at": now_iso()}
        )

    def mark_pending_delete(self, batch_id: str) -> None:
        """C3 在入库事务内落"待删除意图"（I9）；C2 不调用，仅留签名。"""
        self._conn.execute(
            "UPDATE staging_batch SET pending_delete_flag = 1, updated_at = ? WHERE id = ?",
            (now_iso(), batch_id),
        )

    def clear_pending_delete(self, batch_id: str) -> None:
        self._conn.execute(
            "UPDATE staging_batch SET pending_delete_flag = 0, updated_at = ? WHERE id = ?",
            (now_iso(), batch_id),
        )

    def finish_ingest(self, batch_id: str, **_kwargs: Any) -> None:
        """由 C3 实现（C2 只留签名，见 C2-B §5.2）。"""
        raise NotImplementedError("finish_ingest 由 C3（入库事务）实现")

    # ── 内部 ──────────────────────────────────────────────────
    def _apply(
        self, batch_id: str, *, action: str, target: str, values: dict[str, Any]
    ) -> dict[str, Any]:
        current = self.get_or_raise(batch_id)
        assert_transition(current["status"], action, target)

        assignments: dict[str, Any] = {"status": target, "updated_at": now_iso(), **values}
        columns = ", ".join(f"{column} = ?" for column in assignments)
        cursor = self._conn.execute(
            f"UPDATE staging_batch SET {columns} WHERE id = ? AND status = ?",
            (*assignments.values(), batch_id, current["status"]),
        )
        if cursor.rowcount != 1:
            # 理论上不会发生（BEGIN IMMEDIATE 已串行化），留着防"事务外调用"的误用
            raise BusinessRuleError(
                ErrorCode.BATCH_STATE_CONFLICT,
                "批次状态已变化，请刷新后重试",
                detail={"batch_id": batch_id},
            )
        return self.get_or_raise(batch_id)


__all__ = ["StagingRepo"]
