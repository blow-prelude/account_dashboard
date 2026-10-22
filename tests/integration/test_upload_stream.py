"""C2B.1 流式落盘：峰值内存、原子改名、异常不留半成品。

内存断言只在 ``BufferFileManager`` 层做，因为 HTTP 层的 ``multipart`` 解析会把整份
请求体先落进 SpooledTemporaryFile，那是框架开销，不是本线的责任范围（§6.1 的
"5MB 文件峰值内存 < 8MB" 指的是流式落盘这一段）。
"""

from __future__ import annotations

import io
import tracemalloc
from pathlib import Path

import pytest

from account_dashboard.errors import AppError, ErrorCode
from account_dashboard.infra.buffer_file import TMP_SUFFIX, BufferFileManager, free_bytes

FIVE_MB = 5 * 1024 * 1024


@pytest.fixture
def buffer(tmp_path: Path) -> BufferFileManager:
    directory = tmp_path / "buffer"
    directory.mkdir()
    return BufferFileManager(directory, min_free_bytes=0)


def test_stream_writes_five_mb_with_small_peak_memory(buffer: BufferFileManager) -> None:
    payload = b"x" * FIVE_MB  # 先分配，不计入下面的 tracemalloc 峰值
    tracemalloc.start()
    stored = buffer.save_stream(io.BytesIO(payload), "账单.CSV", FIVE_MB)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert stored.size == FIVE_MB
    assert stored.path.is_file()
    assert peak < 8 * 1024 * 1024, f"峰值内存 {peak / 1024 / 1024:.2f}MB 超过 8MB"
    assert not list(buffer.buffer_dir.glob(f"*{TMP_SUFFIX}")), ".tmp 必须被清理"


def test_stored_name_never_uses_original_name(buffer: BufferFileManager) -> None:
    stored = buffer.save_stream(io.BytesIO(b"data"), "../../etc/passwd.csv", 4)

    assert stored.stored_name.endswith(".csv")
    assert "passwd" not in stored.stored_name
    assert ".." not in stored.stored_name
    assert stored.path.parent == buffer.buffer_dir


def test_interrupted_stream_leaves_no_half_file(buffer: BufferFileManager) -> None:
    class BrokenStream:
        def __init__(self) -> None:
            self.calls = 0

        def read(self, size: int) -> bytes:  # noqa: ARG002
            self.calls += 1
            if self.calls == 1:
                return b"y" * 1024
            raise OSError("连接中断")

    with pytest.raises(AppError) as excinfo:
        buffer.save_stream(BrokenStream(), "bill.csv", 1024 * 10)

    assert excinfo.value.code is ErrorCode.FILE_WRITE_FAILED
    assert list(buffer.buffer_dir.iterdir()) == [], "不得留下半个文件或 .tmp 残片"


def test_empty_stream_reports_empty_file(buffer: BufferFileManager) -> None:
    with pytest.raises(AppError) as excinfo:
        buffer.save_stream(io.BytesIO(b""), "bill.csv", 1)

    assert excinfo.value.code is ErrorCode.EMPTY_FILE


def test_free_bytes_tolerates_missing_dir(tmp_path: Path) -> None:
    assert free_bytes(tmp_path / "not-exists") == 0
