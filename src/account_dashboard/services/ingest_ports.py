"""入库事务的删除意图注入点（K3 / Gate 0 冻结）。

A 线（入库事务）在 ``COMMIT`` **之后**、事务**外**调用
``sink.on_committed(batch_id, file_path)``，把「缓冲区物理文件怎么处理」
整个交出去；B 线提供真实实现 ``CleanupService``（删成功清零
``pending_delete_flag``，失败入 ``cleanup_queue``），开发期用
:class:`NullSink` 占位。

这个 Protocol 是两条线**唯一**的咬合点：A 线不 import B 线的任何模块，
B 线也不 import ``ingest_service``。把 ``NullSink`` 换成 ``CleanupService``
只需改 ``api/deps.py`` 的一行（合稿 M2），A 线全部用例应零改动全绿。
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class DeleteOutcome(BaseModel):
    """删除结果。``deleted=False`` 时 ``cleanup_id`` 必填（调用方要能指回队列项）。"""

    deleted: bool
    cleanup_id: str | None = None


class DeleteFailureSink(Protocol):
    """事务外调用；实现方自行决定重试策略，但**不得**因此回滚已提交的数据。"""

    def on_committed(self, batch_id: str, file_path: str) -> DeleteOutcome: ...


class NullSink:
    """A 线开发期默认实现：假装删成功，不碰文件系统。

    存在的意义是让 A 线的用例可以在「B 线还不存在」的情况下全绿；
    生产环境绝不允许注入它（文件会永远堆在缓冲区里）。
    """

    def on_committed(self, batch_id: str, file_path: str) -> DeleteOutcome:
        return DeleteOutcome(deleted=True)


__all__ = ["DeleteFailureSink", "DeleteOutcome", "NullSink"]
