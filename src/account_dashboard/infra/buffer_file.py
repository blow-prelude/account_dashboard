"""缓冲区文件管理（buffer-file-manager，C2-B §4.1 / §4.8，SDD §4.5.1）。

只做「文件」的事：落盘、原子改名、删除、扫描、占用统计；**不碰批次状态**
（那属于 ``repositories/staging_repo.py``）。

四个刻意的实现选择：

1. **流式 1MB 分块 + 边写边查余量**：5MB 文件峰值内存 < 8MB 是硬指标（出口检查表），
   禁止 ``await file.read()`` 整读；
2. **``.tmp`` → ``os.replace``**：中途失败只留 ``.tmp``，不会出现"半个文件"，孤儿扫描
   才敢忽略 ``.tmp``；
3. **``stored_name = uuid4().hex + ext``**：原始文件名只进 DB 展示字段，**永不用于拼路径**
   （防路径穿越与重名覆盖）；
4. **删除重试 3 次 + ``gc.collect()``**：Windows 上文件被占用是常态，退避 100/200/300ms。
"""

from __future__ import annotations

import errno
import gc
import hashlib
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from account_dashboard.errors import EntryValidationError, ErrorCode, FileIOError
from account_dashboard.infra.clock import to_iso
from account_dashboard.infra.logger import get_logger
from account_dashboard.limits import (
    MAX_FILE_BYTES,
    MIN_DISK_FREE_BYTES,
    STREAM_CHUNK_BYTES,
)

_logger = get_logger("buffer")

TMP_SUFFIX = ".tmp"
DELETE_ATTEMPTS = 3
DELETE_BACKOFF_SECONDS = (0.1, 0.2, 0.3)


@dataclass(frozen=True, slots=True)
class StoredFile:
    """落盘结果；``stored_name`` 写进 ``staging_batch.stored_name``。"""

    stored_name: str
    path: Path
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class BufferUsage:
    file_count: int
    total_bytes: int
    oldest_at: str | None


@dataclass(frozen=True, slots=True)
class OrphanFile:
    """缓冲区里存在、但没有任何批次记录的文件（EX-13）。"""

    name: str
    size: int
    modified_at: str


def free_bytes(path: Path) -> int:
    """磁盘余量（单独成函数便于用例注入"磁盘满"）。"""
    try:
        return shutil.disk_usage(path).free
    except OSError as exc:  # 目录刚被删掉
        _logger.warning("无法读取磁盘余量 %s：%s", path, exc)
        return 0


