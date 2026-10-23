"""K3 的注入协议（Gate 0 冻结）：事务外的删除意图交给自己，也交给未来。

A 线（``IngestService``）在 COMMIT **之后**调用
``DeleteFailureSink.on_committed(batch_id, file_path)``，拿到
:class:`DeleteOutcome` 决定报告里 ``files_deleted`` 填真还是假。
它自己**一个 ``unlink`` 都不写**（grep 门禁保证）—— 文件系统不在事务里，
先提交再删，最坏结果是"数据在、文件也在"（由 B 线的启动对账补删）。

Gate 0 提供开发期默认实现 :class:`NullSink`（直接报告已删除，什么都不做）；
合稿 M2 把它换成 :class:`~account_dashboard.services.cleanup_service.CleanupService`
—— ``api/deps.py`` 里的一行替换，是两条线唯一的咬合点。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class DeleteOutcome(BaseModel):
    """删除结果。``cleanup_id`` 在 ``deleted=False`` 时必填（D-7 的 report 要用）。"""

    deleted: bool
    cleanup_id: str | None = None


@runtime_checkable
class DeleteFailureSink(Protocol):
    """A 线唯一可见的删除接口：事务外调用，返回是否删除成功。"""

    def on_committed(self, batch_id: str, file_path: str) -> DeleteOutcome: ...


class NullSink:
    """Gate 0 的开发期实现：声称已删除，实际不动文件（A 线单测用）。"""

    def on_committed(self, batch_id: str, file_path: str) -> DeleteOutcome:
        return DeleteOutcome(deleted=True)


__all__ = ["DeleteFailureSink", "DeleteOutcome", "NullSink"]
