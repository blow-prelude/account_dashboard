"""C3 合稿验收补缺：#8（HTTP 层 D-7）与 #12（边界自证）。

#8：删文件失败时 confirm 必须返回 **200 + files_deleted=false**（D-7 对
SDD §7.5「409 E4003」的显式偏离），失败路径入待清理队列，批次仍 ingested。
服务层行为由 ``test_delete_intent.py`` 覆盖，这里守的是**端点层**口径 ——
前端 catch 分支全靠它决定提示文案。

#12：``SELECT DISTINCT status FROM "transaction"`` 只有 ``pending``；
``staging_batch`` 里 ``ingesting`` 计数为 0（D-8：ingesting 永不落库）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.repositories.database import Database

PREFIX = "/api/v1/staging"
SAMPLE = "alipay_sample_gb18030.csv"


def _mapping(client: TestClient, batch_id: str) -> dict[str, Any]:
    preview = client.get(f"{PREFIX}/batches/{batch_id}/preview", params={"limit": 1}).json()[
        "data"
    ]
    payload = dict(preview["detected_fields"])
    payload.update({"direction_map": {}, "amount_scale": 1})
    return payload


def _prepare(client: TestClient, upload, fixtures_dir: Path) -> str:
    batch = upload(fixtures_dir / SAMPLE)
    batch_id = str(batch["id"])
    client.put(f"{PREFIX}/batches/{batch_id}/mapping", json=_mapping(client, batch_id))
    client.post(f"{PREFIX}/batches/{batch_id}/precheck")
    return batch_id


def test_confirm_returns_200_when_file_delete_fails(
    client: TestClient,
    upload,
    fixtures_dir: Path,
    db: Database,
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验收 #8 / D-7：删不掉 → 200 + files_deleted=false + 队列 +1，批次仍 ingested。"""
    monkeypatch.setattr(BufferFileManager, "delete_with_retry", lambda self, path, **kw: False)

    batch_id = _prepare(client, upload, fixtures_dir)
    response = client.post(f"{PREFIX}/batches/{batch_id}/confirm")

    # D-7：不是 409，是 200 + 报告（前端据此提示"已加入待清理列表，数据不受影响"）
    assert response.status_code == 200, response.text
    report = response.json()["data"]
    assert report["inserted"] == 669
    assert report["files_deleted"] is False
    assert report["cleanup_pending"] is True
    assert report["cleanup_id"]

    # 失败路径入队， attempts=1
    queue = db.query_all("SELECT batch_id, status, attempts, reason FROM cleanup_queue")
    assert len(queue) == 1
    assert queue[0]["batch_id"] == batch_id
    assert queue[0]["status"] == "pending"
    assert queue[0]["attempts"] == 1

    # 批次仍 ingested，旗标保持 1（等重试或对账）
    row = db.query_one(
        "SELECT status, pending_delete_flag FROM staging_batch WHERE id = ?", (batch_id,)
    )
    assert row is not None
    assert row["status"] == "ingested"
    assert row["pending_delete_flag"] == 1

    # 数据完整入库（删除失败不影响数据）
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 669

    # 报告端点与之一致（从旗标推导，不是快照副本）
    stored = client.get(f"{PREFIX}/batches/{batch_id}/report").json()["data"]
    assert stored["files_deleted"] is False
    assert stored["cleanup_pending"] is True


def test_boundary_self_evidence(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    """验收 #12 / M6：两条边界 SQL——transaction 只有 pending；ingesting 计数为 0。"""
    batch_id = _prepare(client, upload, fixtures_dir)
    confirm = client.post(f"{PREFIX}/batches/{batch_id}/confirm")
    assert confirm.status_code == 200, confirm.text

    statuses = {
        str(row["status"]) for row in db.query_all('SELECT DISTINCT status FROM "transaction"')
    }
    assert statuses == {"pending"}

    assert db.scalar_int("SELECT COUNT(*) FROM staging_batch WHERE status = 'ingesting'") == 0
    # 反例守卫：C3 收口时 category_* 必须全 NULL（分类归 C4）
    assert (
        db.scalar_int(
            'SELECT COUNT(*) FROM "transaction" WHERE category_l1 IS NOT NULL '
            "OR category_l2 IS NOT NULL"
        )
        == 0
    )