class BufferFileManager:
    def __init__(
        self,
        buffer_dir: Path,
        min_free_bytes: int = MIN_DISK_FREE_BYTES,
        *,
        max_file_bytes: int = MAX_FILE_BYTES,
    ) -> None:
        self._buffer_dir = buffer_dir
        self._min_free_bytes = min_free_bytes
        self._max_file_bytes = max_file_bytes

    @property
    def buffer_dir(self) -> Path:
        return self._buffer_dir

    # ── 目录 ──────────────────────────────────────────────────
    def ensure_dir(self) -> bool:
        """目录不存在则重建（EX-23）；仍不可写 → ``E4004``。返回是否新建。"""
        existed = self._buffer_dir.is_dir()
        try:
            self._buffer_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise FileIOError(
                ErrorCode.BUFFER_DIR_MISSING,
                f"缓冲区目录不可用：{exc}",
                detail={"path": str(self._buffer_dir)},
            ) from exc
        if not os.access(self._buffer_dir, os.W_OK):
            raise FileIOError(
                ErrorCode.BUFFER_DIR_MISSING,
                "缓冲区目录不可写，请检查目录权限",
                detail={"path": str(self._buffer_dir)},
            )
        if not existed:
            _logger.warning("缓冲区目录已重建：%s", self._buffer_dir)
        return not existed

    def path_for(self, stored_name: str) -> Path:
        """由 ``stored_name`` 还原物理路径，拒绝任何路径穿越。"""
        name = Path(stored_name).name
        if not stored_name or name != stored_name or "\\" in stored_name or "/" in stored_name:
            raise FileIOError(
                ErrorCode.BUFFER_DIR_MISSING,
                "批次文件记录不合法，请联系维护者",
                detail={"stored_name": stored_name},
            )
        return self._buffer_dir / name

    def exists(self, stored_name: str) -> bool:
        try:
            return self.path_for(stored_name).is_file()
        except FileIOError:
            return False

    # ── 落盘 ──────────────────────────────────────────────────
    def save_stream(self, stream: BinaryIO, file_name: str, declared_size: int) -> StoredFile:
        """流式落盘：``.tmp`` → ``fsync`` → ``os.replace``。

        ``declared_size`` 只用于提前拦截（客户端声明的 Content-Length）；
        真实大小以写入字节数为准 —— 声明值可以撒谎。
        """
        self.ensure_dir()
        self._assert_free_space()

        suffix = Path(file_name).suffix.lower()
        token = uuid4().hex
        tmp_path = self._buffer_dir / f"{token}{TMP_SUFFIX}"
        final_path = self._buffer_dir / f"{token}{suffix}"

        digest = hashlib.sha256()
        written = 0
        try:
            with open(tmp_path, "wb") as handle:
                while True:
                    chunk = stream.read(STREAM_CHUNK_BYTES)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > self._max_file_bytes:
                        raise EntryValidationError(
                            ErrorCode.FILE_TOO_LARGE,
                            f"文件超过 {self._max_file_bytes // (1024 * 1024)}MB，"
                            "请按月拆分后再上传",
                            detail={"max_bytes": self._max_file_bytes},
                        )
                    handle.write(chunk)
                    digest.update(chunk)
                    self._assert_free_space()  # 每 1MB 复查，避免写到一半把盘写满
                handle.flush()
                os.fsync(handle.fileno())

            if written == 0:
                raise EntryValidationError(
                    ErrorCode.EMPTY_FILE, "文件是空的，请重新导出账单后再上传"
                )

            os.replace(tmp_path, final_path)  # 原子可见：要么没有，要么完整
        except OSError as exc:
            code = ErrorCode.DISK_FULL if exc.errno == errno.ENOSPC else ErrorCode.FILE_WRITE_FAILED
            raise FileIOError(
                code,
                "磁盘空间不足，请清理后重试"
                if code is ErrorCode.DISK_FULL
                else "文件写入失败，请重试",
                detail={"file_name": file_name, "reason": str(exc)},
            ) from exc
        finally:
            if tmp_path.exists():
                _safe_unlink(tmp_path)  # 任何异常都不留半成品

        return StoredFile(
            stored_name=final_path.name,
            path=final_path,
            size=written,
            sha256=digest.hexdigest(),
        )

    def _assert_free_space(self) -> None:
        available = free_bytes(self._buffer_dir)
        if available < self._min_free_bytes:
            raise FileIOError(
                ErrorCode.DISK_FULL,
                f"磁盘可用空间不足 {self._min_free_bytes // (1024 * 1024)}MB，请清理后重试",
                detail={"free_bytes": available, "min_free_bytes": self._min_free_bytes},
            )

    # ── 删除 ──────────────────────────────────────────────────
    def delete(self, path: Path) -> None:
        """删除单个文件；**缺失视为成功**（幂等）。"""
        try:
            os.remove(path)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise FileIOError(
                ErrorCode.FILE_DELETE_FAILED,
                "文件被占用或没有权限，请关闭相关程序后重试",
                detail={"path": str(path), "reason": str(exc)},
            ) from exc

    def delete_with_retry(self, path: Path, attempts: int = DELETE_ATTEMPTS) -> None:
        """Windows 上文件常被索引/杀软短暂占用 → 退避重试；仍失败抛 ``E4003``。"""
        last_error: FileIOError | None = None
        for attempt in range(attempts):
            try:
                self.delete(path)
                return
            except FileIOError as exc:
                last_error = exc
                _logger.warning("删除文件失败（第 %d/%d 次）：%s", attempt + 1, attempts, path)
                if attempt < attempts - 1:
                    gc.collect()  # 释放本进程内残留的文件句柄
                    time.sleep(
                        DELETE_BACKOFF_SECONDS[min(attempt, len(DELETE_BACKOFF_SECONDS) - 1)]
                    )
        assert last_error is not None
        raise last_error

    # ── 扫描与统计 ────────────────────────────────────────────
    def _iter_files(self) -> list[Path]:
        if not self._buffer_dir.is_dir():
            return []
        try:
            return [entry for entry in self._buffer_dir.iterdir() if entry.is_file()]
        except OSError as exc:
            _logger.warning("扫描缓冲区目录失败 %s：%s", self._buffer_dir, exc)
            return []

    def scan_orphans(self, known_names: set[str]) -> list[OrphanFile]:
        """不在批次表里的文件；``.tmp`` 残片由 ``cleanup_partials`` 处理，此处忽略。"""
        orphans: list[OrphanFile] = []
        for entry in self._iter_files():
            if entry.name.endswith(TMP_SUFFIX) or entry.name in known_names:
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            orphans.append(
                OrphanFile(
                    name=entry.name,
                    size=stat.st_size,
                    modified_at=to_iso(datetime.fromtimestamp(stat.st_mtime)),
                )
            )
        orphans.sort(key=lambda item: item.modified_at)
        return orphans

    def usage(self) -> BufferUsage:
        total = 0
        count = 0
        oldest: float | None = None
        for entry in self._iter_files():
            if entry.name.endswith(TMP_SUFFIX):
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            count += 1
            total += stat.st_size
            oldest = stat.st_mtime if oldest is None else min(oldest, stat.st_mtime)
        return BufferUsage(
            file_count=count,
            total_bytes=total,
            oldest_at=to_iso(datetime.fromtimestamp(oldest)) if oldest is not None else None,
        )

    def cleanup_partials(self) -> int:
        """清理崩溃残留的 ``.tmp``（启动对账会调用）；返回删除个数。"""
        removed = 0
        for entry in self._iter_files():
            if not entry.name.endswith(TMP_SUFFIX):
                continue
            try:
                _safe_unlink(entry)
                removed += 1
            except OSError as exc:
                _logger.warning("清理临时文件失败 %s：%s", entry, exc)
        return removed


def _safe_unlink(path: Path) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        return
    except OSError as exc:  # Windows 上被占用时不要掩盖真实错误
        _logger.warning("删除失败 %s：%s", path, exc)


__all__ = [
    "DELETE_ATTEMPTS",
    "TMP_SUFFIX",
    "BufferFileManager",
    "BufferUsage",
    "OrphanFile",
    "StoredFile",
    "free_bytes",
]
