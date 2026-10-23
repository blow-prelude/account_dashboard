"""同一文件二次入库（EX-09 / C3-A §6.1）。

断言：``inserted=0``、``skipped_dup=669``、批次仍 ``ingested``（归档），
且**不建任何新 raw 表**、``transaction`` 不翻倍。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from account_dashboard.repositories.database import Database

PREFIX = "/api/v1/staging"
SAMPLE = "alipay_sample_gb18030.csv"


def _mapping(client: TestClient, batch_id: str) -> dict[str, Any]:
    preview = client.get(f"{PREFIX}/batches/{batch_id}/preview", params={"limit": 1}).json()["data"]
    payload = dict(preview["detected_fields"])
    payload.update({"direction_map": {}, "amount_scale": 1})
    return payload


def prepare(client: TestClient, upload, fixtures_dir: Path, name: str = SAMPLE) -> str:
    batch = upload(fixtures_dir / name)
    client.put(f"{PREFIX}/batches/{batch['id']}/mapping", json=_mapping(client, batch["id"]))
    return str(batch["id"])


def _confirm(client: TestClient, batch_id: str) -> dict[str, Any]:
    response = client.post(f"{PREFIX}/batches/{batch_id}/confirm")
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


def _raw_table_count(db: Database) -> int:
    return db.scalar_int(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'raw_%'"
    )


def test_same_file_second_ingest_is_all_dup(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    first = prepare(client, upload, fixtures_dir)
    client.post(f"{PREFIX}/batches/{first}/precheck")
    first_report = _confirm(client, first)
    assert first_report["inserted"] == 669

    second = prepare(client, upload, fixtures_dir)
    client.post(f"{PREFIX}/batches/{second}/precheck")
    second_report = _confirm(client, second)

    assert second_report["total"] == 669
    assert second_report["inserted"] == 0
    assert second_report["skipped_dup"] == 669
    assert second_report["skipped_invalid"] == 0
    assert second_report["pending"] == 0
    # 全重复批次一个 raw 表都不新建（只增不改 + 无数据月份不建表的合流）
    assert second_report["monthly"] == {}
    assert second_report["total"] == (
        second_report["inserted"] + second_report["skipped_dup"] + second_report["skipped_invalid"]
    )

    # 数据不翻倍
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 669
    assert _raw_table_count(db) == 5

    # 批次照常归档（EX-09）
    detail = client.get(f"{PREFIX}/batches/{second}").json()["data"]
    assert detail["status"] == "ingested"

    # report_json 的 skipped[] 有 669 条 DUP 明细（include_skipped 才返回）
    row = db.query_one("SELECT report_json FROM staging_batch WHERE id = ?", (second,))
    stored = json.loads(str(row["report_json"]))
    assert len(stored["skipped"]) == 669
    assert {item["reason"] for item in stored["skipped"]} == {"DUP"}
    assert stored["skipped"][0]["row_no"] == 1

    detail_report = client.get(
        f"{PREFIX}/batches/{second}/report", params={"include_skipped": True}
    ).json()["data"]
    assert len(detail_report["skipped"]) == 669
    assert detail_report["skipped_dup"] == 669
