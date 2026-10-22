"""C2B.6 分页与排序：越界 → ``E1010``(422)，``total`` / ``total_pages`` 正确。

分页参数走 ``api/validators.validate_page``（1 ≤ page、10 ≤ page_size ≤ 200），
排序走白名单（C2 只有 ``created_at`` / ``-created_at``，否则 ``E1008``）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.integration.conftest import StagingFlow

from account_dashboard.errors import ErrorCode


@pytest.fixture
def twelve_batches(flow: StagingFlow) -> None:
    for index in range(12):
        flow.upload_ok(file_name=f"bill-{index:02d}.csv")


def test_default_page(api: TestClient, twelve_batches: None) -> None:
    body = api.get("/api/v1/staging/batches").json()["data"]

    assert body["meta"] == {"page": 1, "page_size": 50, "total": 12, "total_pages": 1}
    assert len(body["items"]) == 12


def test_second_page(api: TestClient, twelve_batches: None) -> None:
    body = api.get("/api/v1/staging/batches", params={"page": 2, "page_size": 10}).json()["data"]

    assert body["meta"] == {"page": 2, "page_size": 10, "total": 12, "total_pages": 2}
    assert len(body["items"]) == 2


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"page_size": 9}, ErrorCode.INVALID_PAGINATION),
        ({"page_size": 201}, ErrorCode.INVALID_PAGINATION),
        ({"page": 0}, ErrorCode.INVALID_PAGINATION),
        ({"page": -3}, ErrorCode.INVALID_PAGINATION),
        ({"sort": "updated_at"}, ErrorCode.INVALID_ENUM_VALUE),
        ({"status": "unknown"}, ErrorCode.INVALID_ENUM_VALUE),
    ],
)
def test_invalid_query_params(
    api: TestClient, twelve_batches: None, params: dict[str, object], code: ErrorCode
) -> None:
    response = api.get("/api/v1/staging/batches", params=params)

    assert response.status_code == 422
    assert response.json()["code"] == code.value


def test_status_filter(api: TestClient, flow: StagingFlow, twelve_batches: None) -> None:
    pending = api.get("/api/v1/staging/batches", params={"status": "mapped_pending"}).json()["data"]
    failed = api.get("/api/v1/staging/batches", params={"status": "failed"}).json()["data"]

    assert pending["meta"]["total"] == 12
    assert failed["meta"]["total"] == 0


def test_ascending_sort(api: TestClient, flow: StagingFlow) -> None:
    flow.upload_ok(file_name="a.csv")
    flow.upload_ok(file_name="b.csv")

    ascending = api.get("/api/v1/staging/batches", params={"sort": "created_at"}).json()["data"]
    descending = api.get("/api/v1/staging/batches", params={"sort": "-created_at"}).json()["data"]

    assert len(ascending["items"]) == 2
    assert ascending["items"][0]["id"] == descending["items"][-1]["id"]


def test_page_beyond_last_is_empty_not_error(api: TestClient, twelve_batches: None) -> None:
    body = api.get("/api/v1/staging/batches", params={"page": 5, "page_size": 10}).json()["data"]

    assert body["items"] == []
    assert body["meta"]["total"] == 12
    assert body["meta"]["total_pages"] == 2


def test_override_row_no_path_must_be_positive(api: TestClient, flow: StagingFlow) -> None:
    batch = flow.ready_batch()

    response = api.delete(f"/api/v1/staging/batches/{batch['id']}/overrides/0")

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.INVALID_ENUM_VALUE.value
