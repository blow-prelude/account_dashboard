"""映射与渠道模板（I-MP-01，FR-03 / EX-20）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

PREFIX = "/api/v1/staging"


def detected_mapping(client: TestClient, batch_id: str) -> dict[str, Any]:
    preview = client.get(f"{PREFIX}/batches/{batch_id}/preview", params={"limit": 1}).json()["data"]
    payload = dict(preview["detected_fields"])
    payload.update({"direction_map": {}, "amount_scale": 1})
    return payload


def test_save_mapping_persists(client: TestClient, upload, fixtures_dir: Path) -> None:
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv")
    mapping = detected_mapping(client, batch["id"])

    response = client.put(f"{PREFIX}/batches/{batch['id']}/mapping", json=mapping)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "mapped_pending"
    assert data["template_id"] is None

    detail = client.get(f"{PREFIX}/batches/{batch['id']}").json()["data"]
    assert detail["mapped_fields"]["occurred_at"] == mapping["occurred_at"]
    assert detail["mapped_fields"]["amount"] == mapping["amount"]


def test_missing_core_field_returns_e1007(client: TestClient, upload, fixtures_dir: Path) -> None:
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv")
    mapping = detected_mapping(client, batch["id"])
    mapping["item"] = None

    response = client.put(f"{PREFIX}/batches/{batch['id']}/mapping", json=mapping)
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "E1007"
    assert "商品说明" in body["message"]


def test_column_index_out_of_range(client: TestClient, upload, fixtures_dir: Path) -> None:
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv")
    mapping = detected_mapping(client, batch["id"])
    mapping["occurred_at"] = 99

    response = client.put(f"{PREFIX}/batches/{batch['id']}/mapping", json=mapping)
    assert response.status_code == 422
    assert response.json()["code"] == "E1008"


def test_invalid_amount_scale(client: TestClient, upload, fixtures_dir: Path) -> None:
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv")
    mapping = detected_mapping(client, batch["id"])
    mapping["amount_scale"] = 10

    response = client.put(f"{PREFIX}/batches/{batch['id']}/mapping", json=mapping)
    assert response.status_code == 422
    assert response.json()["code"] == "E1008"


def test_preview_follows_mapping(client: TestClient, upload, fixtures_dir: Path) -> None:
    """映射保存后再预览，列含义必须与映射一致（换列后值跟着换）。"""
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv")
    mapping = detected_mapping(client, batch["id"])
    baseline = client.get(f"{PREFIX}/batches/{batch['id']}/preview").json()["data"]["rows"][0]

    swapped = dict(mapping)
    swapped["counterparty"], swapped["item"] = mapping["item"], mapping["counterparty"]
    client.put(f"{PREFIX}/batches/{batch['id']}/mapping", json=swapped)

    after = client.get(f"{PREFIX}/batches/{batch['id']}/preview").json()["data"]["rows"][0]
    assert after["counterparty"] == baseline["item"]
    assert after["item"] == baseline["counterparty"]


def test_mapping_on_unparsed_batch_conflicts(
    client: TestClient, upload, fixtures_dir: Path
) -> None:
    batch = upload(fixtures_dir / "no_header.csv")  # 解析失败 → failed
    mapping = {"occurred_at": 0, "amount": 1, "direction": 2, "counterparty": 3, "item": 4}
    response = client.put(f"{PREFIX}/batches/{batch['id']}/mapping", json=mapping)
    # failed 允许手动映射（EX-03），但本文件只有 3 列 → 列索引越界
    assert response.status_code == 422
    assert response.json()["code"] == "E1008"


def test_template_three_policies(client: TestClient, upload, fixtures_dir: Path) -> None:
    """I-MP-01：abort → 409；overwrite → 旧默认降级；save_as → 新行。"""
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv")
    mapping = detected_mapping(client, batch["id"])

    first = client.put(
        f"{PREFIX}/batches/{batch['id']}/mapping",
        json={**mapping, "save_template": True, "template_policy": "abort"},
    )
    assert first.status_code == 200
    template_id = first.json()["data"]["template_id"]
    assert template_id

    templates = client.get(f"{PREFIX}/templates", params={"channel": "alipay"}).json()["data"]
    assert len(templates) == 1
    assert templates[0]["is_default"] is True

    abort = client.post(
        f"{PREFIX}/templates",
        json={"channel": "alipay", "name": "默认", "spec": mapping, "policy": "abort"},
    )
    assert abort.status_code == 409
    body = abort.json()
    assert body["code"] == "E2003"
    assert body["data"]["detail"]["can_overwrite"] is True

    overwrite = client.post(
        f"{PREFIX}/templates",
        json={"channel": "alipay", "name": "默认", "spec": mapping, "policy": "overwrite"},
    )
    assert overwrite.status_code == 200
    assert overwrite.json()["data"]["id"] == template_id, "覆盖复用同一条记录"
    defaults = [
        item
        for item in client.get(f"{PREFIX}/templates", params={"channel": "alipay"}).json()["data"]
        if item["is_default"]
    ]
    assert len(defaults) == 1, "同渠道默认模板至多一条"

    save_as = client.post(
        f"{PREFIX}/templates",
        json={"channel": "alipay", "name": "默认", "spec": mapping, "policy": "save_as"},
    )
    assert save_as.status_code == 200
    created = save_as.json()["data"]
    assert created["name"] == "默认(2)"
    assert created["is_default"] is False


def test_mapping_after_precheck_resets_counts(
    client: TestClient, upload, fixtures_dir: Path
) -> None:
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv")
    mapping = detected_mapping(client, batch["id"])
    client.put(f"{PREFIX}/batches/{batch['id']}/mapping", json=mapping)
    precheck = client.post(f"{PREFIX}/batches/{batch['id']}/precheck").json()["data"]
    assert precheck["summary"]["new"] == 669

    changed = dict(mapping)
    changed["direction_map"] = {}
    changed["amount_scale"] = 1
    client.put(f"{PREFIX}/batches/{batch['id']}/mapping", json=changed)

    detail = client.get(f"{PREFIX}/batches/{batch['id']}").json()["data"]
    assert detail["status"] == "mapped_pending", "映射变更后退回待映射（EX-22 前置防护）"
    assert detail["new_count"] == 0
    assert detail["mapping_snapshot"] is None, "旧快照必须作废，否则 C3 会按旧口径入库"
