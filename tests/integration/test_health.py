"""健康检查用例（SDD §6.2.1）。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from account_dashboard import __version__
from account_dashboard.infra.paths import DataPaths
from account_dashboard.repositories.database import Database

API_PREFIX = "/api/v1"


def test_health_ok(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"code", "data", "message"}
    assert body["code"] == "OK"
    assert body["message"] == ""

    data = body["data"]
    assert set(data) == {"status", "version", "data_dir", "db_ok", "backlog"}
    assert data["status"] == "ok"
    assert data["db_ok"] is True
    assert data["version"] == __version__
    assert data["backlog"] == {"cleanup": 0, "orphans": 0}


def test_health_alias(client: TestClient) -> None:
    """启动脚本探测用的无前缀别名。"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["code"] == "OK"


def test_health_reports_data_dir(client: TestClient, paths: DataPaths) -> None:
    data = client.get(f"{API_PREFIX}/health").json()["data"]
    assert Path(data["data_dir"]) == paths.data_dir


def test_health_counts_orphans(client: TestClient, paths: DataPaths) -> None:
    (paths.buffer_dir / "leftover.csv").write_text("x", encoding="utf-8")
    (paths.buffer_dir / "half.tmp").write_text("x", encoding="utf-8")
    backlog = client.get(f"{API_PREFIX}/health").json()["data"]["backlog"]
    assert backlog["orphans"] == 1, "*.tmp 半成品不计入孤儿"


def test_health_counts_cleanup_queue(client: TestClient, db: Database) -> None:
    db.execute(
        "INSERT INTO cleanup_queue(id, batch_id, file_path, reason, attempts, status, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        ("c1", "b1", "D:/tmp/a.csv", "E4003", 0, "pending", "2026-10-22T10:00:00",
         "2026-10-22T10:00:00"),
    )
    backlog = client.get(f"{API_PREFIX}/health").json()["data"]["backlog"]
    assert backlog["cleanup"] == 1


def test_unknown_route_keeps_envelope(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/not-exists")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "data", "message"}
    assert body["code"].startswith("E")
