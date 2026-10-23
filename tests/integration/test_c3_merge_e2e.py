"""C3 合稿 M3：真实样例端到端（合稿文档 §5 M3 + 验收 #1/#2/#3/#4）。

两线合并后的一次完整穿越：上传 → 映射 → 预检 → confirm（事务 + 真实删除）
→ ``/raw/months``（B 线读路径）与报告 ``monthly``（A 线写路径）逐月相等
→ 同一文件二次入库全量重复。

微信 689（172/114/153/142/108）与支付宝 669（101/136/182/143/107）
两条都跑 —— 前者是 B 线样例，后者是 A 线样例，合稿的意义就是让它们在同
一个进程里相遇。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from account_dashboard.repositories.database import Database

PREFIX = "/api/v1/staging"
RAW_PREFIX = "/api/v1/raw"

WECHAT = "wechat_sample_sanitized.xlsx"
ALIPAY = "alipay_sample_gb18030.csv"

WECHAT_MONTHLY = {
    "raw_2026_06": 172,
    "raw_2026_07": 114,
    "raw_2026_08": 153,
    "raw_2026_09": 142,
    "raw_2026_10": 108,
}
ALIPAY_MONTHLY = {
    "raw_2026_06": 101,
    "raw_2026_07": 136,
    "raw_2026_08": 182,
    "raw_2026_09": 143,
    "raw_2026_10": 107,
}


def _mapping(client: TestClient, batch_id: str) -> dict[str, Any]:
    preview = client.get(f"{PREFIX}/batches/{batch_id}/preview", params={"limit": 1}).json()[
        "data"
    ]
    payload = dict(preview["detected_fields"])
    payload.update({"direction_map": {}, "amount_scale": 1})
    return payload


def _import_full(
    client: TestClient, upload, fixtures_dir: Path, sample: str
) -> tuple[str, dict[str, Any]]:
    batch = upload(fixtures_dir / sample)
    batch_id = str(batch["id"])
    client.put(f"{PREFIX}/batches/{batch_id}/mapping", json=_mapping(client, batch_id))
    client.post(f"{PREFIX}/batches/{batch_id}/precheck")
    response = client.post(f"{PREFIX}/batches/{batch_id}/confirm")
    assert response.status_code == 200, response.text
    return batch_id, dict(response.json()["data"])


def _raw_counts(client: TestClient, db: Database) -> dict[str, int]:
    tables = [
        str(row["name"])
        for row in db.query_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'raw_%' "
            "ORDER BY name"
        )
    ]
    return {name: db.scalar_int(f"SELECT COUNT(*) FROM {name}") for name in tables}


def _months(client: TestClient) -> dict[str, int]:
    body = client.get(f"{RAW_PREFIX}/months").json()
    assert body["code"] == "OK"
    return {item["month"]: item["count"] for item in body["data"]}


def test_wechat_full_import_end_to_end(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    """验收 #2：微信 689 全量入库，5 表逐月 172/114/153/142/108。"""
    batch_id, report = _import_full(client, upload, fixtures_dir, WECHAT)

    assert report["total"] == 689
    assert report["inserted"] == 689
    assert report["skipped_dup"] == 0
    assert report["skipped_invalid"] == 0
    assert report["pending"] == 689
    assert report["monthly"] == WECHAT_MONTHLY
    assert sum(report["monthly"].values()) == report["inserted"]
    assert report["total"] == (
        report["inserted"] + report["skipped_dup"] + report["skipped_invalid"]
    )
    # M2 后真实删除
    assert report["files_deleted"] is True

    assert _raw_counts(client, db) == WECHAT_MONTHLY

    # 验收 #4：/raw/months 与报告 monthly 逐月相等（K2：month 为 2026_06 形态）
    months = _months(client)
    assert months == {
        "2026_06": 172,
        "2026_07": 114,
        "2026_08": 153,
        "2026_09": 142,
        "2026_10": 108,
    }
    assert {f"raw_{month}": count for month, count in months.items()} == report["monthly"]

    detail = client.get(f"{PREFIX}/batches/{batch_id}").json()["data"]
    assert detail["status"] == "ingested"
    assert detail["report"]["inserted"] == 689


def test_alipay_full_import_end_to_end(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    """验收 #1：支付宝 669 全量入库（A 线主样例在合稿树上的复跑）。"""
    batch_id, report = _import_full(client, upload, fixtures_dir, ALIPAY)

    assert report["inserted"] == 669
    assert report["monthly"] == ALIPAY_MONTHLY
    assert report["skipped_dup"] == 0
    assert report["skipped_invalid"] == 0

    assert _raw_counts(client, db) == ALIPAY_MONTHLY
    assert {f"raw_{month}": count for month, count in _months(client).items()} == ALIPAY_MONTHLY

    detail = client.get(f"{PREFIX}/batches/{batch_id}").json()["data"]
    assert detail["status"] == "ingested"


def test_second_import_of_same_file_is_all_dup(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    """验收 #3：同一文件二次入库 → inserted=0、skipped_dup=669、批次 ingested、文件已删。"""
    first_id, first = _import_full(client, upload, fixtures_dir, ALIPAY)
    assert first["inserted"] == 669

    second_id, second = _import_full(client, upload, fixtures_dir, ALIPAY)

    assert second["total"] == 669
    assert second["inserted"] == 0
    assert second["skipped_dup"] == 669
    assert second["skipped_invalid"] == 0
    # EX-09：全重复批次不建新表、raw 行数不变
    assert _raw_counts(client, db) == ALIPAY_MONTHLY
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 669
    # 批次仍要归档（ingested），且第二次的文件也被真实删除
    detail = client.get(f"{PREFIX}/batches/{second_id}").json()["data"]
    assert detail["status"] == "ingested"
    row = db.query_one(
        "SELECT stored_name, pending_delete_flag FROM staging_batch WHERE id = ?", (second_id,)
    )
    assert row is not None
    assert row["pending_delete_flag"] == 0
    # 两个批次的报告各自独立（都记载"全量重复"这一事实）
    second_detail = client.get(f"{PREFIX}/batches/{second_id}/report").json()["data"]
    assert second_detail["inserted"] == 0
    assert second_detail["skipped_dup"] == 669
