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


def test_misaligned_spec_raises_issue_counts(
    client: TestClient, upload, tmp_path: Path
) -> None:
    """M5 第 ⑤ 步：故意错位的 spec 必须让 issue 显著上升。

    没有这一步，「映射生效」只是口头承诺 —— 合稿文档点名这是最容易漏测的一条。
    判据不是"能不能保存"，而是**同一份文件换个 spec，行级 issue 从 0 变成全量**：
    只有 spec 真的被喂进解析内核，才可能出现这种差异。
    """
    target = tmp_path / "bank_five_cols.csv"
    target.write_text(
        "交易时间,交易对方,商品,收/支,金额\n"
        "2026-10-01 10:00:00,某便利店,矿泉水,支出,12.30\n"
        "2026-10-01 10:00:02,某便利店,面包,支出,8.00\n"
        "2026-10-01 10:00:03,某便利店,牛奶,支出,5.50\n",
        encoding="utf-8",
    )
    batch = upload(target)
    batch_id = batch["id"]
    good = detected_mapping(client, batch_id)

    client.put(f"{PREFIX}/batches/{batch_id}/mapping", json=good)
    baseline = client.post(f"{PREFIX}/batches/{batch_id}/precheck").json()["data"]
    assert baseline["summary"] == {"total": 3, "new": 3, "dup": 0, "pending_manual": 0}
    assert baseline["issues"] == {}, "正确 spec 下三行都不该有解析问题"

    # 错位：时间列指到「商品」、金额列指到「交易对方」—— 三行全部解析不出来
    wrong = dict(good)
    wrong["occurred_at"] = good["item"]
    wrong["amount"] = good["counterparty"]
    assert wrong != good

    response = client.put(f"{PREFIX}/batches/{batch_id}/mapping", json=wrong)
    assert response.status_code == 200, response.text

    after = client.post(f"{PREFIX}/batches/{batch_id}/precheck").json()["data"]
    issues = after["issues"]
    assert issues.get("TIME_PARSE") == 3, f"错位 spec 应让三行时间全失败：{issues}"
    assert issues.get("AMOUNT_PARSE") == 3, f"错位 spec 应让三行金额全失败：{issues}"
    assert after["summary"]["new"] == 0
    assert after["summary"]["pending_manual"] == 3, "解析不出的行归入待人工，不算 new"

    # 改回正确 spec 必须能恢复 —— 证明右移不是"保存了就回不去"
    client.put(f"{PREFIX}/batches/{batch_id}/mapping", json=good)
    restored = client.post(f"{PREFIX}/batches/{batch_id}/precheck").json()["data"]
    assert restored["issues"] == {}
    assert restored["summary"] == {"total": 3, "new": 3, "dup": 0, "pending_manual": 0}
