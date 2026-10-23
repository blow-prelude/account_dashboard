"""``/raw/months`` 的口径（C3-B §4.5 / K2）。

三条断言：``month`` 是 ``"2026_06"``（**无** ``raw_`` 前缀）、``count`` 与
预置行数相等、无数据的月份不出现（缺月是常态，按月归档视图不报错）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.conftest import API_PREFIX
from tests.helpers.ingest_state import seed_raw_rows


def test_months_have_no_raw_prefix_and_exact_counts(client: TestClient, db) -> None:
    seed_raw_rows(db.conn, "2026_06", "b" * 32, 3)
    seed_raw_rows(db.conn, "2026_05", "b" * 32, 2)

    body = client.get(f"{API_PREFIX}/raw/months").json()

    assert body["code"] == "OK"
    months = body["data"]
    assert months == [
        {"month": "2026_06", "count": 3},
        {"month": "2026_05", "count": 2},
    ], "按月份降序；month 无 raw_ 前缀（前端 x.month.slice(5) 依赖它）"
    assert "2026_04" not in [item["month"] for item in months], "无数据的月份不出现"


def test_months_empty_when_no_raw_tables(client: TestClient) -> None:
    body = client.get(f"{API_PREFIX}/raw/months").json()

    assert body["data"] == []
