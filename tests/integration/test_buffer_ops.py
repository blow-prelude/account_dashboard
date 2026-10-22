"""C2B.6 缓冲区运维端点：占用统计、目录重建、孤儿扫描、丢弃删文件。

四个端点都是"用户看得见的运维动作"，所以断言点都落在**磁盘事实**上（文件在不在、
大小对不对），而不是只看接口返回 200。

Windows 特有的一条：``discard`` 时文件被占用 → ``409 E4003`` 且**状态不变**
（C2 是同步删除；C3 会改成"先置状态 + 入待清理队列"）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.integration.conftest import StagingFlow, buffer_files, set_buffer_threshold

from account_dashboard.errors import ErrorCode
from account_dashboard.infra.buffer_file import TMP_SUFFIX


def test_usage_counts_files_and_threshold(api: TestClient, flow: StagingFlow, paths) -> None:
    flow.upload_ok(content=b"x" * 2048)

    payload = api.get("/api/v1/staging/usage").json()["data"]

    assert payload["file_count"] == 1
    assert payload["total_bytes"] == 2048
    assert payload["threshold"] == 500 * 1024 * 1024, "默认阈值 500MB（setting 缺省）"
    assert payload["exceeded"] is False


def test_usage_threshold_follows_setting(api: TestClient, db, flow: StagingFlow) -> None:
    set_buffer_threshold(db, 10)  # 最小可配阈值 10MB；单文件上限 5MB，所以要攒 3 个才超
    four_mb = b"x" * (4 * 1024 * 1024)

    assert flow.upload_ok(content=four_mb)["status"] == "mapped_pending"
    assert api.get("/api/v1/staging/usage").json()["data"]["exceeded"] is False

    flow.upload_ok(content=four_mb)
    flow.upload_ok(content=four_mb)

    payload = api.get("/api/v1/staging/usage").json()["data"]
    assert payload["threshold"] == 10 * 1024 * 1024
    assert payload["file_count"] == 3
    assert payload["exceeded"] is True


def test_ensure_dir_recreates_missing_buffer(api: TestClient, flow: StagingFlow, paths) -> None:
    flow.upload_ok()
    shutil.rmtree(paths.buffer_dir)
    assert not paths.buffer_dir.exists()

    payload = api.post("/api/v1/staging/ensure-dir").json()["data"]

    assert payload["created"] is True
    assert paths.buffer_dir.is_dir()
    assert Path(payload["path"]) == paths.buffer_dir

    # 重建后可以继续上传（EX-23 之后用户要能自愈）
    assert flow.upload_ok()["status"] == "mapped_pending"


def test_ensure_dir_is_idempotent(api: TestClient, paths) -> None:
    api.post("/api/v1/staging/ensure-dir")

    payload = api.post("/api/v1/staging/ensure-dir").json()["data"]

    assert payload["created"] is False


def test_orphans_list_ignores_tmp(api: TestClient, flow: StagingFlow, paths) -> None:
    flow.upload_ok()
    (paths.buffer_dir / "stray.csv").write_bytes(b"leftover")
    (paths.buffer_dir / f"crashed{TMP_SUFFIX}").write_bytes(b"half")

    payload = api.get("/api/v1/staging/orphans").json()["data"]

    names = [item["name"] for item in payload]
    assert names == ["stray.csv"], ".tmp 是崩溃残片，归 cleanup_partials 处理"
    assert payload[0]["size"] == len(b"leftover")


def test_orphans_empty_after_discard(api: TestClient, flow: StagingFlow, paths) -> None:
    batch = flow.upload_ok()

    api.post(f"/api/v1/staging/batches/{batch['id']}/discard")

    assert api.get("/api/v1/staging/orphans").json()["data"] == []
    assert buffer_files(paths) == []


def test_discard_deletes_file_and_sets_status(api: TestClient, flow: StagingFlow, paths) -> None:
    batch = flow.upload_ok()
    assert len(buffer_files(paths)) == 1

    payload = api.post(f"/api/v1/staging/batches/{batch['id']}/discard").json()["data"]

    assert payload["status"] == "discarded"
    assert buffer_files(paths) == []
    assert flow.detail(batch["id"])["file_exists"] is False


def test_discard_requires_confirm(api: TestClient, flow: StagingFlow) -> None:
    batch = flow.upload_ok()

    response = api.post(f"/api/v1/staging/batches/{batch['id']}/discard", json={"confirm": False})

    assert response.status_code == 422
    assert flow.detail(batch["id"])["status"] == "mapped_pending"


def test_discard_failure_on_locked_file_keeps_state(
    api: TestClient, flow: StagingFlow, paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = flow.upload_ok()

    def locked(_path: str) -> None:
        raise PermissionError("文件被占用")

    monkeypatch.setattr("account_dashboard.infra.buffer_file.os.remove", locked)

    response = api.post(f"/api/v1/staging/batches/{batch['id']}/discard")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == ErrorCode.FILE_DELETE_FAILED.value
    assert "占用" in body["message"]
    assert flow.detail(batch["id"])["status"] == "mapped_pending", "删不掉就不能置已丢弃"
    assert len(buffer_files(paths)) == 1
