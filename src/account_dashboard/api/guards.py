"""批次状态机守卫（C2-B §4.2，SDD §4.1.3）。

门面而已：允许矩阵与断言实现在 ``models/staging.py``（叶子层），因为
``repositories/staging_repo.py`` 也要断言，而分层门禁禁止 ``repositories → api``。

C2 只覆盖四个动作（``parse`` / ``map`` / ``precheck`` / ``discard``）。C3 的
``try_enter_ingesting`` 留签名：它必须是**条件 UPDATE + rowcount**，而不是"先查后改"
（并发两次都会查到"待确认"，幂等闸门就漏了，EX-18）。
"""

from __future__ import annotations

from account_dashboard.models.staging import BatchAction, BatchStatus, assert_transition


class BatchGuard:
    @staticmethod
    def assert_transition(
        current: BatchStatus | str,
        action: BatchAction | str,
        target: BatchStatus | str | None = None,
    ) -> None:
        """非法流转抛 ``BusinessRuleError(E2002)``（409）。"""
        assert_transition(str(current), str(action), None if target is None else str(target))

    @staticmethod
    def try_enter_ingesting() -> None:
        """C3 实现：``UPDATE ... SET status='ingesting' WHERE id=? AND status='prechecked'``，
        ``rowcount == 0`` → ``E2002``。C2 阶段调用即视为越界。"""
        raise NotImplementedError("确认入库属 C3（ingest_service），C2 不提供")


__all__ = ["BatchGuard"]
