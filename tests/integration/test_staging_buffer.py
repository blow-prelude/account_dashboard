"""缓冲区维护与丢弃（EX-13 / EX-17 / EX-23，C2 出口检查表）。

这组用例同时守住 C2 的边界：全程结束后 ``transaction`` 仍为 0 行。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from account_dashboard.infra.paths import DataPaths
from account_dashboard.repositories.database import Database

PREFIX = "/api/v1/staging"


def test_orphans_listed_and_partials_ignored(
    client: TestClient, upload, fixtures_dir: Path, paths: DataPaths
) -> None:
    upload(fixtures_dir / "alipay_sample_gb18030.csv")
    (paths.buffer_dir / "leftover.csv").write_text("x", encoding="utf-8")
    (paths.buffer_dir / "half.part").write_text("x", encoding="utf-8")
    (paths.buffer_dir / "legacy.tmp").write_text("x", encoding="utf-8")

    orphans = client.get(f"{PREFIX}/orphans").json()["data"]
    assert [item["name"] for item in orphans] == ["leftover.csv"]
    assert orphans[0]["size_bytes"] == 1

    health = client.get("/api/v1/health").json()["data"]
    assert health["backlog"]["orphans"] == 1, "健康检查与孤儿列表口径必须一致"


def test_usage_reports_threshold(
    client: TestClient, upload, fixtures_dir: Path
) -> None:
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv")
    usage = client.get(f"{PREFIX}/usage").json()["data"]
    assert usage["file_count"] == 1
    assert usage["total_bytes"] == batch["file_size"]
    assert usage["threshold_bytes"] == 500 * 1024 * 1024
    assert usage["exceeded"] is False
    assert usage["oldest_at"]


def test_ensure_dir_recreates_buffer(
    client: TestClient, upload, fixtures_dir: Path, paths: DataPaths
) -> None:
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv")
    shutil.rmtree(paths.buffer_dir)
    assert not paths.buffer_dir.exists()

    response = client.post(f"{PREFIX}/ensure-dir")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["created"] is True
    assert paths.buffer_dir.is_dir()

    detail = client.get(f"{PREFIX}/batches/{batch['id']}").json()["data"]
    assert detail["file_exists"] is False

    # 状态守卫先于文件存在性：mapped_pending 不允许重解析，只能重新上传
    parse = client.post(f"{PREFIX}/batches/{batch['id']}/parse")
    assert parse.status_code == 409
    assert parse.json()["code"] == "E2002"

    preview = client.get(f"{PREFIX}/batches/{batch['id']}/preview")
    assert preview.status_code == 500
    assert preview.json()["code"] == "E4004"
    assert "重新上传" in preview.json()["message"]


def test_discard_requires_confirm_and_deletes_file(
    client: TestClient, upload, fixtures_dir: Path, paths: DataPaths
) -> None:
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv")
    files_before = list(paths.buffer_dir.iterdir())
    assert len(files_before) == 1

    refused = client.post(f"{PREFIX}/batches/{batch['id']}/discard", json={})
    assert refused.status_code == 422
    assert refused.json()["code"] == "E1008"
    assert (paths.buffer_dir / files_before[0].name).exists()

    done = client.post(f"{PREFIX}/batches/{batch['id']}/discard", json={"confirm": True})
    assert done.status_code == 200
    assert done.json()["data"]["status"] == "discarded"
    assert done.json()["data"]["file_exists"] is False
    assert list(paths.buffer_dir.iterdir()) == []

    again = client.post(f"{PREFIX}/batches/{batch['id']}/discard", json={"confirm": True})
    assert again.status_code == 409
    assert again.json()["code"] == "E2002"

    assert client.get(f"{PREFIX}/orphans").json()["data"] == []


def test_row_limit_exceeded(
    client: TestClient,
    upload,
    fixtures_dir: Path,
    monkeypatch,
    db: Database,
) -> None:
    """E1006：超过行数上限要立即停止并提示分批，而不是继续吃内存。"""
    monkeypatch.setattr("account_dashboard.infra.parsers.base.MAX_ROWS", 5)
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv")
    assert batch["status"] == "failed"
    assert "分批" in (batch["fail_reason"] or "")

    retry = client.post(f"{PREFIX}/batches/{batch['id']}/parse")
    assert retry.status_code == 422
    assert retry.json()["code"] == "E1006"
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 0


def test_preview_after_file_lost(
    client: TestClient, upload, fixtures_dir: Path, paths: DataPaths
) -> None:
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv")
    for item in paths.buffer_dir.iterdir():
        item.unlink()
    response = client.get(f"{PREFIX}/batches/{batch['id']}/preview")
    assert response.status_code == 500
    assert response.json()["code"] == "E4004"
