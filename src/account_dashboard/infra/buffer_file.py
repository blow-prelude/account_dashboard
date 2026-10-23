"""缓冲区文件管理（SDD §4.5.1 / §7.1，EX-17 / EX-11 / EX-23）。

四个必须做对的动作：

1. **流式落盘**：1MB 分块写，峰值内存与文件大小无关（5MB 文件峰值 < 8MB 有 tracemalloc 用例背书）；
2. **先写 ``.part`` 再 ``os.replace``**：中途失败只留下 ``.part``，不会出现"半个正式文件"
   被孤儿扫描误报；
3. **写前与写入过程中都查余量**：余量不足立即清理并抛 ``E4001``（507），不能等 ENOSPC；
4. **删除幂等**：文件已不存在视为成功（丢弃批次、清理队列重试都靠这条）。
"""

from __future__ import annotations

import gc
import hashlib
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from account_dashboard.infra.clock import to_iso
from account_dashboard.infra.errors import (
    BufferDirError,
    DiskFullError,
    EncodingDetectionError,
    FileDeleteError,
    FileTooLargeError,
    FileTypeError,
    FileWriteError,
)
from account_dashboard.infra.logger import get_logger

_logger = get_logger("buffer")

CHUNK_SIZE = 1 << 20  # 1MB
MAX_FILE_BYTES = 5 * 1024 * 1024
MIN_DISK_FREE_BYTES = 200 * 1024 * 1024
ALLOWED_EXTENSIONS = frozenset({".csv", ".xlsx"})
# 半成品后缀：.part 是本模块写的，.tmp 是历史/外部工具留下的，两者都不算孤儿
PARTIAL_SUFFIXES = (".part", ".tmp")


class UploadStream(Protocol):
    """``UploadFile`` 的结构子集（只依赖 ``read``，便于用假的流做内存测试）。"""

    async def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True, slots=True)
class StoredFile:
    stored_name: str
    path: Path
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class OrphanFile:
    name: str
    size_bytes: int
    modified_at: str


@dataclass(frozen=True, slots=True)
class BufferUsage:
    file_count: int
    total_bytes: int
    oldest_at: str | None
    threshold_bytes: int

    @property
    def exceeded(self) -> bool:
        return self.total_bytes >= self.threshold_bytes


