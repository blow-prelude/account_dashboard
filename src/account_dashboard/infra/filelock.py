"""单实例文件锁（ADR-12）。

同一数据目录只允许一个后端进程：两个进程同时迁移或同时写 WAL 会互相破坏。
用 OS 级字节锁（Windows ``msvcrt.locking`` / POSIX ``fcntl.flock``），
进程崩溃时由操作系统自动释放，不会留下"假占用"。
"""

from __future__ import annotations

import os
import sys
from contextlib import suppress
from pathlib import Path
from types import TracebackType
from typing import TextIO

LOCK_FILE_NAME = "instance.lock"


class AlreadyRunning(Exception):
    """已有实例持有该数据目录的锁。映射为启动退出码 5。"""


class SingleInstanceLock:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / LOCK_FILE_NAME
        self._file: TextIO | None = None

    def acquire(self) -> None:
        if self._file is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 锁需要长期持有句柄，不能用 with 立即关闭
        handle = open(self.path, "a+", encoding="utf-8", newline="")  # noqa: SIM115
        try:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(" ")
                handle.flush()
            handle.seek(0)
            _lock(handle)
        except OSError as exc:
            handle.close()
            raise AlreadyRunning("已有实例在运行，请先关闭它（或检查 instance.lock）") from exc

        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._file = handle

    def release(self) -> None:
        handle = self._file
        if handle is None:
            return
        try:
            _unlock(handle)
        finally:
            handle.close()
            self._file = None
            with suppress(OSError):
                self.path.unlink()

    @property
    def held(self) -> bool:
        return self._file is not None

    def __enter__(self) -> SingleInstanceLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


def _lock(handle: TextIO) -> None:
    # 用 sys.platform 而非 os.name：mypy 按分析平台静态裁剪不可达分支，
    # Windows 专用模块（msvcrt）不会在 POSIX 上被类型检查（行为与 os.name 等价）
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:  # pragma: no cover - POSIX 分支
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: TextIO) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover - POSIX 分支
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:  # pragma: no cover - 进程退出时自动释放
        return
