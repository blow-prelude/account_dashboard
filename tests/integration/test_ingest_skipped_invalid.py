"""不可解析行的归宿（D-6 / C3-A §6.1）。

造 3 行时间/金额不可解析的数据：既不写 raw 也不写 ``transaction``，
只进报告的 ``skipped_invalid`` 与 ``report_json.skipped[]`` 明细
（文件会被删，报告是这批行唯一的留痕）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from account_dashboard.repositories.database import Database

PREFIX = "/api/v1/staging"

BROKEN_CSV = (
    "交易时间,交易分类,交易对方,商品说明,收/支,金额,收/付款方式,交易状态\n"
    "2026-10-01 10:00:00,餐饮美食,某某便利店,矿泉水,支出,12.30,微信,交易成功\n"
    "不是时间,餐饮美食,某某便利店,面包,支出,12.30,微信,交易成功\n"
    "2026-10-01 10:00:02,餐饮美食,某某便利店,可乐,支出,abc,微信,交易成功\n"
    "2026-10-01 10:00:03,餐饮美食,某某便利店,纸巾,收入,3.50,微信,交易成功\n"
    ",,餐饮美食,某某便利店,矿泉水,支出,12.30,微信,交易成功\n"
)


def _mapping(client: TestClient, batch_id: str) -> dict[str, Any]:
    preview = client.get(f"{PREFIX}/batches/{batch_id}/preview", params={"limit": 1}).json()["data"]
    payload = dict(preview["detected_fields"])
    payload.update({"direction_map": {}, "amount_scale": 1})
    return payload


@pytest.fixture
def broken_batch(client: TestClient, upload, tmp_path: Path) -> str:
    target = tmp_path / "broken_rows.csv"
    target.write_text(BROKEN_CSV, encoding="utf-8")
    batch = upload(target)
    client.put(f"{PREFIX}/batches/{batch['id']}/mapping", json=_mapping(client, batch["id"]))
    return str(batch["id"])


def test_invalid_rows_are_skipped_with_details(
    client: TestClient, broken_batch: str, db: Database
) -> None:
    batch_id = broken_batch
    client.post(f"{PREFIX}/batches/{batch_id}/precheck")
    response = client.post(f"{PREFIX}/batches/{batch_id}/confirm")
    assert response.status_code == 200, response.text
    report = response.json()["data"]

    assert report["total"] == 5
    assert report["inserted"] == 2
    assert report["skipped_invalid"] == 3
    assert report["skipped_dup"] == 0
    assert report["pending"] == 2
    assert report["monthly"] == {"raw_2026_10": 2}
    assert report["total"] == (
        report["inserted"] + report["skipped_dup"] + report["skipped_invalid"]
    )

    # raw 与 transaction 里都没有这 3 行（按 row_no 核对）
    raw_rows = [
        int(row["row_no"])
        for row in db.query_all("SELECT row_no FROM raw_2026_10 ORDER BY row_no")
    ]
    txn_rows = [
        int(row["row_no"])
        for row in db.query_all('SELECT row_no FROM "transaction" ORDER BY row_no')
    ]
    assert raw_rows == [1, 4]
    assert txn_rows == [1, 4]

    # report_json.skipped[] 明细：原因 + 原始值
    stored = db.query_one("SELECT report_json FROM staging_batch WHERE id = ?", (batch_id,))
    payload = __import__("json").loads(str(stored["report_json"]))
    skipped = payload["skipped"]
    assert len(skipped) == 3
    reasons = {item["row_no"]: item["reason"] for item in skipped}
    assert reasons == {2: "TIME_PARSE", 3: "AMOUNT_PARSE", 5: "TIME_PARSE"}
    by_row = {item["row_no"]: item for item in skipped}
    assert by_row[2]["raw"] == "不是时间"
    assert by_row[3]["raw"] == "abc"
    assert by_row[2]["field"] == "occurred_at"
    assert by_row[3]["field"] == "amount"

    # include_skipped=true 才把明细带给前端
    detail = client.get(
        f"{PREFIX}/batches/{batch_id}/report", params={"include_skipped": True}
    ).json()["data"]
    assert len(detail["skipped"]) == 3
    assert detail["skipped_invalid"] == 3
    brief = client.get(f"{PREFIX}/batches/{batch_id}/report").json()["data"]
    assert brief["skipped"] == []


def test_invalid_rows_do_not_block_batch_archive(
    client: TestClient, broken_batch: str, db: Database
) -> None:
    """有无效行不影响批次归档与文件删除意图（D-6：报告即留痕）。"""
    batch_id = broken_batch
    client.post(f"{PREFIX}/batches/{batch_id}/precheck")
    response = client.post(f"{PREFIX}/batches/{batch_id}/confirm")
    assert response.status_code == 200
    assert response.json()["data"]["files_deleted"] is True

    row = db.query_one("SELECT status FROM staging_batch WHERE id = ?", (batch_id,))
    assert row is not None and row["status"] == "ingested"
