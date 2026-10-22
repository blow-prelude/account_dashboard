"""表头探测（U-HD-01 ~ U-HD-04，SDD §8.3）。

两个反直觉点必须被用例锁住：分母固定 15、要求 5 核心全中。否则「只有 5 列且全中」
的行会拿到 1.0 分，与 11 列全中的真表头并列，误选就变成偶发故障。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from account_dashboard.infra.errors import HeaderUnrecognizedError
from account_dashboard.infra.parsers.encoding import decode_file
from account_dashboard.infra.parsers.header_detect import (
    CORE_FIELDS,
    DENOMINATOR,
    normalize_header_cell,
    score_headers,
    select_header,
)
from account_dashboard.infra.parsers.registry import ParserRegistry

WECHAT_COLUMNS = [
    "交易时间",
    "交易类型",
    "交易对方",
    "商品",
    "收/支",
    "金额(元)",
    "支付方式",
    "当前状态",
    "交易单号",
    "商户单号",
    "备注",
]
ALIPAY_COLUMNS = [
    "交易时间",
    "交易分类",
    "交易对方",
    "对方账号",
    "商品说明",
    "收/支",
    "金额",
    "收/付款方式",
    "交易状态",
    "交易订单号",
    "商家订单号",
    "备注",
    "",
]


def test_header_row_wechat(fixtures_dir: Path) -> None:
    result = ParserRegistry().parse(fixtures_dir / "wechat_sample_sanitized.xlsx")
    assert result.header.row_index == 17  # 0-based；1-based 是第 18 行
    assert result.header.matched_core == 5
    assert result.meta["preamble_rows"] == 17
    assert len(result.header.columns) == 11


def test_header_row_alipay(fixtures_dir: Path) -> None:
    result = ParserRegistry().parse(fixtures_dir / "alipay_sample_gb18030.csv")
    assert result.header.row_index == 23
    assert result.header.matched_core == 5
    assert len(result.header.columns) == 13
    assert result.header.columns[-1] == "", "末列为空也要保留物理索引"


def test_header_row_shifted(fixtures_dir: Path) -> None:
    """U-HD-04：前言整体下移 5 行，仍能定位（不能按固定行号取表头）。"""
    result = ParserRegistry().parse(fixtures_dir / "wechat_header_shifted.xlsx")
    assert result.header.row_index == 22
    assert result.total_rows == 689


def test_no_header_raises(fixtures_dir: Path) -> None:
    with pytest.raises(HeaderUnrecognizedError) as excinfo:
        ParserRegistry().parse(fixtures_dir / "no_header.csv")
    assert excinfo.value.code == "E1003"


def test_no_header_allows_partial_candidate(fixtures_dir: Path) -> None:
    """U-HD-03：allow_partial 时返回最佳候选，供手动映射使用（EX-03）。"""
    result = ParserRegistry().parse(fixtures_dir / "no_header.csv", allow_partial=True)
    assert result.header.row_index == 2
    assert result.header.matched_core == 2  # 日期 → 交易时间、摘要 → 商品说明
    assert result.mapping.missing_core(), "只命中两个核心字段，必然缺映射"


def test_fixed_denominator_beats_short_row() -> None:
    """5 列全中的短行只能拿 10/15；11 列全中的真表头拿 14/15，不会被并列。"""
    short = ["交易时间", "金额", "收/支", "交易对方", "商品"]
    matches = score_headers([short, WECHAT_COLUMNS])
    assert matches[0].columns == tuple(WECHAT_COLUMNS)
    assert matches[0].score == pytest.approx((5 * 2 + 4) / DENOMINATOR)
    assert matches[1].score == pytest.approx((5 * 2 + 0) / DENOMINATOR)
    assert matches[0].score > matches[1].score


def test_preamble_with_fake_fields_is_filtered() -> None:
    """前言里的「交易时间」字样会命中 1 个核心字段，但因不足 5 个而不会被选中。"""
    rows = [
        ["交易时间", "2026-06-01 至 2026-10-21"],
        [],
        WECHAT_COLUMNS,
    ]
    matches = score_headers(rows)
    assert [item.row_index for item in matches] == [2, 0], "按分数降序：真表头在前"
    chosen = select_header(matches)
    assert chosen.row_index == 2


def test_defaults_to_first_when_tied() -> None:
    first = WECHAT_COLUMNS
    second = list(WECHAT_COLUMNS)
    chosen = select_header(score_headers([first, second]))
    assert chosen.row_index == 0, "同分取行号最小者"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("金额（元）", "金额(元)"),
        ("  收/支 ", "收/支"),
        ("\ufeff交易时间", "交易时间"),
        ("备注:", "备注"),
        ("Amount", "amount"),
        (None, ""),
    ],
)
def test_normalize_header_cell(raw: object, expected: str) -> None:
    assert normalize_header_cell(raw) == expected


def test_core_fields_are_five() -> None:
    assert set(CORE_FIELDS) == {"occurred_at", "amount", "direction", "counterparty", "item"}


def test_utf8_and_gb18030_decode_identically(fixtures_dir: Path) -> None:
    """U-EN-01：同内容两种编码，解析结果逐行一致。"""
    gb_text, gb_encoding = decode_file(fixtures_dir / "alipay_sample_gb18030.csv")
    utf_text, utf_encoding = decode_file(fixtures_dir / "alipay_sample_utf8.csv")
    assert gb_encoding == "gb18030"
    assert utf_encoding == "utf-8"
    assert gb_text == utf_text

    registry = ParserRegistry()
    gb_rows = registry.parse(fixtures_dir / "alipay_sample_gb18030.csv").rows
    utf_rows = registry.parse(fixtures_dir / "alipay_sample_utf8.csv").rows
    assert [row.payload for row in gb_rows] == [row.payload for row in utf_rows]
