"""C2 出口契约（从 B 线变体移植）：端点清单、信封形状、分页边界、删除失败入队。

与业务行为用例（``test_staging_*.py``）分工：这里守的是**对外契约不被悄悄改坏** ——
端点少一条前端就 404，C3 端点提前落进来说明越界，分页边界松了前端会传疯。
这些断言在合稿前由 B 线变体维护，合稿后统一用真实样例驱动。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.conftest import API_PREFIX, FIXTURES_DIR

from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.infra.errors import FileDeleteError

EXPECTED_OPERATIONS = {
    ("post", f"{API_PREFIX}/staging/batches"),
    ("get", f"{API_PREFIX}/staging/batches"),
    ("get", f"{API_PREFIX}/staging/batches/{{batch_id}}"),
    ("post", f"{API_PREFIX}/staging/batches/{{batch_id}}/parse"),
    ("get", f"{API_PREFIX}/staging/batches/{{batch_id}}/preview"),
    ("post", f"{API_PREFIX}/staging/batches/{{batch_id}}/discard"),
    ("put", f"{API_PREFIX}/staging/batches/{{batch_id}}/mapping"),
    ("get", f"{API_PREFIX}/staging/templates"),
    ("post", f"{API_PREFIX}/staging/templates"),
    ("post", f"{API_PREFIX}/staging/batches/{{batch_id}}/precheck"),
    ("post", f"{API_PREFIX}/staging/batches/{{batch_id}}/overrides"),
    ("delete", f"{API_PREFIX}/staging/batches/{{batch_id}}/overrides/{{row_no}}"),
    ("get", f"{API_PREFIX}/staging/usage"),
    ("post", f"{API_PREFIX}/staging/ensure-dir"),
    ("get", f"{API_PREFIX}/staging/orphans"),
}


@pytest.fixture
def twelve_batches(upload) -> None:
    for _ in range(12):
        upload(FIXTURES_DIR / "alipay_sample_gb18030.csv")


@pytest.fixture
def one_batch(upload) -> dict:
    return upload(FIXTURES_DIR / "alipay_sample_gb18030.csv")


def test_fifteen_endpoints_registered(client: TestClient) -> None:
    spec = client.get("/api/openapi.json").json()
    actual = {
        (method, path)
        for path, operations in spec["paths"].items()
        if path.startswith(f"{API_PREFIX}/staging")
        for method in operations
    }

    assert actual == EXPECTED_OPERATIONS
    assert len(actual) == 15


def test_c3_endpoints_are_absent(client: TestClient) -> None:
    """C3 的 confirm / report / cleanup 不得提前实现（越界即返工）。"""
    paths = set(client.get("/api/openapi.json").json()["paths"])

    for reserved in (
        f"{API_PREFIX}/staging/batches/{{batch_id}}/confirm",
        f"{API_PREFIX}/staging/batches/{{batch_id}}/report",
        f"{API_PREFIX}/staging/orphans/cleanup",
    ):
        assert reserved not in paths, f"{reserved} 属 C3，不得在 C2 提前实现"


def test_error_envelope_shape(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/staging/batches/missing")

    body = response.json()
    assert body["code"] == "E2001"
    assert body["message"]
    assert set(body) == {"code", "data", "message"}


def test_success_envelope_shape(client: TestClient) -> None:
    body = client.get(f"{API_PREFIX}/staging/usage").json()

    assert body["code"] == "OK"
    assert body["message"] == ""
    assert "file_count" in body["data"]


def test_default_page(client: TestClient, twelve_batches: None) -> None:
    body = client.get(f"{API_PREFIX}/staging/batches").json()["data"]

    assert body["meta"] == {"page": 1, "page_size": 50, "total": 12, "total_pages": 1}
    assert len(body["items"]) == 12


def test_second_page(client: TestClient, twelve_batches: None) -> None:
    body = client.get(
        f"{API_PREFIX}/staging/batches", params={"page": 2, "page_size": 10}
    ).json()["data"]

    assert body["meta"] == {"page": 2, "page_size": 10, "total": 12, "total_pages": 2}
    assert len(body["items"]) == 2


def test_page_beyond_last_is_empty_not_error(client: TestClient, twelve_batches: None) -> None:
    """越界页是空列表而不是报错：前端翻页到最后一页之后不该弹红条。"""
    body = client.get(
        f"{API_PREFIX}/staging/batches", params={"page": 5, "page_size": 10}
    ).json()["data"]

    assert body["items"] == []
    assert body["meta"]["total"] == 12
    assert body["meta"]["total_pages"] == 2


@pytest.mark.parametrize(
    "params",
    [
        {"page_size": 9},
        {"page_size": 201},
        {"page": 0},
        {"page": -3},
    ],
)
def test_invalid_pagination_returns_e1010(
    client: TestClient, twelve_batches: None, params: dict[str, int]
) -> None:
    response = client.get(f"{API_PREFIX}/staging/batches", params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "E1010"


def test_invalid_status_returns_e1008(client: TestClient, twelve_batches: None) -> None:
    """枚举类参数走 E1008，与分页的 E1010 分开（SDD §4.1.2 的分组）。"""
    response = client.get(f"{API_PREFIX}/staging/batches", params={"status": "unknown"})

    assert response.status_code == 422
    assert response.json()["code"] == "E1008"


def test_discard_file_locked_enqueues_cleanup(
    client: TestClient, db, one_batch: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """文件被占用（E4003）：批次照常置 discarded，删不掉的路径进待清理队列等 C3 重试。

    不能因为删不掉就回滚状态 —— 否则用户会反复点丢弃。
    """

    def locked(_self: BufferFileManager, _path: Path) -> None:
        raise FileDeleteError("文件被占用，无法删除")

    monkeypatch.setattr(BufferFileManager, "delete", locked)

    response = client.post(
        f"{API_PREFIX}/staging/batches/{one_batch['id']}/discard", json={"confirm": True}
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "discarded"

    rows = db.query_all("SELECT batch_id, status FROM cleanup_queue")
    assert [row["batch_id"] for row in rows] == [one_batch["id"]]
    assert rows[0]["status"] == "pending"


def test_clean_discard_leaves_no_cleanup_row(
    client: TestClient, db, one_batch: dict
) -> None:
    client.post(f"{API_PREFIX}/staging/batches/{one_batch['id']}/discard", json={"confirm": True})

    assert db.query_all("SELECT * FROM cleanup_queue") == []
