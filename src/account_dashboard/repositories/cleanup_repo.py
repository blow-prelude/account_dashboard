"""待清理队列与「删除意图」的落点（C3-B，EX-11 / K4 / K5）。

本文件是 B 线**唯一**允许写 ``staging_batch`` 的地方，且只准含两个模式
（合稿 §7 的 grep 门禁）：

* ``clear_pending_delete``  → ``SET pending_delete_flag=0, deleted_at=?``；
* ``reset_interrupted``     → ``SET status='prechecked' WHERE status='ingesting'``。

其余任何 ``status`` 变更走 A 线的 ``staging_repo``。``pending_delete_flag``
的语义写死在 DDL 注释里：**仅表示缓冲区物理文件的删除意图**，与主数据无关。

事务纪律（B 线 §4.1）：``flag`` 清零与入队是**两个独立小事务**，调用方各自
``with uow.begin():`` —— 合并会让"清零成功但入队失败"的中间态无法解释。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from account_dashboard.infra.clock import now_iso

# cleanup_queue 的合法状态（DDL CHECK 同步）
CLEANUP_STATUSES = ("pending", "done", "abandoned")

_CLEANUP_COLUMNS = (
    "c.id, c.batch_id, c.file_path, c.reason, c.attempts, c.last_error, c.status, "
    "c.created_at, c.updated_at, b.file_name AS file_name"
)


@dataclass(frozen=True, slots=True)
class CleanupRow:
    id: str
    batch_id: str | None
    file_path: str
    reason: str
    attempts: int
    last_error: str | None
    status: str
    created_at: str
    updated_at: str
    # DDL 无此列：由 LEFT JOIN staging_batch 派生（前端 c.file_name || c.file_path 兜底）
    file_name: str | None = None


@dataclass(frozen=True, slots=True)
class BatchFileRow:
    """对账用的最小批次投影：谁的文件还在缓冲区里。"""

    batch_id: str
    stored_name: str


class CleanupRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── staging_batch 双写方（门禁允许的两处）──────────────────
    def clear_pending_delete(self, batch_id: str, *, deleted_at: str | None = None) -> int:
        """删除意图完成：``flag`` 清零 + 落 ``deleted_at``（独立小事务由调用方开）。"""
        cursor = self._conn.execute(
            "UPDATE staging_batch SET pending_delete_flag = 0, deleted_at = ?, updated_at = ? "
            "WHERE id = ?",
            (deleted_at or now_iso(), now_iso(), batch_id),
        )
        return cursor.rowcount

    def reset_interrupted(self, *, reason: str = "服务重启中断") -> int:
        """对账第 ① 步（D-8 的防御性保险丝）：``ingesting`` 置回 ``prechecked``。

        幂等闸门在事务内（A 线），正常情况恒命中 0 条；命中说明有人在事务外
        改过状态 —— 调用方必须记 WARN，不静默修复。
        """
        cursor = self._conn.execute(
            "UPDATE staging_batch SET status = 'prechecked', fail_reason = ?, updated_at = ? "
            "WHERE status = 'ingesting'",
            (reason, now_iso()),
        )
        return cursor.rowcount

    # ── cleanup_queue ─────────────────────────────────────────
    def enqueue(
        self,
        *,
        batch_id: str | None,
        file_path: str,
        reason: str,
        cleanup_id: str | None = None,
    ) -> str:
        """删不掉就入队；同一路径已有 pending 行则**累加 attempts** 而不是重复插入。

        ``attempts`` 的语义是"删除尝试次数"：入队即已失败过一次，故新行从 1 起算。
        """
        existing = self._find_pending(file_path)
        if existing is not None:
            self.record_failure(existing, reason)
            return existing
        new_id = cleanup_id or uuid4().hex
        stamp = now_iso()
        self._conn.execute(
            "INSERT INTO cleanup_queue(id, batch_id, file_path, reason, attempts, last_error, "
            "status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                new_id,
                batch_id,
                file_path,
                reason[:200],
                1,
                reason[:200],
                "pending",
                stamp,
                stamp,
            ),
        )
        return new_id

    def mark_done(self, cleanup_id: str) -> int:
        cursor = self._conn.execute(
            "UPDATE cleanup_queue SET status = 'done', updated_at = ? WHERE id = ?",
            (now_iso(), cleanup_id),
        )
        return cursor.rowcount

    def record_failure(self, cleanup_id: str, error: str) -> int:
        """重试仍失败：``attempts`` 递增、``last_error`` 留痕（用户要在界面上看到）。"""
        cursor = self._conn.execute(
            "UPDATE cleanup_queue SET attempts = attempts + 1, last_error = ?, updated_at = ? "
            "WHERE id = ?",
            (error[:200], now_iso(), cleanup_id),
        )
        return cursor.rowcount

    def get(self, cleanup_id: str) -> CleanupRow | None:
        row = self._conn.execute(
            f"SELECT {_CLEANUP_COLUMNS} FROM cleanup_queue c "
            "LEFT JOIN staging_batch b ON b.id = c.batch_id WHERE c.id = ?",  # noqa: S608
            (cleanup_id,),
        ).fetchone()
        return _to_row(row)

    def list_items(self, status: str | None = None) -> list[CleanupRow]:
        """``status=None`` 返回全部；端点 ``?status=pending`` 只传 pending。

        返回的是**行列表**（不是分页对象）—— 前端 ``buffer.js`` 直接 ``.map``。
        方法名刻意不叫 ``list``：类体内的 ``list[...]`` 注解会撞上它自己的名字。
        """
        where = ""
        params: list[Any] = []
        if status is not None:
            where = " WHERE c.status = ?"
            params.append(status)
        rows = self._conn.execute(
            f"SELECT {_CLEANUP_COLUMNS} FROM cleanup_queue c "
            f"LEFT JOIN staging_batch b ON b.id = c.batch_id{where} "  # noqa: S608
            "ORDER BY c.created_at DESC, c.id DESC",
            tuple(params),
        ).fetchall()
        return [record for row in rows if (record := _to_row(row)) is not None]

    # ── 对账读取（只读）───────────────────────────────────────
    def pending_delete_batches(self) -> list[BatchFileRow]:
        """第 ② 步的输入：``ingested`` + ``flag=1``（删意图待执行）。"""
        rows = self._conn.execute(
            "SELECT id AS batch_id, stored_name FROM staging_batch "
            "WHERE status = 'ingested' AND pending_delete_flag = 1 "
            "ORDER BY created_at DESC, id DESC"
        ).fetchall()
        return [BatchFileRow(str(row["batch_id"]), str(row["stored_name"])) for row in rows]

    def inconsistent_batches(self) -> list[BatchFileRow]:
        """第 ③ 步的输入：``ingested`` + ``flag=0``（文件按说已经没了）。"""
        rows = self._conn.execute(
            "SELECT id AS batch_id, stored_name FROM staging_batch "
            "WHERE status = 'ingested' AND pending_delete_flag = 0 "
            "ORDER BY created_at DESC, id DESC"
        ).fetchall()
        return [BatchFileRow(str(row["batch_id"]), str(row["stored_name"])) for row in rows]

    def count_pending_deletes(self) -> int:
        """仍在等待补删的删除意图数（对账报告在自愈**之后**重新计数）。"""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM staging_batch "
            "WHERE status = 'ingested' AND pending_delete_flag = 1"
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def stored_names(self, *, exclude: tuple[str, ...] = ()) -> set[str]:
        """孤儿扫描的"已知集合"；``exclude`` 传终态时得到**更严**的诊断视图。

        对账第 ④ 步传 ``("ingested", "discarded")``（C3 §4.3：这些批次的文件
        按说已经没了，还留在缓冲区就是异常）；用户面的 ``/staging/orphans``
        与 ``/health`` 用全量（C2 冻结口径，不传 exclude）。
        """
        if not exclude:
            rows = self._conn.execute("SELECT stored_name FROM staging_batch").fetchall()
            return {str(row["stored_name"]) for row in rows}
        placeholders = ",".join("?" for _ in exclude)
        rows = self._conn.execute(
            f"SELECT stored_name FROM staging_batch WHERE status NOT IN ({placeholders})",  # noqa: S608
            exclude,
        ).fetchall()
        return {str(row["stored_name"]) for row in rows}

    # ── 内部 ──────────────────────────────────────────────────
    def _find_pending(self, file_path: str) -> str | None:
        row = self._conn.execute(
            "SELECT id FROM cleanup_queue WHERE status = 'pending' AND file_path = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (file_path,),
        ).fetchone()
        return str(row["id"]) if row is not None else None


def _to_row(row: sqlite3.Row | None) -> CleanupRow | None:
    if row is None:
        return None
    return CleanupRow(
        id=str(row["id"]),
        batch_id=row["batch_id"],
        file_path=str(row["file_path"]),
        reason=str(row["reason"]),
        attempts=int(row["attempts"]),
        last_error=row["last_error"],
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        file_name=row["file_name"],
    )
