"""C2B.1 磁盘余量（EX-17）：余量不足 → 507 E4001，且不留临时文件、不建批次。

注入点是 ``buffer_file.free_bytes``（模块级函数）：只替换"读磁盘"这一个动作，
被测的判定逻辑（每 1MB 复查、异常清理）保持真实。
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.integration.conftest import StagingFlow, buffer_files

from account_dashboard.errors import AppError, ErrorCode
from account_dashboard.infra.buffer_file import TMP_SUFFIX, BufferFileManager


def test_upload_rejected_when_disk_is_full(
    api: TestClient,
    flow: StagingFlow,
    paths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("account_dashboard.infra.buffer_file.free_bytes", lambda _path: 1024)

    response = flow.upload()

    assert response.status_code == 507
    body = response.json()
    assert body["code"] == ErrorCode.DISK_FULL.value
    assert "空间不足" in body["message"]
    assert buffer_files(paths) == [], "余量不足不得留下任何文件（含 .tmp）"

    listing = api.get("/api/v1/staging/batches").json()["data"]
    assert listing["meta"]["total"] == 0, "落盘失败不得留下批次记录（K7）"


def test_free_space_rechecked_while_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """第一次够、第二次不够：必须在中途失败并清理半成品。"""
    directory = tmp_path / "buffer"
    directory.mkdir()
    manager = BufferFileManager(directory, min_free_bytes=1000)

    calls = {"count": 0}

    def shrinking(_path: Path) -> int:
        calls["count"] += 1
        return 10_000 if calls["count"] == 1 else 0

    monkeypatch.setattr("account_dashboard.infra.buffer_file.free_bytes", shrinking)

    with pytest.raises(AppError) as excinfo:
        manager.save_stream(io.BytesIO(b"z" * (2 * 1024 * 1024)), "big.csv", 0)

    assert excinfo.value.code is ErrorCode.DISK_FULL
    assert calls["count"] >= 2, "必须边写边查，不能只在入口查一次"
    assert [item.name for item in directory.iterdir() if item.name.endswith(TMP_SUFFIX)] == []
    assert list(directory.iterdir()) == []
