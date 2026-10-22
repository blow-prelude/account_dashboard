"""表头打分探测（SDD §8.3）。

两个反直觉点，都是踩过坑才写进来的：

1. **分母固定 15**（5 核心 × 2 + 5 次要 × 1）。若用「命中数 / 该行非空列数」，
   只有 5 列且恰好全中的行会拿满分，与 11 列全中并列，误选风险高。
2. **要求 5 核心全中**才算自动候选。前言里「交易时间：2026-06-01」这类文本可能
   虚构命中 1~2 个字段，要求全中可以把它们全部排除（EX-03 才走手动映射）。

同分时取**行号最小者**（先出现者胜）。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any

from account_dashboard.infra.errors import HeaderUnrecognizedError
from account_dashboard.infra.parsers.models import HeaderMatch

CORE_FIELDS: tuple[str, ...] = ("occurred_at", "amount", "direction", "counterparty", "item")
SECONDARY_FIELDS: tuple[str, ...] = (
    "txn_type",
    "payment_method",
    "platform_category",
    "platform_status",
    "note",
)
DENOMINATOR = len(CORE_FIELDS) * 2 + len(SECONDARY_FIELDS)  # 15，固定
DEFAULT_MAX_SCAN = 60

ALIASES: dict[str, tuple[str, ...]] = {
    "occurred_at": ("交易时间", "交易日期", "时间", "日期", "发生时间", "记账时间", "付款时间"),
    "amount": ("金额(元)", "金额（元）", "金额", "交易金额", "发生金额", "amount"),
    "direction": ("收/支", "收支", "收／支", "收入/支出", "借贷标志", "收支类型"),
    "counterparty": ("交易对方", "对方", "商户名称", "交易商户", "商家", "收/付款方"),
    "item": ("商品", "商品说明", "商品名称", "摘要", "交易摘要", "说明", "用途"),
    "txn_type": ("交易类型", "业务类型", "交易方式"),
    "payment_method": ("支付方式", "收/付款方式", "付款方式", "收付款方式"),
    # 注意：「交易分类」在 SDD 的 txn_type 与 platform_category 两个别名表里都出现过，
    # 这里**只归给 platform_category** —— 支付宝的「交易分类」就是平台分类，
    # 而微信用的是「交易类型」。若两处都保留，字典后写者覆盖前者，行为将取决于书写顺序。
    "platform_category": ("交易分类", "分类", "账单分类"),
    "platform_status": ("当前状态", "交易状态", "状态"),
    "note": ("备注", "交易备注", "附言"),
}

_ZERO_WIDTH = dict.fromkeys(map(ord, "\ufeff\u200b\u200c\u200d\u2060"), None)
_SPACE_RE = re.compile(r"\s+")


def normalize_header_cell(value: Any) -> str:
    """str → NFKC（全角转半角）→ 去 BOM/零宽/Tab/换行 → 折叠空白 → 去尾冒号 → lower。"""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).translate(_ZERO_WIDTH)
    text = _SPACE_RE.sub(" ", text).strip()
    if text.endswith(":"):
        text = text[:-1].strip()
    return text.casefold()


def _build_alias_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for field_name, aliases in ALIASES.items():
        for alias in aliases:
            index.setdefault(normalize_header_cell(alias), field_name)
    return index


_ALIAS_INDEX = _build_alias_index()


def match_field(cell: Any) -> str | None:
    """单列 → 标准字段名；未命中返回 ``None``。"""
    return _ALIAS_INDEX.get(normalize_header_cell(cell))


def score_headers(
    rows: Iterable[Sequence[Any]],
    max_scan: int = DEFAULT_MAX_SCAN,
    *,
    meta: dict[str, Any] | None = None,
) -> list[HeaderMatch]:
    """对前 ``max_scan`` 行逐行打分，返回按「分数降序 → 命中多 → 行号小」排序的候选。"""
    matches: list[HeaderMatch] = []
    for row_index, cells in enumerate(rows):
        if row_index >= max_scan:
            break
        mapping: dict[str, int] = {}
        core = 0
        secondary = 0
        for column, cell in enumerate(cells):
            field_name = match_field(cell)
            if field_name is None or field_name in mapping:
                continue
            mapping[field_name] = column
            if field_name in CORE_FIELDS:
                core += 1
            elif field_name in SECONDARY_FIELDS:
                secondary += 1
        if core == 0 and secondary == 0:
            continue
        matches.append(
            HeaderMatch(
                row_index=row_index,
                mapping=mapping,
                score=(core * 2 + secondary) / DENOMINATOR,
                matched_core=core,
                columns=tuple(str(cell).strip() for cell in cells),
                meta=dict(meta or {}),
            )
        )

    matches.sort(key=lambda item: (-item.score, -len(item.mapping), item.row_index))
    return matches


def select_header(
    matches: Sequence[HeaderMatch],
    *,
    allow_partial: bool = False,
) -> HeaderMatch:
    """挑最佳候选；无 5 核心全中者则按 ``allow_partial`` 决定是否降级返回。"""
    complete = [item for item in matches if item.matched_core == len(CORE_FIELDS)]
    if complete:
        return complete[0]
    usable = [item for item in matches if item.matched_core > 0]
    if allow_partial and usable:
        return usable[0]
    if not matches:
        raise HeaderUnrecognizedError("没有找到表头，请手动指定各列含义")
    missing = _missing_core(matches[0])
    raise HeaderUnrecognizedError(
        "没有找到完整的表头（缺少：" + "、".join(missing) + "），请手动指定各列含义",
        detail={"missing_core": missing, "best_row": matches[0].row_index},
    )


def detect_header(
    rows: Iterable[Sequence[Any]],
    *,
    max_scan: int = DEFAULT_MAX_SCAN,
    allow_partial: bool = False,
    meta: dict[str, Any] | None = None,
) -> HeaderMatch:
    """``score_headers`` + ``select_header`` 的组合入口。"""
    return select_header(
        score_headers(rows, max_scan=max_scan, meta=meta), allow_partial=allow_partial
    )


FIELD_LABELS = {
    "occurred_at": "交易时间",
    "amount": "金额",
    "direction": "收/支",
    "counterparty": "交易对方",
    "item": "商品说明",
}


def _missing_core(match: HeaderMatch) -> list[str]:
    return [FIELD_LABELS[name] for name in CORE_FIELDS if name not in match.mapping]
