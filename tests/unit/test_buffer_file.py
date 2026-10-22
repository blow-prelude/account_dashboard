"""缓冲区文件管理（EX-17 / EX-11 / EX-13）。

最关键的一条是 ``test_stream_upload_memory_peak``：5MB 文件落盘时 tracemalloc 峰值
必须 < 8MB。它证明的是「不整文件进内存」，也是导出检查表里唯一无法靠肉眼验收的项。
"""

from __future__ import annotations

import asyncio
import tracemalloc
from pathlib import Path

import pytest

from account_dashboard.infra.buffer_file import (
    CHUNK_SIZE,
    MAX_FILE_BYTES,
    BufferFileManager,
)
from account_dashboard.infra.errors import (
    DiskFullError,
    EncodingDetectionError,
    FileDeleteError,
    FileTooLargeError,
    FileTypeError,
)


class ChunkStream:
    """按块产出指定总字节数的假上传流（不会一次性分配整文件）。"""

    def __init__(self, total_bytes: int, chunk_size: int = CHUNK_SIZE) -> None:
        self.total_bytes = total_bytes
        self.chunk_size = chunk_size
        self.sent = 0

    async def read(self, size: int = -1) -> bytes:
        if self.sent >= self.total_bytes:
            return b""
        limit = size if size and size > 0 else self.chunk_size
        size_to_send = min(limit, self.chunk_size, self.total_bytes - self.sent)
        self.sent += size_to_send
        return b"x" * size_to_send


def test_stream_upload_memory_peak(tmp_path: Path) -> None:
    """5MB 流式落盘，内存峰值 < 8MB（EX-17 的验收口径）。"""
    manager = BufferFileManager(tmp_path)
    stream = ChunkStream(MAX_FILE_BYTES)

    tracemalloc.start()
    stored = asyncio.run(manager.save_stream(stream, "big.csv"))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert stored.size == MAX_FILE_BYTES
    assert stored.path.is_file()
    assert peak < 8 * 1024 * 1024, f"内存峰值 {peak / 1024 / 1024:.1f}MB，超过 8MB"


def test_atomic_replace_leaves_no_partial(tmp_path: Path) -> None:
    manager = BufferFileManager(tmp_path)
    stored = asyncio.run(manager.save_stream(ChunkStream(4096), "账单.CSV"))
    assert stored.stored_name.endswith(".csv"), "扩展名统一转小写"
    assert stored.stored_name != "账单.CSV", "落盘名用 uuid，原名只存 DB"
    leftovers = [item.name for item in tmp_path.iterdir() if item.name.endswith(".part")]
    assert leftovers == []


def test_oversize_stream_rejected_and_cleaned(tmp_path: Path) -> None:
    manager = BufferFileManager(tmp_path)
    with pytest.raises(FileTooLargeError) as excinfo:
        asyncio.run(manager.save_stream(ChunkStream(MAX_FILE_BYTES + 1), "big.csv"))
    assert excinfo.value.code == "E1005"
    assert list(tmp_path.iterdir()) == [], "超限时必须清理半成品"


def test_declared_size_rejected_before_writing(tmp_path: Path) -> None:
    manager = BufferFileManager(tmp_path)
    with pytest.raises(FileTooLargeError):
        asyncio.run(manager.save_stream(ChunkStream(1), "big.csv", MAX_FILE_BYTES + 1))
    assert list(tmp_path.iterdir()) == []


def test_disk_full_before_writing(tmp_path: Path) -> None:
    manager = BufferFileManager(tmp_path, min_free_bytes=10**15)
    with pytest.raises(DiskFullError) as excinfo:
        asyncio.run(manager.save_stream(ChunkStream(1024), "a.csv"))
    assert excinfo.value.code == "E4001"
    assert list(tmp_path.iterdir()) == []


def test_disk_full_during_writing_cleans_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = BufferFileManager(tmp_path, min_free_bytes=1024)
    calls = {"n": 0}

    def fake_free() -> int:
        calls["n"] += 1
        return 10**12 if calls["n"] == 1 else 0

    monkeypatch.setattr(manager, "free_bytes", fake_free)
    with pytest.raises(DiskFullError):
        asyncio.run(manager.save_stream(ChunkStream(CHUNK_SIZE * 2), "a.csv"))
    assert list(tmp_path.iterdir()) == [], "写入中磁盘满必须删掉 .part"


def test_empty_file_rejected(tmp_path: Path) -> None:
    manager = BufferFileManager(tmp_path)
    with pytest.raises(EncodingDetectionError) as excinfo:
        asyncio.run(manager.save_stream(ChunkStream(0), "a.csv"))
    assert excinfo.value.code == "E1004"
    assert list(tmp_path.iterdir()) == []


def test_unsupported_extension(tmp_path: Path) -> None:
    manager = BufferFileManager(tmp_path)
    with pytest.raises(FileTypeError) as excinfo:
        asyncio.run(manager.save_stream(ChunkStream(10), "a.txt"))
    assert excinfo.value.code == "E1001"


def test_delete_is_idempotent(tmp_path: Path) -> None:
    manager = BufferFileManager(tmp_path)
    target = tmp_path / "gone.csv"
    manager.delete(target)  # 不存在也不报错
    target.write_text("x", encoding="utf-8")
    manager.delete(target)
    assert not target.exists()

    (tmp_path / "locked.csv").mkdir()  # 目录：unlink 会失败
    with pytest.raises(FileDeleteError) as excinfo:
        manager.delete(tmp_path / "locked.csv")
    assert excinfo.value.code == "E4003"


def test_scan_orphans_skips_partials_and_known(tmp_path: Path) -> None:
    manager = BufferFileManager(tmp_path)
    (tmp_path / "known.csv").write_text("a", encoding="utf-8")
    (tmp_path / "orphan.csv").write_text("b", encoding="utf-8")
    (tmp_path / "half.part").write_text("c", encoding="utf-8")
    (tmp_path / "legacy.tmp").write_text("d", encoding="utf-8")

    orphans = manager.scan_orphans({"known.csv"})
    assert [item.name for item in orphans] == ["orphan.csv"]
    assert orphans[0].size_bytes == 1
    assert orphans[0].modified_at


def test_usage_and_cleanup_partials(tmp_path: Path) -> None:
    manager = BufferFileManager(tmp_path)
    (tmp_path / "a.csv").write_text("12345", encoding="utf-8")
    (tmp_path / "b.csv").write_text("123", encoding="utf-8")
    (tmp_path / "x.part").write_text("ignored", encoding="utf-8")

    usage = manager.usage(threshold_bytes=100)
    assert usage.file_count == 2
    assert usage.total_bytes == 8
    assert usage.exceeded is False

    assert manager.cleanup_partials() == 1
    assert not (tmp_path / "x.part").exists()


def test_ensure_dir_recreates_missing_dir(tmp_path: Path) -> None:
    target = tmp_path / "buffer" / "nested"
    manager = BufferFileManager(target)
    assert manager.ensure_dir() is True
    assert target.is_dir()
    assert manager.ensure_dir() is False


def test_path_for_strips_directories(tmp_path: Path) -> None:
    manager = BufferFileManager(tmp_path)
    assert manager.path_for("../../etc/passwd").parent == tmp_path
