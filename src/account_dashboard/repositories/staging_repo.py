"""缓冲区批次仓储（SDD §4.4.4）。

三条纪律：

* **无物理删除** —— 批次是审计对象，丢弃只改状态（``discarded``）；
* **状态写入必须带 ``expected_from``** —— 条件更新是并发/重试的唯一防线（C3 的幂等闸门同源）；
* SQL 全参数化，列名白名单写死。

C3-A 在本仓储增加两个写路径方法（``try_enter_ingesting`` / ``finish_ingest``），
它们是 ``staging_batch`` 状态机的最后两个写入点；``pending_delete_flag`` 的语义
见 ``finish_ingest`` 的注释。
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
    "parse_meta, report_json, pending_delete_flag, deleted_at, fail_reason, ingest_started_at, "
    "committed_at, created_at, updated_at"
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
    # 删除意图（I9）：仅表示缓冲区物理文件的删除意图，与"待删除主数据"无关。
    # 只有 finish_ingest 能置 1；清零归 B 线的 cleanup_repo。
    pending_delete_flag: int = 0
    deleted_at: str | None = None
    fail_reason: str | None = None
    ingest_started_at: str | None = None
    committed_at: str | None = None
    created_at: str = ""
    updated_at: str = ""

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

    # ── 入库写路径（C3-A） ─────────────────────────────────────
    def try_enter_ingesting(self, batch_id: str, *, now: str | None = None) -> int:
        """幂等闸门：``prechecked → ingesting`` 的条件 UPDATE。

        **不是"先查后改"**（那有 TOCTOU：并发两次都查到 prechecked）。这里靠
        条件 UPDATE + ``rowcount`` 判定，配合 ``BEGIN IMMEDIATE`` 的写锁天然串行化：
        并发双提交时，后到者的事务开始前闸门已把状态改写，``rowcount == 0`` → E2002。

        必须在**已开启**的事务内调用（由 ``IngestService`` 负责开事务）：闸门与
        后续写入在同一事务里，进程崩溃时 SQLite 自动回滚，批次仍是 ``prechecked``
        —— 不会留下永久 ``ingesting`` 脏状态（PRD 9.2 收口规则 4 / D-8）。
        守卫本身不开事务、不提交。
        """
        stamp = now or now_iso()
        cursor = self._conn.execute(
            "UPDATE staging_batch SET status = ?, ingest_started_at = ?, updated_at = ? "
            "WHERE id = ? AND status = ?",
            (
                str(BatchStatus.INGESTING),
                stamp,
                stamp,
                batch_id,
                str(BatchStatus.PRECHECKED),
            ),
        )
        return cursor.rowcount

    def finish_ingest(
        self,
        batch_id: str,
        *,
        report_json: str,
        mapping_snapshot: str,
        committed_at: str,
        pending_delete_flag: int = 1,
    ) -> int:
        """入库收口：``ingested`` + 冻结报告与快照 + 删除意图旗标。

        * ``mapping_snapshot`` 在此**原样回写**（D-5）：C2 预检写的那份可能已被
          用户后续操作污染，入库事务内读到的这份才是 I11 要的"入库时刻不可变快照"；
          回写之后该字段只读（grep 门禁见 tests/integration/test_write_path_gates.py）。
        * ``pending_delete_flag`` 只有本方法能置 1，且**仅表示缓冲区物理文件的删除
          意图**，与"待删除主数据"无关；清零归 B 线 ``cleanup_repo``。
        """
        cursor = self._conn.execute(
            "UPDATE staging_batch SET status = ?, report_json = ?, mapping_snapshot = ?, "
            "committed_at = ?, pending_delete_flag = ?, updated_at = ? WHERE id = ?",
            (
                str(BatchStatus.INGESTED),
                report_json,
                mapping_snapshot,
                committed_at,
                pending_delete_flag,
                committed_at,
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
        pending_delete_flag=int(row["pending_delete_flag"] or 0),
        deleted_at=row["deleted_at"],
        fail_reason=row["fail_reason"],
        ingest_started_at=row["ingest_started_at"],
        committed_at=row["committed_at"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