class BufferFileManager:
    def __init__(
        self,
        buffer_dir: Path,
        *,
        min_free_bytes: int = MIN_DISK_FREE_BYTES,
        max_file_bytes: int = MAX_FILE_BYTES,
    ) -> None:
        self.buffer_dir = buffer_dir
        self.min_free_bytes = min_free_bytes
        self.max_file_bytes = max_file_bytes

    # ── 目录 ──────────────────────────────────────────────────
    def ensure_dir(self) -> bool:
        """目录缺失则重建（EX-23）；不可写抛 ``E4004``。返回是否真的创建过。"""
        existed = self.buffer_dir.is_dir()
        try:
            self.buffer_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BufferDirError(f"缓冲区目录不可用：{exc}") from exc
        if not os.access(self.buffer_dir, os.W_OK):
            raise BufferDirError(f"缓冲区目录不可写：{self.buffer_dir}")
        return not existed

    def free_bytes(self) -> int:
        try:
            return shutil.disk_usage(self.buffer_dir).free
        except OSError:
            return 0

    def path_for(self, stored_name: str) -> Path:
        """只接受文件名（防路径穿越）：调用方传入的是 DB 里的 ``stored_name``。"""
        name = Path(stored_name).name
        return self.buffer_dir / name

    def exists(self, stored_name: str) -> bool:
        return self.path_for(stored_name).is_file()

    # ── 落盘 ──────────────────────────────────────────────────
    async def save_stream(
        self,
        stream: UploadStream,
        file_name: str,
        declared_size: int = 0,
    ) -> StoredFile:
        extension = Path(file_name).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise FileTypeError("只支持 CSV 或 Excel(.xlsx) 文件，请重新导出")
        if declared_size and declared_size > self.max_file_bytes:
            raise FileTooLargeError(
                f"文件超过 {self.max_file_bytes // (1024 * 1024)}MB，请按月份分批导出",
                detail={"max_bytes": self.max_file_bytes},
            )

        self.ensure_dir()
        if self.free_bytes() < self.min_free_bytes:
            raise DiskFullError(
                "磁盘空间不足，未写入任何文件，请清理磁盘后重试",
                detail={"free_bytes": self.free_bytes(), "min_free_bytes": self.min_free_bytes},
            )

        stored_name = f"{uuid4().hex}{extension}"
        final_path = self.buffer_dir / stored_name
        tmp_path = final_path.with_name(final_path.name + ".part")
        digest = hashlib.sha256()
        written = 0

        try:
            with tmp_path.open("wb") as handle:
                while True:
                    chunk = await stream.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > self.max_file_bytes:
                        raise FileTooLargeError(
                            f"文件超过 {self.max_file_bytes // (1024 * 1024)}MB，请按月份分批导出",
                            detail={"max_bytes": self.max_file_bytes},
                        )
                    if self.free_bytes() < self.min_free_bytes:
                        raise DiskFullError(
                            "磁盘空间不足，已清理未完成文件",
                            detail={"free_bytes": self.free_bytes()},
                        )
                    handle.write(chunk)
                    digest.update(chunk)
                handle.flush()
                os.fsync(handle.fileno())

            if written == 0:
                raise EncodingDetectionError("文件为空，请检查导出内容", code="E1004")

            os.replace(tmp_path, final_path)  # 原子可见：要么没有，要么完整
        except (FileTooLargeError, DiskFullError, EncodingDetectionError):
            _unlink_quiet(tmp_path)
            raise
        except OSError as exc:
            _unlink_quiet(tmp_path)
            raise FileWriteError(f"写入缓冲区失败，请检查磁盘与权限：{exc}") from exc

        _logger.info("落盘 %s（%s 字节）", stored_name, written)
        return StoredFile(
            stored_name=stored_name,
            path=final_path,
            size=written,
            sha256=digest.hexdigest(),
        )

    # ── 删除 / 扫描 / 统计 ────────────────────────────────────
    def delete(self, path: Path) -> None:
        """缺失视为成功（幂等）；被占用/无权限抛 ``E4003``（C3 会入待清理队列）。"""
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise FileDeleteError(f"文件删除失败：{exc}") from exc

    def delete_with_retry(self, path: Path, attempts: int = 3, delay: float = 0.1) -> bool:
        """带退避的删除（EX-11 / C3-B）：返回是否删干净了，**绝不抛异常**。

        Windows 上 openpyxl / csv 读取后的句柄可能没来得及释放，``unlink``
        抛 ``PermissionError``；``gc.collect()`` 是那里唯一有效的兜底，
        配合 100/200/300ms 线性退避给系统一个回收窗口。

        三条语义（与既有的 ``delete()`` 刻意不同，那个是"失败即抛"）：

        * ``FileNotFoundError`` → **成功**（幂等：已经没了就算删掉）；
        * ``PermissionError`` → 退避后重试，``attempts`` 次都失败才返回 ``False``；
        * 其他 ``OSError``（目录、只读文件系统…）→ 立即 ``False``，重试无意义。

        调用方（``CleanupService`` / 启动对账）拿到 ``False`` 后自行入队，
        由用户在``待清理``页面手动重试 —— 删除失败永远不阻断主流程。
        """
        for i in range(attempts):
            try:
                path.unlink()
                return True
            except FileNotFoundError:
                return True
            except PermissionError:
                gc.collect()
                time.sleep(delay * (i + 1))
            except OSError:
                return False
        return False

    def scan_orphans(self, known_names: set[str]) -> list[OrphanFile]:
        """目录里存在、但没有任何批次记录的文件（半成品不算孤儿）。"""
        if not self.buffer_dir.is_dir():
            return []
        orphans: list[OrphanFile] = []
        for entry in sorted(self.buffer_dir.iterdir()):
            if not entry.is_file() or _is_partial(entry.name) or entry.name in known_names:
                continue
            stat = entry.stat()
            orphans.append(
                OrphanFile(
                    name=entry.name,
                    size_bytes=stat.st_size,
                    modified_at=to_iso(datetime.fromtimestamp(stat.st_mtime)),
                )
            )
        return orphans

    def usage(self, *, threshold_bytes: int = 500 * 1024 * 1024) -> BufferUsage:
        if not self.buffer_dir.is_dir():
            return BufferUsage(0, 0, None, threshold_bytes)
        count = 0
        total = 0
        oldest: datetime | None = None
        for entry in self.buffer_dir.iterdir():
            if not entry.is_file() or _is_partial(entry.name):
                continue
            stat = entry.stat()
            count += 1
            total += stat.st_size
            stamp = datetime.fromtimestamp(stat.st_mtime)
            oldest = stamp if oldest is None or stamp < oldest else oldest
        return BufferUsage(count, total, to_iso(oldest) if oldest else None, threshold_bytes)

    def cleanup_partials(self) -> int:
        """启动时清理残留半成品（崩溃上传留下的 ``.part`` / ``.tmp``）。"""
        if not self.buffer_dir.is_dir():
            return 0
        removed = 0
        for entry in self.buffer_dir.iterdir():
            if entry.is_file() and _is_partial(entry.name):
                _unlink_quiet(entry)
                removed += 1
        if removed:
            _logger.info("清理缓冲区半成品 %s 个", removed)
        return removed


def _is_partial(name: str) -> bool:
    return name.endswith(PARTIAL_SUFFIXES)


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:  # pragma: no cover - Windows 占用时才会走到
        _logger.warning("临时文件清理失败 %s：%s", path.name, exc)
