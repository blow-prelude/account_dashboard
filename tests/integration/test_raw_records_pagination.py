"""``/raw/{yyyy_mm}/records`` 与 ``/raw/records/{id}``（C3-B §4.5）。

分页边界（``page_size`` 10~200，越界 ``E1010``）、``meta.total`` 正确、
列表项**不带** ``raw_payload``、缺月返回空数组而不是 404。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.conftest import API_PREFIX
from tests.helpers.ingest_state import seed_raw_rows

ROWS = 25


@pytest.fixture
def seeded(client: TestClient, db) -> str:
    seed_raw_rows(db.conn, "2026_06", "b" * 32, ROWS)
    return "2026_06"


def test_pagination_bounds(seeded: str, client: TestClient) -> None:
    for bad in (9, 201):
        response = client.get(
            f"{API_PREFIX}/raw/{seeded}/records", params={"page": 1, "page_size": bad}
        )
        assert response.status_code == 422
        assert response.json()["code"] == "E1010"


def test_first_page_meta_and_no_payload(seeded: str, client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/raw/{seeded}/records", params={"page_size": 10})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["meta"]["total"] == ROWS
    assert data["meta"]["page"] == 1
    assert data["meta"]["total_pages"] == 3
    assert len(data["items"]) == 10
    assert "raw_payload" not in data["items"][0], "列表不带 raw_payload（5 万行时 JSON 会爆）"
    assert data["items"][0]["occurred_at"].startswith("2026-06")


def test_last_page_is_partial(seeded: str, client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/raw/{seeded}/records", params={"page": 3, "page_size": 10})

    data = response.json()["data"]
    assert len(data["items"]) == 5
    assert data["meta"]["total"] == ROWS


def test_missing_month_returns_empty_not_404(client: TestClient) -> None:
    """按月归档视图里缺月是常态：空数组 + meta.total=0。"""
    response = client.get(f"{API_PREFIX}/raw/2026_04/records", params={"page_size": 10})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["items"] == []
    assert data["meta"]["total"] == 0


def test_bad_month_format_is_e1008(client: TestClient) -> None:
    for bad in ("2026-06", "raw_2026_06", "2026_6", "latest"):
        response = client.get(f"{API_PREFIX}/raw/{bad}/records")
        assert response.status_code == 422, bad
        assert response.json()["code"] == "E1008", bad


def test_detail_carries_raw_payload(seeded: str, client: TestClient) -> None:
    listing = client.get(f"{API_PREFIX}/raw/{seeded}/records", params={"page_size": 10}).json()
    record_id = listing["data"]["items"][0]["id"]

    response = client.get(f"{API_PREFIX}/raw/records/{record_id}")

    assert response.status_code == 200
    detail = response.json()["data"]
    assert detail["id"] == record_id
    assert isinstance(detail["raw_payload"], dict)
    assert "交易时间" in detail["raw_payload"], "raw_payload 保留整行原貌（I7）"


def test_detail_unknown_id_is_e2001(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/raw/records/999999")

    assert response.status_code == 404
    assert response.json()["code"] == "E2001"
