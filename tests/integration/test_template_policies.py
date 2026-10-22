"""C2B.4 模板三策略（EX-20）：abort 409 / overwrite 降级 / save_as 加后缀。

关键不变量：**同一渠道 ``is_default=1`` 至多一条**（``uq_template_default`` 部分唯一索引）。
"先降级后插入"必须在同一事务内，本用例通过在``overwrite``后立即校验 default 数量来锁住。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from tests.integration.conftest import StagingFlow

from account_dashboard.errors import ErrorCode

SPEC: dict[str, Any] = {
    "occurred_at": 0,
    "amount": 1,
    "direction": 2,
    "counterparty": 3,
    "item": 4,
    "amount_scale": 1,
}


def post_template(
    api: TestClient,
    *,
    name: str = "微信默认",
    channel: str = "wechat",
    policy: str = "abort",
    spec: dict[str, Any] | None = None,
):
    return api.post(
        "/api/v1/staging/templates",
        json={"channel": channel, "name": name, "spec": spec or SPEC, "policy": policy},
    )


def defaults_of(api: TestClient, channel: str = "wechat") -> list[dict[str, Any]]:
    items = api.get(f"/api/v1/staging/templates?channel={channel}").json()["data"]
    return [item for item in items if item["is_default"]]


def test_first_template_becomes_default(api: TestClient) -> None:
    response = post_template(api)

    assert response.status_code == 200
    assert response.json()["data"]["is_default"] is True


def test_abort_conflicts_with_existing_default(api: TestClient) -> None:
    post_template(api)

    response = post_template(api, name="第二个")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == ErrorCode.DUPLICATE_TEMPLATE.value
    assert "默认模板" in body["message"]
    assert len(defaults_of(api)) == 1, "abort 不得写入任何记录"


def test_overwrite_demotes_old_default(api: TestClient) -> None:
    post_template(api, name="旧模板")
    new_spec = dict(SPEC, amount_scale=100)

    response = post_template(api, name="新模板", policy="overwrite", spec=new_spec)

    assert response.status_code == 200
    created = response.json()["data"]
    assert created["is_default"] is True
    assert created["spec"]["amount_scale"] == 100

    defaults = defaults_of(api)
    assert len(defaults) == 1
    assert defaults[0]["name"] == "新模板"

    all_items = api.get("/api/v1/staging/templates?channel=wechat").json()["data"]
    old = next(item for item in all_items if item["name"] == "旧模板")
    assert old["is_default"] is False, "旧模板保留但降级为普通模板"


def test_overwrite_keeps_single_default_even_repeated(api: TestClient) -> None:
    post_template(api)
    for index in range(3):
        post_template(api, name=f"覆盖{index}", policy="overwrite")

    items = api.get("/api/v1/staging/templates?channel=wechat").json()["data"]
    assert len(defaults_of(api)) == 1
    assert len(items) == 4, "旧 default 全部保留（可另存/追溯）"


def test_save_as_appends_suffix_on_duplicate_name(api: TestClient) -> None:
    post_template(api, name="同名")

    response = post_template(api, name="同名", policy="save_as")

    assert response.status_code == 200
    created = response.json()["data"]
    assert created["name"] == "同名 (2)"
    assert created["is_default"] is False, "save_as 永远不抢默认"


def test_templates_are_scoped_by_channel(api: TestClient) -> None:
    post_template(api, channel="wechat", name="微信")
    post_template(api, channel="alipay", name="微信")  # 同名不同渠道：允许

    wechat = api.get("/api/v1/staging/templates?channel=wechat").json()["data"]
    alipay = api.get("/api/v1/staging/templates?channel=alipay").json()["data"]
    everything = api.get("/api/v1/staging/templates").json()["data"]

    assert [item["channel"] for item in wechat] == ["wechat"]
    assert [item["channel"] for item in alipay] == ["alipay"]
    assert len(everything) == 2


def test_template_name_must_not_be_blank(api: TestClient) -> None:
    response = post_template(api, name="   ")

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.INVALID_ENUM_VALUE.value


def test_invalid_policy_is_rejected(api: TestClient) -> None:
    response = post_template(api, policy="whatever")

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.INVALID_ENUM_VALUE.value


def test_default_template_is_used_for_replay(api: TestClient, parser, flow: StagingFlow) -> None:
    """模板存下来的 spec 会在下次解析时作为 ``MappingSpec`` 重放（K6）。"""
    post_template(api, channel="other", policy="overwrite")
    flow.upload_ok()

    assert parser.last_spec is not None
    assert parser.last_spec.amount == 1
