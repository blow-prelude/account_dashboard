"""删除意图与待清理队列（C3-B §4.1，EX-11 / K3 / K4）。

A 线（``IngestService``）在事务 COMMIT **之后**调用
:meth:`on_committed` —— 这是两条线唯一的咬合点。执行顺序（在事务外）：

```
① buffer.delete_with_retry(path, attempts=3)      # PermissionError → gc + 100/200/300ms 退避
② 成功 → UPDATE staging_batch SET pending_delete_flag=0, deleted_at=?   （独立小事务）
③ 失败 → INSERT cleanup_queue(...)                （另一个独立小事务）
         返回 DeleteOutcome(deleted=False, cleanup_id=...)
```

三条硬约束：

* **不能因为删不掉就回滚入库** —— 数据已提交，只能入队（D-7：confirm 返回
  200 + ``files_deleted=false``，不是 409）；
* ``flag`` 清零与入队是**两个独立小事务**，合并会让"清零成功但入队失败"
  的中间态无法解释；
* ``cleanup_queue.file_path`` 存路径字符串，``file_name`` 不落表（DDL 无该列），
  端点返回时由 ``LEFT JOIN staging_batch`` 补全。
"""

from __future__ import annotations

import re
from pathlib import Path

from account_dashboard.api.errors import (
    BusinessRuleError,
    EntryValidationError,
    ErrorCode,
)
from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.infra.logger import get_logger
from account_dashboard.models.ingest import CleanupItemDTO, OrphanCleanupDTO
from account_dashboard.repositories.cleanup_repo import CLEANUP_STATUSES, CleanupRepo, CleanupRow
from account_dashboard.repositories.unit_of_work import UnitOfWork
from account_dashboard.services.ingest_ports import DeleteFailureSink, DeleteOutcome

_logger = get_logger("cleanup")

# 孤儿清理的名字白名单（§4.4）：stored_name 的形态 = 32 位十六进制 + 可选扩展名
_ORPHAN_NAME_RE = re.compile(r"^[0-9a-f]{32}(\.[A-Za-z0-9]{1,8})?$")

_DELETE_FAILED_REASON = "文件删除失败（E4003）：被占用或无权限"
_RETRY_FAILED_REASON = "重试删除失败：文件仍被占用或无权限"


