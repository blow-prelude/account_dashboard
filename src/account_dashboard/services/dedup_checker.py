"""去重预检（dedup-checker，C2-B §4.5 / SDD §4.2.3）。

**本模块只读**：只查 ``transaction.fp``，不写 ``transaction``、不写 ``raw_*``、
不改 ``staging_batch`` 的 ``total_rows``（I-PC-01 靠这条自证）。

三态判定（顺序不可换）：

1. ``is_valid=False`` 或 ``fp is None`` → ``pending_manual``，**不参与指纹比对**
   （否则缺时间的行会被错误地算成 ``new``，去重就漏判了，EX-21）；
2. ``fp`` 命中 ``transaction.fp`` → ``dup``；
3. 未命中 → ``new``。

``apply_overrides`` 只做一件事：把**已命中 dup** 的行翻成 ``new``，
``pending_manual`` 不翻（这类行根本没法入库，翻了只会误导用户）。
"""

from __future__ import annotations

from collections.abc import Sequence

from account_dashboard.models.internal import ParsedRow
from account_dashboard.repositories.transaction_repo import TransactionRepo

LABEL_NEW = "new"
LABEL_DUP = "dup"
LABEL_PENDING = "pending_manual"


class DedupChecker:
    def __init__(self, txn_repo: TransactionRepo) -> None:
        self._txn_repo = txn_repo

    def label_rows(self, rows: Sequence[ParsedRow]) -> dict[int, str]:
        """``{row_no: label}``；C3 入库二次去重（EX-22）复用同一判定。"""
        labels: dict[int, str] = {}
        fp_to_rows: dict[str, list[int]] = {}

        for row in rows:
            if not row.is_valid or not row.fp:
                labels[row.row_no] = LABEL_PENDING
                continue
            labels[row.row_no] = LABEL_NEW
            fp_to_rows.setdefault(row.fp, []).append(row.row_no)

        if not fp_to_rows:
            return labels

        for fp in self._txn_repo.find_fp_in(list(fp_to_rows)):
            for row_no in fp_to_rows.get(fp, ()):
                labels[row_no] = LABEL_DUP
        return labels

    def apply_overrides(self, labels: dict[int, str], override_rows: set[int]) -> dict[int, str]:
        """强制新增：``dup → new``。返回**新字典**，不修改入参。"""
        flipped = dict(labels)
        for row_no in override_rows:
            if flipped.get(row_no) == LABEL_DUP:
                flipped[row_no] = LABEL_NEW
        return flipped

    @staticmethod
    def summarize(labels: dict[int, str]) -> dict[str, int]:
        """四数字，且必然满足 ``new + dup + pending_manual == total``。"""
        summary = {"total": len(labels), LABEL_NEW: 0, LABEL_DUP: 0, LABEL_PENDING: 0}
        for label in labels.values():
            if label in summary:
                summary[label] += 1
        return summary


__all__ = ["LABEL_DUP", "LABEL_NEW", "LABEL_PENDING", "DedupChecker"]
