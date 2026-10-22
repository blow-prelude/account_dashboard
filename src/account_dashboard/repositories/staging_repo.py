"""缓冲区批次仓储（SDD §4.4.4）。

三条纪律：

* **无物理删除** —— 批次是审计对象，丢弃只改状态（``discarded``）；
* **状态写入必须带 ``expected_from``** —— 条件更新是并发/重试的唯一防线（C3 的幂等闸门同源）；
* SQL 全参数化，列名白名单写死。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from account_dashboard.infra.clock import now_iso
from account_dashboard.models.enums import BatchStatus, Channel

_BATCH_COLUMNS = (
    "id, file_name, stored_name, file_size, channel, status, total_rows, new_count, dup_count, "
    "pending_count, encoding, adapter, header_row_no, mapped_fields, mapping_snapshot, "
    "parse_meta, report_json, fail_reason, created_at, updated_at"
)


@dataclass(frozen=True, slots=True)
class BatchRow:
    id: str
    file_name: str
    stored_name: str
    file_size: int
    channel: str
    status: str
    total_rows: int
    new_count: int
    dup_count: int
    pending_count: int
    encoding: str | None
    adapter: str | None
    header_row_no: int | None
    mapped_fields: str | None
    mapping_snapshot: str | None
    parse_meta: str | None
    report_json: str | None
    fail_reason: str | None
    created_at: str
    updated_at: str

    @property
    def status_enum(self) -> BatchStatus:
        return BatchStatus(self.status)

    @property
    def channel_enum(self) -> Channel:
        return Channel(self.channel)


class StagingRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── 写 ────────────────────────────────────────────────────
    def create(
        self,
        *,
        batch_id: str,
        file_name: str,
        stored_name: str,
        file_size: int,
        channel: Channel,
        created_at: str | None = None,
    ) -> None:
        stamp = created_at or now_iso()
        self._conn.execute(
            "INSERT INTO staging_batch(id, file_name, stored_name, file_size, channel, status, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                batch_id,
                file_name,
                stored_name,
                file_size,
                str(channel),
                str(BatchStatus.UPLOADED),
                stamp,
                stamp,
            ),
        )

    def set_status(
        self,
        batch_id: str,
        *,
        to: BatchStatus,
        expected_from: BatchStatus | None = None,
        reason: str | None = None,
    ) -> int:
        """条件状态更新；返回受影响行数（0 表示状态不符或批次不存在）。"""
        sets = ["status = ?", "updated_at = ?"]
        params: list[Any] = [str(to), now_iso()]
        if reason is not None:
            sets.append("fail_reason = ?")
            params.append(reason)
        where = "id = ?"
        params.append(batch_id)
        if expected_from is not None:
            where += " AND status = ?"
            params.append(str(expected_from))
        cursor = self._conn.execute(
            f"UPDATE staging_batch SET {', '.join(sets)} WHERE {where}",  # noqa: S608 - 列名固定
            tuple(params),
        )
        return cursor.rowcount

    def update_after_parse(
        self,
        batch_id: str,
        *,
        channel: Channel,
        encoding: str,
        adapter: str,
        header_row_no: int,
        total_rows: int,
        parse_meta: str,
        expected_from: BatchStatus | None = None,
    ) -> int:
        where = "id = ?"
        params: list[Any] = [
            str(channel),
            encoding,
            adapter,
            header_row_no,
            total_rows,
            parse_meta,
            now_iso(),
            batch_id,
        ]
        if expected_from is not None:
            where += " AND status = ?"
            params.append(str(expected_from))
        cursor = self._conn.execute(
            "UPDATE staging_batch SET channel = ?, encoding = ?, adapter = ?, header_row_no = ?, "
            "total_rows = ?, parse_meta = ?, fail_reason = NULL, updated_at = ?, "
            # 重解析（prechecked → mapped_pending）必须把上一轮预检的产物一并作废：
            # 计数留着会让用户看到旧数字，快照留着会让 C3 的 replay() 按旧口径入库，
            # 并绕过「必须先 precheck」这道闸门（合稿验收 #7 / D-5）。
            "new_count = 0, dup_count = 0, pending_count = 0, mapping_snapshot = NULL "
            f"WHERE {where}",  # noqa: S608 - 占位符拼接，无外部输入
            tuple(params),
        )
        return cursor.rowcount

    def update_mapping(
        self,
        batch_id: str,
        *,
        mapped_fields: str,
        channel: Channel | None = None,
        header_row_no: int | None = None,
        expected_status: BatchStatus | None = None,
    ) -> int:
        sets = ["mapped_fields = ?", "updated_at = ?"]
        params: list[Any] = [mapped_fields, now_iso()]
        if channel is not None:
            sets.append("channel = ?")
            params.append(str(channel))
        if header_row_no is not None:
            sets.append("header_row_no = ?")
            params.append(header_row_no)
        where = "id = ?"
        params.append(batch_id)
        if expected_status is not None:
            where += " AND status = ?"
            params.append(str(expected_status))
        cursor = self._conn.execute(
            f"UPDATE staging_batch SET {', '.join(sets)} WHERE {where}",  # noqa: S608
            tuple(params),
        )
        return cursor.rowcount

    def reset_precheck(self, batch_id: str, *, status: BatchStatus) -> int:
        """映射变更后清空预检结果（EX-22 的前置防护）：计数归零、快照作废。"""
        cursor = self._conn.execute(
            "UPDATE staging_batch SET new_count = 0, dup_count = 0, pending_count = 0, "
            "mapping_snapshot = NULL, status = ?, updated_at = ? WHERE id = ?",
            (str(status), now_iso(), batch_id),
        )
        return cursor.rowcount

    def update_precheck(
        self,
        batch_id: str,
        *,
        new_count: int,
        dup_count: int,
        pending_count: int,
        mapping_snapshot: str,
        status: BatchStatus = BatchStatus.PRECHECKED,
    ) -> int:
        cursor = self._conn.execute(
            "UPDATE staging_batch SET new_count = ?, dup_count = ?, pending_count = ?, "
            "mapping_snapshot = ?, status = ?, updated_at = ? WHERE id = ?",
            (
                new_count,
                dup_count,
                pending_count,
                mapping_snapshot,
                str(status),
                now_iso(),
                batch_id,
            ),
        )
        return cursor.rowcount

    # ── 读 ────────────────────────────────────────────────────
    def get(self, batch_id: str) -> BatchRow | None:
        row = self._conn.execute(
            f"SELECT {_BATCH_COLUMNS} FROM staging_batch WHERE id = ?", (batch_id,)
        ).fetchone()
        return _to_row(row)

    def list(
        self,
        *,
        status: BatchStatus | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[BatchRow], int]:
        where = ""
        params: list[Any] = []
        if status is not None:
            where = " WHERE status = ?"
            params.append(str(status))
        total_row = self._conn.execute(
            f"SELECT COUNT(*) AS n FROM staging_batch{where}",  # noqa: S608
            tuple(params),
        ).fetchone()
        total = int(total_row["n"]) if total_row is not None else 0
        rows = self._conn.execute(
            f"SELECT {_BATCH_COLUMNS} FROM staging_batch{where} "  # noqa: S608
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (*params, page_size, (page - 1) * page_size),
        ).fetchall()
        return [record for row in rows if (record := _to_row(row)) is not None], total

    def known_stored_names(self) -> set[str]:
        rows = self._conn.execute("SELECT stored_name FROM staging_batch").fetchall()
        return {str(row["stored_name"]) for row in rows}


def _to_row(row: sqlite3.Row | None) -> BatchRow | None:
    if row is None:
        return None
    return BatchRow(
        id=str(row["id"]),
        file_name=str(row["file_name"]),
        stored_name=str(row["stored_name"]),
        file_size=int(row["file_size"]),
        channel=str(row["channel"]),
        status=str(row["status"]),
        total_rows=int(row["total_rows"]),
        new_count=int(row["new_count"]),
        dup_count=int(row["dup_count"]),
        pending_count=int(row["pending_count"]),
        encoding=row["encoding"],
        adapter=row["adapter"],
        header_row_no=row["header_row_no"],
        mapped_fields=row["mapped_fields"],
        mapping_snapshot=row["mapping_snapshot"],
        parse_meta=row["parse_meta"],
        report_json=row["report_json"],
        fail_reason=row["fail_reason"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