class CleanupService(DeleteFailureSink):
    """实现 Gate 0 的 ``DeleteFailureSink``；合稿 M2 时由 ``api/deps.py`` 注入。"""

    def __init__(self, uow: UnitOfWork, buffer: BufferFileManager) -> None:
        self._uow = uow
        self._buffer = buffer
        self._repo = CleanupRepo(uow.conn)

    # ══ DeleteFailureSink（A 线咬合点）══════════════════════════
    def on_committed(self, batch_id: str, file_path: str) -> DeleteOutcome:
        path = Path(file_path)
        if self._buffer.delete_with_retry(path):
            with self._uow.begin():
                self._repo.clear_pending_delete(batch_id)
            _logger.info("提交后删除成功：批次 %s，文件 %s", batch_id, path.name)
            return DeleteOutcome(deleted=True)

        with self._uow.begin():
            cleanup_id = self._repo.enqueue(
                batch_id=batch_id, file_path=str(path), reason=_DELETE_FAILED_REASON
            )
        _logger.warning(
            "提交后删除失败，已入待清理队列：批次 %s，文件 %s（%s）",
            batch_id,
            path.name,
            cleanup_id,
        )
        return DeleteOutcome(deleted=False, cleanup_id=cleanup_id)

    # ══ 待清理队列 CRUD（运维端点）══════════════════════════════
    def list_items(self, status: str | None = None) -> list[CleanupItemDTO]:
        if status is not None and status not in CLEANUP_STATUSES:
            raise EntryValidationError(
                ErrorCode.INVALID_ENUM_VALUE,
                f"状态只支持 {' / '.join(CLEANUP_STATUSES)}，收到『{status}』",
                detail={"status": status, "allowed": list(CLEANUP_STATUSES)},
            )
        return [self._to_dto(row) for row in self._repo.list_items(status)]

    def retry(self, cleanup_id: str) -> CleanupItemDTO:
        """手动重试删一个文件；幂等 —— 已 ``done``/``abandoned`` 的重复重试
        返回当前状态而不报错（用户重复点"重试"不该看到红条）。"""
        item = self._repo.get(cleanup_id)
        if item is None:
            raise BusinessRuleError(
                ErrorCode.BATCH_NOT_FOUND,
                "待清理记录不存在，可能已被清理",
                detail={"cleanup_id": cleanup_id},
            )
        if item.status != "pending":
            return self._to_dto(item)

        path = Path(item.file_path)
        if self._buffer.delete_with_retry(path):
            # mark_done 与 flag 清零是同一次成功删除的记账，放一个小事务里；
            # 任一半途失败都会因 delete 的幂等性在下次重试/对账时自愈。
            with self._uow.begin():
                self._repo.mark_done(cleanup_id)
                if item.batch_id is not None:
                    self._repo.clear_pending_delete(item.batch_id)
            _logger.info("待清理重试成功：%s", item.file_path)
        else:
            with self._uow.begin():
                self._repo.record_failure(cleanup_id, _RETRY_FAILED_REASON)
            _logger.warning("待清理重试仍失败：%s", item.file_path)

        refreshed = self._repo.get(cleanup_id)
        if refreshed is None:  # pragma: no cover - 刚更新过，不可能消失
            raise BusinessRuleError(
                ErrorCode.INTERNAL_ERROR, "待清理记录读取失败，请刷新页面重试"
            )
        return self._to_dto(refreshed)

    # ══ 孤儿清理（三重白名单，§4.4）═════════════════════════════
    def cleanup_orphans(self, names: list[str]) -> OrphanCleanupDTO:
        """清理缓冲区里**没有任何批次记录**的文件（EX-13 要用户确认后才会到这）。

        三重白名单，任一不过即整体拒绝（验证阶段不删任何文件）：

        ① 路径防穿越（最优先）：``resolve()`` 后必须仍在缓冲区目录内 → ``E1011``；
        ② 名字形态：``^[0-9a-f]{32}(\\.[A-Za-z0-9]{1,8})?$`` → ``E1008``；
        ③ 不得与已知批次同名（它可能正被别的批次使用）→ ``E2002``。

        穿越检查先于格式检查：``"../<32hex>"`` 两种规则都不符合，但路径逃逸是
        更危险的信号，报 ``E1011`` 才能让运维第一时间看到。
        """
        unique = list(dict.fromkeys(names))
        known = self._repo.stored_names()
        buffer_root = self._buffer.buffer_dir.resolve()

        for name in unique:
            candidate = (self._buffer.buffer_dir / name).resolve()
            if not candidate.is_relative_to(buffer_root):
                raise EntryValidationError(
                    ErrorCode.INVALID_DATA_DIR,
                    "文件名含路径穿越字符，已拒绝清理",
                    detail={"name": name},
                )
            if not _ORPHAN_NAME_RE.match(name):
                raise EntryValidationError(
                    ErrorCode.INVALID_ENUM_VALUE,
                    "文件名不是合法的存储名（32 位十六进制），已拒绝清理",
                    detail={"name": name},
                )
            if name in known:
                raise BusinessRuleError(
                    ErrorCode.BATCH_STATE_CONFLICT,
                    "该文件仍被某个批次引用，不能作为孤儿清理",
                    detail={"name": name},
                )

        removed: list[str] = []
        failed: list[dict[str, str]] = []
        for name in unique:
            if self._buffer.delete_with_retry(self._buffer.buffer_dir / name):
                removed.append(name)
            else:
                # 删不掉的**不从清单里移除** —— 留在 failed 里等用户下次再试
                failed.append({"name": name, "code": ErrorCode.FILE_DELETE_FAILED.value})
        if failed:
            _logger.warning("孤儿清理部分失败：%s", ", ".join(item["name"] for item in failed))
        return OrphanCleanupDTO(removed=removed, failed=failed)

    # ── 内部 ──────────────────────────────────────────────────
    def _to_dto(self, row: CleanupRow) -> CleanupItemDTO:
        return CleanupItemDTO(
            id=row.id,
            batch_id=row.batch_id,
            file_path=row.file_path,
            file_name=row.file_name,
            reason=row.reason,
            attempts=row.attempts,
            last_error=row.last_error,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
