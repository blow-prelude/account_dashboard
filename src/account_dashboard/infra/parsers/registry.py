"""解析器注册表：适配器选择 + 「一次解析」的完整流程（SDD §4.5.2 / §7.2）。

``parse()`` 是解析链路的唯一入口 —— 上传自动解析、重试解析、预览、预检、C3 重放
全部走它，保证「同一份文件同一个映射 → 同一批 ParsedRow」，这是 I11（可重放）的基础。

本模块**不碰数据库**：它只把文件变成 ``ParsedRow`` 列表。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from account_dashboard.infra.parsers.alipay_csv import AlipayCsvAdapter
from account_dashboard.infra.parsers.base import BaseAdapter, RowSource, dumps_payload
from account_dashboard.infra.parsers.encoding import decode_file, is_xlsx
from account_dashboard.infra.parsers.generic import GenericAdapter
from account_dashboard.infra.parsers.models import HeaderMatch, ParsedRow, ParseStats
from account_dashboard.infra.parsers.wechat_xlsx import WechatXlsxAdapter
from account_dashboard.models.enums import Channel
from account_dashboard.models.internal import MappingSpec

SNIFF_MIN_SCORE = 0.5
HEAD_PROBE_BYTES = 8192


@dataclass(frozen=True, slots=True)
class ParseFileResult:
    """一次解析的全部产出（含 meta，供 ``staging_batch.parse_meta`` 落库）。"""

    adapter: str
    channel: Channel
    encoding: str
    header: HeaderMatch
    mapping: MappingSpec
    rows: list[ParsedRow]
    stats: ParseStats
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def total_rows(self) -> int:
        return len(self.rows)

    def rows_payload(self) -> list[dict[str, Any]]:
        """给 C3 用的最小形态（避免把 dataclass 直接塞进 JSON）。"""
        return [
            {
                "row_no": row.row_no,
                "occurred_at": row.occurred_at_iso,
                "amount_cents": row.amount_cents,
                "direction": str(row.direction) if row.direction else None,
                "fingerprint": row.fingerprint,
                "payload": dumps_payload(row.payload),
            }
            for row in self.rows
        ]


class ParserRegistry:
    def __init__(self, adapters: list[BaseAdapter] | None = None) -> None:
        self._adapters: list[BaseAdapter] = adapters or [
            WechatXlsxAdapter(),
            AlipayCsvAdapter(),
            GenericAdapter(),
        ]
        self._generic = next(
            (adapter for adapter in self._adapters if isinstance(adapter, GenericAdapter)),
            GenericAdapter(),
        )

    @property
    def adapters(self) -> list[BaseAdapter]:
        return list(self._adapters)

    def get(self, name: str) -> BaseAdapter:
        for adapter in self._adapters:
            if adapter.name == name:
                return adapter
        return self._generic

    def select(self, path: Path, channel_hint: Channel | None = None) -> BaseAdapter:
        """① 渠道提示命中 → 直接用；② sniff 打分取最高（≥0.5）；③ 否则兜底 generic。"""
        if channel_hint and channel_hint != Channel.OTHER:
            for adapter in self._adapters:
                if adapter.channel == channel_hint:
                    return adapter

        head = _read_head(path)
        scored = [(adapter.sniff(path, head), adapter) for adapter in self._adapters]
        best_score, best_adapter = max(
            scored, key=lambda item: (item[0], not isinstance(item[1], GenericAdapter))
        )
        return best_adapter if best_score >= SNIFF_MIN_SCORE else self._generic

    def parse(
        self,
        path: Path,
        *,
        channel_hint: Channel | None = None,
        mapping: MappingSpec | None = None,
        adapter_name: str | None = None,
        allow_partial: bool = False,
        parse_rows: bool = True,
    ) -> ParseFileResult:
        """编码 → 适配器 → 表头 → 逐行清洗。异常由 ``infra.errors`` 抛出，业务层翻译。"""
        head = _read_head(path)
        encoding = "xlsx"
        text: str | None = None
        if not is_xlsx(head):
            text, encoding = decode_file(path)

        adapter = self.get(adapter_name) if adapter_name else self.select(path, channel_hint)
        effective = mapping or MappingSpec()
        meta: dict[str, Any] = {}
        source = adapter.open_source(path, text=text, encoding=encoding)
        try:
            header = adapter.detect_header(source, allow_partial=allow_partial)
            effective = mapping or adapter.default_mapping(header)
            stats = ParseStats()
            rows: list[ParsedRow] = []
            if parse_rows and not effective.missing_core():
                rows = list(adapter.iter_rows(source, header, effective, stats))
            meta = _build_meta(source, header, stats)
        finally:
            source.close()

        return ParseFileResult(
            adapter=adapter.name,
            channel=adapter.channel,
            encoding=encoding,
            header=header,
            mapping=effective,
            rows=rows,
            stats=stats,
            meta=meta,
        )


def _read_head(path: Path, size: int = HEAD_PROBE_BYTES) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(size)
    except OSError:
        return b""


def _build_meta(source: RowSource, header: HeaderMatch, stats: ParseStats) -> dict[str, Any]:
    meta: dict[str, Any] = dict(source.meta)
    meta.update(header.meta)
    meta["sheet"] = source.meta.get("sheet", header.meta.get("sheet"))
    meta["delimiter"] = source.meta.get("delimiter")
    meta["preamble_rows"] = header.row_index
    meta["header_row_no"] = header.row_index
    meta["column_count"] = len(header.columns)
    meta["columns"] = list(header.columns)
    meta["empty_rows_skipped"] = stats.empty_rows_skipped
    meta["issues"] = stats.as_dict()
    return meta


def default_registry() -> ParserRegistry:
    """无状态，可安全复用（每次新建代价很低，但避免重复构造适配器实例）。"""
    return ParserRegistry()
