"""主数据层仓储。

C2 只开放**只读**指纹查询（``find_fp_in``）；C3-A 起本模块是唯一写
``transaction`` 的地方（``insert_many``），并留下 C4 的四个空壳签名
（``iter_for_recalc`` / ``count_by`` / ``sum_by_category`` / ``patch_status``）——
只写签名 + ``NotImplementedError``，C4 填实现时**不得改签名**。

为什么分片放在这里而不是调用方：``IN`` 的参数个数上限随 SQLite 版本变化
（旧版本 999），把分片放在 SQL 旁边，就不会出现"换个调用点就超限"的问题。
``insert_many`` 的 500 行分批同理，且能把 5 万行的峰值内存压住。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from itertools import islice
from typing import Any
from uuid import uuid4

from account_dashboard.infra.clock import now_iso

# ``IN`` 的参数个数上限随 SQLite 版本变化（旧版本 999），取 500 留一倍余量。
FP_QUERY_CHUNK = 500

_INSERT_SQL = (
    'INSERT INTO "transaction"(id, occurred_at, amount_cents, direction, category_l1, '
    "category_l2, counterparty, item, txn_type, payment_method, channel, status, note, "
    "hint_l1, hint_l2, batch_id, row_no, fp, override_reason, override_at, created_at, "
    "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)

# 批次钩子签名：(第几批从 0 起, 该批行数)。生产传 None。
BatchHook = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class TransactionInsert:
    """一行待入库的主数据（``id`` 由仓储生成，调用方不关心）。"""

    occurred_at: str
    amount_cents: int
    direction: str
    batch_id: str
    row_no: int
    counterparty: str | None = None
    item: str | None = None
    txn_type: str | None = None
    payment_method: str | None = None
    channel: str = "other"
    fp: str | None = None
    # 强制新增留痕（P0-1 / PRD「override_reason（强制新增原因，可空）」）：
    # fp 命中但用户标了 override 的行，把原因搬到主数据上，前端抽屉直接展示。
    override_reason: str | None = None
    override_at: str | None = None


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

    def insert_many(
        self,
        rows: Iterable[TransactionInsert],
        *,
        chunk_size: int = FP_QUERY_CHUNK,
        batch_hook: BatchHook | None = None,
    ) -> int:
        """分批 ``executemany`` 写入主数据；返回写入行数。

        ``batch_hook(batch_index, batch_size)`` 在**每批执行前**调用，是故障注入 1
        的注入点（``tests/fault_injection/test_fi_tx_failure.py``）：注入必须在
        ``insert_many`` 内部按批计数，不能 mock 整个 repo —— 否则测的是 mock
        不是事务。生产环境传 ``None``。

        C3 写入的行恒为 ``status='pending'``、``category_l1/l2`` 为 ``NULL``
        （分类是 C4 的事）；金额只搬运 ``ParsedRow.amount_cents``，此处禁止任何
        ``* 100`` 之类的二次换算。
        """
        size = max(1, chunk_size)
        iterator = iter(rows)
        written = 0
        index = 0
        while True:
            chunk = list(islice(iterator, size))
            if not chunk:
                break
            if batch_hook is not None:
                batch_hook(index, len(chunk))
            stamp = now_iso()
            self._conn.executemany(
                _INSERT_SQL,
                [
                    (
                        uuid4().hex,
                        row.occurred_at,
                        row.amount_cents,
                        row.direction,
                        None,  # category_l1 —— C4
                        None,  # category_l2 —— C4
                        row.counterparty,
                        row.item,
                        row.txn_type,
                        row.payment_method,
                        row.channel,
                        "pending",  # status —— C3 只写 pending
                        None,  # note —— C4 修正
                        None,  # hint_l1 —— C4
                        None,  # hint_l2 —— C4
                        row.batch_id,
                        row.row_no,
                        row.fp,
                        row.override_reason,
                        row.override_at,
                        stamp,
                        stamp,
                    )
                    for row in chunk
                ],
            )
            written += len(chunk)
            index += 1
        return written

    def count_all(self) -> int:
        """只在测试与报告里用。"""
        row = self._conn.execute('SELECT COUNT(*) FROM "transaction"').fetchone()
        return int(row[0])

    def count_by_batch(self, batch_id: str) -> int:
        """某批次入库的主数据行数（入库后自检：应等于报告的 ``inserted``）。"""
        row = self._conn.execute(
            'SELECT COUNT(*) FROM "transaction" WHERE batch_id = ?', (batch_id,)
        ).fetchone()
        return int(row[0])

    # ── C4 空壳签名（本线只放签名，实现留给 C4，不得改签名） ────
    def iter_for_recalc(
        self,
        scope: str,
        batch_id: str | None = None,
        rule_ids: Sequence[str] | None = None,
        overwrite_manual: bool = False,
    ) -> Iterable[sqlite3.Row]:
        """重算目标行迭代器（C4 填实现）。``scope`` 取值由 C4 定义。"""
        raise NotImplementedError("iter_for_recalc 由 C4 实现")

    def count_by(self, filters: dict[str, Any] | None = None) -> int:
        """按过滤条件计数（C4 填实现）。"""
        raise NotImplementedError("count_by 由 C4 实现")

    def sum_by_category(
        self, *, level: int = 1, filters: dict[str, Any] | None = None
    ) -> dict[str, int]:
        """按分类汇总金额（整数分；C4 填实现）。"""
        raise NotImplementedError("sum_by_category 由 C4 实现")

    def patch_status(
        self,
        txn_id: str,
        status: str,
        *,
        category_l1: str | None = None,
        category_l2: str | None = None,
    ) -> int:
        """状态/分类补写（C4 填实现）。``status`` 是 4 个合法写入点之一。"""
        raise NotImplementedError("patch_status 由 C4 实现")


__all__ = ["BatchHook", "FP_QUERY_CHUNK", "TransactionInsert", "TransactionRepo"]
