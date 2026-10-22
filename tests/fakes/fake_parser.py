"""B 线自维护的假解析器（C2-B §2）。

存在的意义：A 线（解析内核）可能还没合稿，但 B 线的 15 个端点必须能独立开发与验收。
注入点只有一处 —— ``ParserRegistry``：合稿时把 ``api/deps.get_parser_registry`` 换成
``default_registry()``，业务代码零改动（合稿 M2）。

合稿后本文件**保留**：C3 的故障注入（编码失败/表头失败/空文件/超行数）还要用它，
因为用真实样例去构造这些失败态成本太高。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from account_dashboard.infra.parsers.base import ParserAdapter
from account_dashboard.infra.parsers.errors import (
    EmptyDocument,
    EncodingDetectFailed,
    HeaderNotRecognized,
    ParseError,
    RowLimitExceeded,
)
from account_dashboard.models.internal import (
    Channel,
    Direction,
    MappingSpec,
    ParsedRow,
    ParseMeta,
    ParseResult,
)


def compute_fp(
    channel: str,
    occurred_at: str | None,
    amount_cents: int | None,
    direction: str,
    counterparty: str | None,
) -> str | None:
    """复刻 A 线的指纹规则（缺时间或金额 → ``None``），让预检用例有确定行为。"""
    if occurred_at is None or amount_cents is None:
        return None
    normalized = (counterparty or "").replace("(*)", "").strip().lower()
    raw = f"{channel}|{occurred_at}|{amount_cents}|{direction}|{normalized}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


_UNSET: Any = object()


def make_row(
    row_no: int = 1,
    *,
    occurred_at: Any = _UNSET,
    amount_cents: Any = _UNSET,
    direction: Direction = "expense",
    counterparty: Any = _UNSET,
    item: str | None = "测试商品",
    channel: Channel = "other",
    raw_payload: dict[str, Any] | None = None,
) -> ParsedRow:
    """默认值随 ``row_no`` 变化，保证不同行的指纹天然不同（否则预检全是 dup）。

    需要构造"不可解析行"时显式传 ``occurred_at=None`` / ``amount_cents=None``。
    """
    resolved_at = f"2026-06-01T10:{row_no % 60:02d}:00" if occurred_at is _UNSET else occurred_at
    resolved_amount = 1000 + row_no if amount_cents is _UNSET else amount_cents
    resolved_counterparty = f"测试商户{row_no:04d}" if counterparty is _UNSET else counterparty

    payload = (
        raw_payload
        if raw_payload is not None
        else {
            "交易时间": resolved_at or "",
            "金额": "" if resolved_amount is None else f"{resolved_amount / 100:.2f}",
            "收/支": direction,
        }
    )
    return ParsedRow(
        row_no=row_no,
        occurred_at=resolved_at,
        amount_cents=resolved_amount,
        direction=direction,
        counterparty=resolved_counterparty,
        item=item,
        txn_type="商户消费",
        payment_method="零钱",
        platform_category="餐饮美食",
        platform_status="支付成功",
        channel=channel,
        fp=compute_fp(channel, resolved_at, resolved_amount, direction, resolved_counterparty),
        raw_payload=payload,
    )


def make_rows(count: int, *, start: int = 1, channel: Channel = "other") -> list[ParsedRow]:
    """生成 ``count`` 行互不相同的合法行（指纹唯一，便于断言 new 计数）。"""
    return [
        make_row(
            index,
            occurred_at=f"2026-06-{(index % 28) + 1:02d}T09:{(index % 60):02d}:00",
            amount_cents=100 + index,
            counterparty=f"商户{index:04d}",
            channel=channel,
        )
        for index in range(start, start + count)
    ]


class FakeParser:
    """``ParserAdapter`` 的最小实现：``parse`` 返回预置行，或抛出预置异常。"""

    name = "fake"
    extensions = (".csv", ".xlsx")

    def __init__(
        self,
        rows: list[ParsedRow] | None = None,
        *,
        error: ParseError | None = None,
        encoding: str = "fake",
        adapter: str = "fake",
        columns: int = 3,
        header_row_no: int = 0,
        meta: ParseMeta | None = None,
        channel: Channel = "other",
    ) -> None:
        self._rows = list(rows or [])
        self._error = error
        self._encoding = encoding
        self._adapter = adapter
        self._columns = columns
        self._header_row_no = header_row_no
        self._meta = meta or ParseMeta()
        self.channel = channel
        self.parse_calls: list[str] = []
        self.last_spec: MappingSpec | None = None

    # 用例可在运行中翻转失败态（验证"失败批次重试成功"）
    @property
    def error(self) -> ParseError | None:
        return self._error

    @error.setter
    def error(self, value: ParseError | None) -> None:
        self._error = value

    def sniff(self, path: Path) -> bool:  # noqa: ARG002 - 协议要求
        return True

    def parse(self, path: Path, spec: MappingSpec | None = None) -> ParseResult:
        self.parse_calls.append(path.name)
        self.last_spec = spec
        if self._error is not None:
            raise self._error
        return ParseResult(
            rows=list(self._rows),
            header_row_no=self._header_row_no,
            encoding=self._encoding,
            adapter=self._adapter,
            columns=self._columns,
            meta=self._meta,
        )


def fake_encoding_error() -> FakeParser:
    return FakeParser(error=EncodingDetectFailed("无法识别文件编码"))


def fake_header_error() -> FakeParser:
    return FakeParser(error=HeaderNotRecognized("没有找到表头行"))


def fake_empty_document() -> FakeParser:
    return FakeParser(error=EmptyDocument("文件里没有数据行"))


def fake_row_limit_error() -> FakeParser:
    return FakeParser(error=RowLimitExceeded("行数超过上限"))


assert isinstance(FakeParser(), ParserAdapter), "FakeParser 必须满足 ParserAdapter 协议"


__all__ = [
    "FakeParser",
    "compute_fp",
    "fake_empty_document",
    "fake_encoding_error",
    "fake_header_error",
    "fake_row_limit_error",
    "make_row",
    "make_rows",
]
