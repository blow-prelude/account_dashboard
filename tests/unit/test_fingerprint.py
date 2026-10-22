"""去重指纹（U-FP-01 / U-FP-02，SDD §8.7 / EX-21）。

指纹是去重的唯一依据，所以这组用例既锁「同输入同输出」，也锁「改任一字段必不同」——
后者才真正决定「同日同额不同对方」不会被误判成重复。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from account_dashboard.infra.parsers.fingerprint import build_fingerprint, normalize_component
from account_dashboard.models.enums import Direction

BASE = dict(
    occurred_at=datetime(2026, 10, 21, 19, 48, 3),
    amount_cents=880,
    direction=Direction.EXPENSE,
    counterparty="某某便利店",
    item="扫码支付",
)


def test_same_inputs_same_fingerprint() -> None:
    assert build_fingerprint(**BASE) == build_fingerprint(**BASE)
    assert len(build_fingerprint(**BASE) or "") == 32


@pytest.mark.parametrize(
    "override",
    [
        {"occurred_at": datetime(2026, 10, 21, 19, 48, 4)},
        {"amount_cents": 881},
        {"direction": Direction.INCOME},
        {"counterparty": "美团平台商户"},
        {"item": "外卖订单"},
    ],
)
def test_any_field_change_changes_fingerprint(override: dict[str, object]) -> None:
    changed = {**BASE, **override}
    assert build_fingerprint(**changed) != build_fingerprint(**BASE)


def test_missing_time_or_amount_returns_none() -> None:
    assert build_fingerprint(**{**BASE, "occurred_at": None}) is None
    assert build_fingerprint(**{**BASE, "amount_cents": None}) is None


def test_same_day_same_amount_different_counterparty_differs() -> None:
    """FR-04 规则 3：同日同额不同对方是两笔真实消费，不能判重。"""
    left = build_fingerprint(**BASE)
    right = build_fingerprint(**{**BASE, "counterparty": "滴滴出行"})
    assert left != right


def test_none_and_empty_counterparty_are_equivalent() -> None:
    left = build_fingerprint(**{**BASE, "counterparty": None})
    right = build_fingerprint(**{**BASE, "counterparty": ""})
    assert left == right


def test_counterparty_mask_stripped() -> None:
    assert normalize_component("浪漫(**)店") == normalize_component("浪漫店")
    assert normalize_component("  某 某  ") == "某 某"


def test_case_and_width_normalized() -> None:
    assert normalize_component("STARBUCKS") == normalize_component("starbucks")
    assert normalize_component("（某某）") == normalize_component("(某某)")
