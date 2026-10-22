"""C2B.5 强制新增：``dup → new`` 翻转、留痕、幂等、可撤销。

幂等键是 ``override_mark`` 的主键 ``(batch_id, row_no)``：重复 POST 只更新原因，
不新增行。撤销走 DELETE，不存在时返回 ``{"removed": false}`` 而不是 404。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.fakes.fake_parser import make_row
from tests.integration.conftest import StagingFlow, insert_transaction

from account_dashboard.errors import ErrorCode


def prepare_dup(api: TestClient, db, parser, flow: StagingFlow) -> str:
    """造一个"第 1 行已入库"的批次，返回 batch_id。"""
    insert_transaction(db, fp=make_row(1).fp)
    parser._rows = [make_row(1), make_row(2)]  # noqa: SLF001
    batch = flow.ready_batch()
    assert flow.precheck(batch["id"]).status_code == 200
    return batch["id"]


def test_override_flips_dup_to_new(api: TestClient, db, parser, flow: StagingFlow) -> None:
    batch_id = prepare_dup(api, db, parser, flow)

    response = api.post(
        f"/api/v1/staging/batches/{batch_id}/overrides",
        json={"row_no": 1, "reason": "确实第二笔，重复扣款"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["reason"] == "确实第二笔，重复扣款"

    payload = flow.precheck(batch_id).json()["data"]
    row = next(item for item in payload["rows"] if item["row_no"] == 1)
    assert row["label"] == "new"
    assert row["override"] is True
    assert payload["summary"]["new"] == 2
    assert payload["summary"]["dup"] == 0


def test_override_is_idempotent(api: TestClient, db, parser, flow: StagingFlow) -> None:
    batch_id = prepare_dup(api, db, parser, flow)

    for reason in ("第一次", "第二次"):
        api.post(
            f"/api/v1/staging/batches/{batch_id}/overrides",
            json={"row_no": 1, "reason": reason},
        )

    rows = db.query_all("SELECT * FROM override_mark WHERE batch_id = ?", (batch_id,))
    assert len(rows) == 1, "同一 (batch_id, row_no) 只能有一行"
    assert rows[0]["reason"] == "第二次", "重复标记应更新原因"


def test_revoke_restores_dup(api: TestClient, db, parser, flow: StagingFlow) -> None:
    batch_id = prepare_dup(api, db, parser, flow)
    api.post(f"/api/v1/staging/batches/{batch_id}/overrides", json={"row_no": 1, "reason": "x"})

    response = api.delete(f"/api/v1/staging/batches/{batch_id}/overrides/1")

    assert response.status_code == 200
    assert response.json()["data"]["removed"] is True
    payload = flow.precheck(batch_id).json()["data"]
    row = next(item for item in payload["rows"] if item["row_no"] == 1)
    assert row["label"] == "dup"
    assert row["override"] is False


def test_revoke_missing_override_is_idempotent(api: TestClient, flow: StagingFlow) -> None:
    batch = flow.ready_batch()

    response = api.delete(f"/api/v1/staging/batches/{batch['id']}/overrides/3")

    assert response.status_code == 200
    assert response.json()["data"]["removed"] is False


def test_override_requires_prechecked_state(api: TestClient, flow: StagingFlow) -> None:
    batch = flow.upload_ok()  # mapped_pending

    response = api.post(
        f"/api/v1/staging/batches/{batch['id']}/overrides",
        json={"row_no": 1, "reason": "提前标记"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == ErrorCode.BATCH_STATE_CONFLICT.value


def test_blank_reason_is_rejected(api: TestClient, flow: StagingFlow) -> None:
    batch = flow.ready_batch()

    response = api.post(
        f"/api/v1/staging/batches/{batch['id']}/overrides",
        json={"row_no": 1, "reason": "   "},
    )

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.INVALID_ENUM_VALUE.value


def test_override_does_not_flip_pending_manual(api: TestClient, parser, flow: StagingFlow) -> None:
    """待人工核对的行本来就不能入库，强制新增翻它没有意义（C2-B §4.6）。"""
    parser._rows = [make_row(1, occurred_at=None)]  # noqa: SLF001
    batch = flow.ready_batch()
    flow.precheck(batch["id"])

    api.post(
        f"/api/v1/staging/batches/{batch['id']}/overrides",
        json={"row_no": 1, "reason": "强行新增"},
    )

    payload = flow.precheck(batch["id"]).json()["data"]
    assert payload["rows"][0]["label"] == "pending_manual"
    assert payload["rows"][0]["override"] is True
