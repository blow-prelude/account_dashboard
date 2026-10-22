"""C2B.4 映射校验（裁决 D-2 硬三软二）。

四类断言：缺必需列 → ``E1007``；缺对方/商品 → 200 + warning；索引越界 → ``E1008``；
``amount_scale`` 越界 → ``E1008``。外加"保存映射后状态即 prechecked"（D-1）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.integration.conftest import StagingFlow

from account_dashboard.errors import ErrorCode


def test_missing_required_field_blocks(flow: StagingFlow) -> None:
    batch = flow.upload_ok()

    response = flow.mapping(batch["id"], amount=-1)

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == ErrorCode.MAPPING_INCOMPLETE.value
    assert "金额" in body["message"]
    assert body["data"]["detail"]["missing"] == ["amount"]
    assert flow.detail(batch["id"])["status"] == "mapped_pending", "校验失败不得改状态"


def test_all_required_fields_missing_are_listed(flow: StagingFlow) -> None:
    batch = flow.upload_ok()

    response = flow.mapping(
        batch["id"], occurred_at=-1, amount=-1, direction=-1, counterparty=None, item=None
    )

    assert response.status_code == 400
    detail = response.json()["data"]["detail"]
    assert set(detail["missing"]) == {"occurred_at", "amount", "direction"}
    message = response.json()["message"]
    for label in ("交易时间", "金额", "收/支方向"):
        assert label in message


def test_soft_fields_only_warn(flow: StagingFlow) -> None:
    batch = flow.upload_ok()

    response = flow.mapping(batch["id"], counterparty=None, item=None)

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["warnings"]) == 2
    assert any("交易对方" in item for item in data["warnings"])
    assert data["batch"]["status"] == "prechecked"


def test_index_out_of_range_rejected(flow: StagingFlow) -> None:
    batch = flow.upload_ok()  # FakeParser 声明 columns=3

    response = flow.mapping(batch["id"], occurred_at=9)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == ErrorCode.INVALID_ENUM_VALUE.value
    assert "只有 3 列" in body["message"]


def test_negative_index_below_minus_one_rejected(flow: StagingFlow) -> None:
    batch = flow.upload_ok()

    response = flow.mapping(batch["id"], item=-5)

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.INVALID_ENUM_VALUE.value


def test_amount_scale_must_be_one_or_hundred(flow: StagingFlow) -> None:
    batch = flow.upload_ok()

    response = flow.mapping(batch["id"], amount_scale=7)

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.INVALID_ENUM_VALUE.value


def test_direction_map_value_must_be_enum(flow: StagingFlow) -> None:
    batch = flow.upload_ok()

    response = flow.mapping(batch["id"], direction_map={"支出": "out"})

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.INVALID_ENUM_VALUE.value


def test_mapping_is_persisted_verbatim(flow: StagingFlow) -> None:
    batch = flow.upload_ok()
    flow.mapping(batch["id"], amount_scale=100, direction_map={"支出": "expense"})

    stored = flow.detail(batch["id"])["mapped_fields"]

    assert stored["amount_scale"] == 100
    assert stored["direction_map"] == {"支出": "expense"}
    assert stored["counterparty"] == 0


def test_mapping_can_be_saved_again_on_prechecked(api: TestClient, flow: StagingFlow) -> None:
    batch = flow.ready_batch()

    response = flow.mapping(batch["id"], item=1)

    assert response.status_code == 200
    assert response.json()["data"]["batch"]["status"] == "prechecked"


def test_save_template_flag_creates_default(api: TestClient, flow: StagingFlow) -> None:
    batch = flow.upload_ok()

    response = flow.mapping(batch["id"], save_template=True)

    assert response.status_code == 200
    template = response.json()["data"]["template"]
    assert template is not None
    assert template["is_default"] is True

    listing = api.get("/api/v1/staging/templates").json()["data"]
    assert len(listing) == 1
    assert listing[0]["spec"]["amount_scale"] == 1
