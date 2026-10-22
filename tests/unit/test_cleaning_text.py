"""文本清洗与方向判定（U-DM-01，SDD §8.5 / §8.6）。

方向判定有一个顺序陷阱：``clean_text`` 把 ``/`` 当空值，但微信「收/支」列的 ``/``
是 **neutral 的合法表示**（样例实测 4 行）。因此必须先查映射表、再回退到通用清洗。
"""

from __future__ import annotations

import pytest

from account_dashboard.infra.parsers.cleaning import clean_text, parse_direction
from account_dashboard.models.enums import Channel, Direction, IssueCode


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  美团平台商户 ", "美团平台商户"),
        ("金额（元）", "金额(元)"),
        ("\ufeff交易时间", "交易时间"),
        ("备注：", "备注"),
        ("a\tb\nc", "a b c"),
        ("零钱\u3000通", "零钱 通"),
        (461, "461"),
        (8.0, "8"),
        (8.8, "8.8"),
        ("", None),
        ("/", None),
        ("-", None),
        ("N/A", None),
        (None, None),
    ],
)
def test_clean_text(raw: object, expected: str | None) -> None:
    assert clean_text(raw) == expected


def test_clean_text_keeps_slash_when_markers_disabled() -> None:
    assert clean_text("/", empty_markers=("",)) == "/"


@pytest.mark.parametrize(
    ("raw", "channel", "expected"),
    [
        ("支出", Channel.WECHAT, Direction.EXPENSE),
        ("收入", Channel.WECHAT, Direction.INCOME),
        ("/", Channel.WECHAT, Direction.NEUTRAL),
        ("支出", Channel.ALIPAY, Direction.EXPENSE),
        ("收入", Channel.ALIPAY, Direction.INCOME),
        ("不计收支", Channel.ALIPAY, Direction.NEUTRAL),
    ],
)
def test_direction_mapping(raw: str, channel: Channel, expected: Direction) -> None:
    direction, issue = parse_direction(raw, channel)
    assert direction is expected
    assert issue is None


def test_wechat_slash_is_neutral_not_unknown() -> None:
    direction, issue = parse_direction("/", Channel.WECHAT)
    assert direction is Direction.NEUTRAL
    assert issue is None, "微信的 / 是合法 neutral，不该被当成未知值"


def test_unknown_direction_falls_back_to_neutral_with_issue() -> None:
    direction, issue = parse_direction("待定", Channel.WECHAT)
    assert direction is Direction.NEUTRAL
    assert issue is IssueCode.DIRECTION_UNKNOWN


def test_empty_direction_records_issue() -> None:
    direction, issue = parse_direction(None, Channel.ALIPAY)
    assert direction is Direction.NEUTRAL
    assert issue is IssueCode.DIRECTION_UNKNOWN


def test_direction_inference_from_hint() -> None:
    """原始方向缺失时，用交易类型/商品关键词兜底（绝不覆盖渠道给出的值）。"""
    direction, issue = parse_direction(None, Channel.WECHAT, hint_text="零钱通转入")
    assert direction is Direction.NEUTRAL
    assert issue is None

    direction, issue = parse_direction("", Channel.OTHER, hint_text="奖学金")
    assert direction is Direction.INCOME


def test_template_direction_map_wins() -> None:
    direction, issue = parse_direction(
        "其他收入", Channel.OTHER, extra_map={"其他收入": Direction.INCOME}
    )
    assert direction is Direction.INCOME
    assert issue is None
