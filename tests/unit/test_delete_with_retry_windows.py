"""``delete_with_retry`` 的 Windows 语义（EX-11，C3-B §4.2）。

Linux 上删打开中的文件不会失败，因此用 monkeypatch 模拟三种系统行为：
``PermissionError``（Windows 句柄未释放）连续两次后成功、``FileNotFoundError``
（幂等）、``OSError``（非占用类错误，重试无意义）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from account_dashboard.infra.buffer_file import BufferFileManager


def test_permission_error_retries_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = BufferFileManager(tmp_path)
    target = tmp_path / "locked.csv"
    calls = {"n": 0}

    def fake_unlink(self: Path) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("文件被占用")
        return None

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    assert manager.delete_with_retry(target, attempts=3, delay=0) is True
    assert calls["n"] == 3, "前两次 PermissionError 后第三次应成功"


def test_file_not_found_counts_as_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """幂等：文件已经没了就算删干净了（重试队列、补删都靠这条）。"""
    manager = BufferFileManager(tmp_path)
    calls = {"n": 0}

    def fake_unlink(self: Path) -> None:
        calls["n"] += 1
        raise FileNotFoundError

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    assert manager.delete_with_retry(tmp_path / "gone.csv", delay=0) is True
    assert calls["n"] == 1, "FileNotFoundError 立即返回，不进入退避重试"


def test_plain_os_error_does_not_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """目录 / 只读文件系统之类的错误，重试三次也是同一个结果。"""
    manager = BufferFileManager(tmp_path)
    calls = {"n": 0}

    def fake_unlink(self: Path) -> None:
        calls["n"] += 1
        raise OSError("只读文件系统")

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    assert manager.delete_with_retry(tmp_path / "ro.csv", attempts=3, delay=0) is False
    assert calls["n"] == 1


def test_all_attempts_exhausted_returns_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = BufferFileManager(tmp_path)
    calls = {"n": 0}

    def fake_unlink(self: Path) -> None:
        calls["n"] += 1
        raise PermissionError("一直被占用")

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    assert manager.delete_with_retry(tmp_path / "locked.csv", attempts=3, delay=0) is False
    assert calls["n"] == 3, "attempts 次都失败才返回 False"


def test_real_delete_with_retry(tmp_path: Path) -> None:
    """不 mock 的真实路径：存在 → 删掉；不存在 → 视为成功。"""
    manager = BufferFileManager(tmp_path)
    target = tmp_path / "real.csv"
    target.write_text("x", encoding="utf-8")
    assert manager.delete_with_retry(target, delay=0) is True
    assert not target.exists()
    assert manager.delete_with_retry(target, delay=0) is True
