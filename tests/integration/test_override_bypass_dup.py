"""override 绕过指纹去重（P0-1 / C3-A §4.2）。

预检阶段 override 只改 label；**入库阶段才第一次影响真实写入**：
override 行即使 ``fp`` 命中也入库，并把「强制新增」原因搬到主数据行上
（PRD：``override_reason``，前端抽屉直接展示）。
"""

from __future__ import annotations

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


def test_override_row_bypasses_fingerprint_dup(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    first = prepare(client, upload, fixtures_dir)
    client.post(f"{PREFIX}/batches/{first}/precheck")
    _confirm(client, first)

    second = prepare(client, upload, fixtures_dir)
    precheck = client.post(f"{PREFIX}/batches/{second}/precheck").json()["data"]
    target = precheck["rows"][7]
    assert target["label"] == "dup"  # 同一份文件，fp 全命中

    created = client.post(
        f"{PREFIX}/batches/{second}/overrides",
        json={"row_no": target["row_no"], "reason": "确认为独立消费", "note": "小票已核对"},
    )
    assert created.status_code == 200

    report = _confirm(client, second)
    assert report["inserted"] == 1
    assert report["skipped_dup"] == 668
    assert report["skipped_invalid"] == 0
    assert report["monthly"] and sum(report["monthly"].values()) == 1

    # 该 fp 在库里出现两次（原始 + 强制新增）
    fp = target["fingerprint"]
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction" WHERE fp = ?', (fp,)) == 2

    # 主数据行带「强制新增」原因（PRD override_reason，前端抽屉展示）
    forced = db.query_one(
        'SELECT * FROM "transaction" WHERE batch_id = ? AND row_no = ?',
        (second, target["row_no"]),
    )
    assert forced is not None
    assert forced["override_reason"] == "确认为独立消费"
    assert forced["override_at"]

    # 没有 override 的重复行仍然被跳过（对照）
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction" WHERE batch_id = ?', (second,)) == 1


def test_without_override_row_is_skipped(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    """对照组：同一行没有 override → 走 skipped_dup。"""
    first = prepare(client, upload, fixtures_dir)
    client.post(f"{PREFIX}/batches/{first}/precheck")
    _confirm(client, first)

    second = prepare(client, upload, fixtures_dir)
    client.post(f"{PREFIX}/batches/{second}/precheck")
    report = _confirm(client, second)
    assert report["inserted"] == 0
    assert report["skipped_dup"] == 669
