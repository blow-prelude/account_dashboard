"""C2B 出口检查：15 个端点齐备、响应恒为三段式、路径参数错误码正确。

这条用例守的是"契约完整性"而不是业务行为：C2-B §5.1 的 15 行必须一条不少、
一条不多（C3 的 confirm/report/cleanup 不在其中）。少一条前端会 404，多一条说明越界。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.integration.conftest import StagingFlow

from account_dashboard.errors import ErrorCode

EXPECTED_OPERATIONS = {
    ("post", "/api/v1/staging/batches"),
    ("get", "/api/v1/staging/batches"),
    ("get", "/api/v1/staging/batches/{batch_id}"),
    ("post", "/api/v1/staging/batches/{batch_id}/parse"),
    ("get", "/api/v1/staging/batches/{batch_id}/preview"),
    ("post", "/api/v1/staging/batches/{batch_id}/discard"),
    ("put", "/api/v1/staging/batches/{batch_id}/mapping"),
    ("get", "/api/v1/staging/templates"),
    ("post", "/api/v1/staging/templates"),
    ("post", "/api/v1/staging/batches/{batch_id}/precheck"),
    ("post", "/api/v1/staging/batches/{batch_id}/overrides"),
    ("delete", "/api/v1/staging/batches/{batch_id}/overrides/{row_no}"),
    ("get", "/api/v1/staging/usage"),
    ("post", "/api/v1/staging/ensure-dir"),
    ("get", "/api/v1/staging/orphans"),
}


def test_fifteen_endpoints_registered(api: TestClient) -> None:
    spec = api.get("/api/openapi.json").json()
    actual = {
        (method, path)
        for path, operations in spec["paths"].items()
        if path.startswith("/api/v1/staging")
        for method in operations
    }

    assert actual == EXPECTED_OPERATIONS
    assert len(actual) == 15


def test_c3_endpoints_are_absent(api: TestClient) -> None:
    spec = api.get("/api/openapi.json").json()
    paths = set(spec["paths"])

    for reserved in (
        "/api/v1/staging/batches/{batch_id}/confirm",
        "/api/v1/staging/batches/{batch_id}/report",
        "/api/v1/staging/orphans/cleanup",
    ):
        assert reserved not in paths, f"{reserved} 属 C3，不得在 C2 提前实现"


def test_error_envelope_shape(api: TestClient) -> None:
    response = api.get("/api/v1/staging/batches/missing")

    body = response.json()
    assert body["code"] == ErrorCode.BATCH_NOT_FOUND.value
    assert body["message"]
    assert set(body) == {"code", "data", "message"}


def test_success_envelope_shape(api: TestClient, flow: StagingFlow) -> None:
    body = api.get("/api/v1/staging/usage").json()

    assert body["code"] == "OK"
    assert body["message"] == ""
    assert "file_count" in body["data"]


def test_router_has_no_sqlite_or_repo_imports() -> None:
    """分层断言（与 tests/integration/test_layering.py 呼应，这里锁单个文件）。"""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "account_dashboard"
        / "api"
        / "routers"
        / "staging.py"
    ).read_text(encoding="utf-8")

    assert "import sqlite3" not in source
    assert "repositories" not in source
    assert "openpyxl" not in source and "import csv" not in source
