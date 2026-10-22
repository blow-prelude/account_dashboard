"""金额清洗（U-AM-01 / U-AM-02，FR-04 / I4）。

这一组用例的价值全在「差 1 分」上：``4.35 * 100`` 在 IEEE754 下是 434.99999999999994，
``int()`` 之后变 434。任何改动 ``parse_amount_to_cents`` 的人都必须先让这组用例保持绿色。
"""

from __future__ import annotations

import pytest

from account_dashboard.infra.parsers.cleaning import AmountParseError, parse_amount_to_cents


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (8.8, 880),
        (4.35, 435),
        (8.8 + 0.1, 890),  # 8.9 的浮点表示是 8.900000000000000355...，仍应得 890
        ("45.90", 4590),
        ("¥1,234.5", 123450),
        ("￥ 12.00 ", 1200),
        ("0.01", 1),
        ("8.80元", 880),
        (461, 46100),
        (0, 0),
        (-12.34, 1234),  # 金额取绝对值，方向由 direction 承载
        ("-45.90", 4590),
        ("8.800", 880),
    ],
)
def test_amount_to_cents(raw: object, expected: int) -> None:
    assert parse_amount_to_cents(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "/", "-", "—", "N/A", "abc", "12.3456", 10**10, True])
def test_amount_parse_error(raw: object) -> None:
    with pytest.raises(AmountParseError):
        parse_amount_to_cents(raw)


def test_amount_scale_100_means_raw_is_cents() -> None:
    """个别银行导出直接用「分」作单位：scale=100 时不再乘 100。"""
    assert parse_amount_to_cents("4590", scale=100) == 4590
    assert parse_amount_to_cents(4590, scale=100) == 4590


def test_float_never_used_for_multiplication() -> None:
    """把反例写死：如果有人退化成 ``int(v * 100)``，这条必红。"""
    assert int(4.35 * 100) == 434  # 错误做法的结果
    assert parse_amount_to_cents(4.35) == 435  # 正确做法的结果
