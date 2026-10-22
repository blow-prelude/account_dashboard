"""统一 ``ParseAdapter`` 协议与两种 ``RowSource``（SDD §8.1）。

``RowSource`` 把 CSV 与 xlsx 的差异吸收掉，让表头探测与字段清洗只写一份。
两个实现都保证 **0-based 行号与物理行号一致**：微信样例的 XML 里缺了第 6、16 行，
openpyxl 会补出空行（707 行），这条性质直接支撑「表头在第 18 行」这个可被人读懂的行号。
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from itertools import islice
from pathlib import Path
from typing import Any, Protocol

from account_dashboard.infra.errors import NoDataRowsError, RowLimitError
from account_dashboard.infra.parsers.cleaning import (
    AmountParseError,
    TimeParseError,
    clean_text,
    parse_amount_to_cents,
    parse_direction,
    parse_time,
)
from account_dashboard.infra.parsers.fingerprint import build_fingerprint
from account_dashboard.infra.parsers.header_detect import (
    DEFAULT_MAX_SCAN,
    score_headers,
    select_header,
)
from account_dashboard.infra.parsers.models import HeaderMatch, ParsedRow, ParseStats
from account_dashboard.models.enums import Channel, Direction, IssueCode
from account_dashboard.models.internal import MappingSpec

MAX_ROWS = 50_000
DELIMITER_CANDIDATES: tuple[str, ...] = (",", "\t", ";", "|")


class RowSource(Protocol):
    """行源：惰性产出 ``list[Any]``，下标即 0-based 行号。"""

    meta: dict[str, Any]

    def iter_rows(self) -> Iterator[list[Any]]: ...

    def close(self) -> None: ...


@dataclass
class CsvRowSource:
    """已解码文本的 CSV 行源（分隔符自动探测：首 20 行按候选字符频次取最大）。"""

    text: str
    delimiter: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.delimiter is None:
            self.delimiter = detect_delimiter(self.text)
        self.meta.setdefault("delimiter", self.delimiter)
        self.meta.setdefault("sheet", None)

    def iter_rows(self) -> Iterator[list[Any]]:
        reader = csv.reader(io.StringIO(self.text, newline=""), delimiter=self.delimiter or ",")
        for row in reader:
            yield list(row)

    def close(self) -> None:  # 文本已在内存，无需释放
        return


@dataclass
class XlsxRowSource:
    """xlsx 行源：``read_only`` 流式读取，单 sheet 时自动选中表头得分最高者。"""

    path: Path
    sheet_name: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    _workbook: Any = field(default=None, repr=False)
    _sheet: Any = field(default=None, repr=False)

    def sheets(self) -> list[str]:
        workbook = self._open()
        return list(workbook.sheetnames)

    def _open(self) -> Any:
        if self._workbook is None:
            from openpyxl import load_workbook  # 延迟导入：纯 CSV 路径不需要 openpyxl

            self._workbook = load_workbook(self.path, read_only=True, data_only=True)
        return self._workbook

    def _choose_sheet(self) -> Any:
        workbook = self._open()
        if self.sheet_name and self.sheet_name in workbook.sheetnames:
            self.meta.setdefault("sheet", self.sheet_name)
            return workbook[self.sheet_name]

        best_sheet = workbook.worksheets[0]
        best_score = -1.0
        for worksheet in workbook.worksheets:
            rows = _iterate_sheet(worksheet)
            matches = score_headers(rows, max_scan=DEFAULT_MAX_SCAN)
            best = matches[0].score if matches else 0.0
            if best > best_score:
                best_score = best
                best_sheet = worksheet
        self.meta.setdefault("sheet", best_sheet.title)
        return best_sheet

    def iter_rows(self) -> Iterator[list[Any]]:
        if self._sheet is None:
            self._sheet = self._choose_sheet()
        for row in self._sheet.iter_rows(values_only=True):
            yield list(row)

    def close(self) -> None:
        if self._workbook is not None:
            self._workbook.close()
            self._workbook = None
            self._sheet = None


def _iterate_sheet(worksheet: Any) -> Iterator[list[Any]]:
    for row in worksheet.iter_rows(values_only=True):
        yield list(row)


def detect_delimiter(text: str) -> str:
    """统计首 20 行各候选分隔符出现次数，取最大者（并列时按候选顺序）。"""
    sample = "\n".join(text.splitlines()[:20])
    counts = {candidate: sample.count(candidate) for candidate in DELIMITER_CANDIDATES}
    best = max(DELIMITER_CANDIDATES, key=lambda candidate: counts[candidate])
    return best if counts[best] > 0 else ","


class BaseAdapter:
    """适配器公共实现：表头探测、行清洗、指纹构造全部在这里，子类只声明差异。"""

    name: str = "generic"
    channel: Channel = Channel.OTHER
    extensions: tuple[str, ...] = (".csv",)
    max_scan: int = DEFAULT_MAX_SCAN

    # ── 子类实现 ────────────────────────────────────────────
    def sniff(self, path: Path, head: bytes) -> float:
        raise NotImplementedError

    def open_source(
        self,
        path: Path,
        *,
        text: str | None = None,
        encoding: str | None = None,
    ) -> RowSource:
        raise NotImplementedError

    # ── 公共流程 ────────────────────────────────────────────
    def detect_header(
        self,
        source: RowSource,
        *,
        allow_partial: bool = False,
    ) -> HeaderMatch:
        matches = score_headers(source.iter_rows(), max_scan=self.max_scan, meta=source.meta)
        return select_header(matches, allow_partial=allow_partial)

    def default_mapping(self, header: HeaderMatch) -> MappingSpec:
        columns = {name: header.mapping.get(name) for name in _ALL_FIELDS}
        return MappingSpec(columns=columns)

    def iter_rows(
        self,
        source: RowSource,
        header: HeaderMatch,
        mapping: MappingSpec,
        stats: ParseStats | None = None,
    ) -> Iterator[ParsedRow]:
        counters = stats if stats is not None else ParseStats()
        width = len(header.columns)
        payload_keys = build_payload_keys(header.columns)
        scale = mapping.amount_scale if mapping.amount_scale in (1, 100) else 1

        data_row_no = 0
        for cells in islice(source.iter_rows(), header.row_index + 1, None):
            data_row_no += 1
            if data_row_no > MAX_ROWS:
                raise RowLimitError(
                    f"数据行超过 {MAX_ROWS} 行，请按月份分批导出",
                    detail={"max_rows": MAX_ROWS},
                )

            normalized = normalize_cells(cells, width)
            if is_blank_row(normalized):
                counters.empty_rows_skipped += 1
                continue

            row = ParsedRow(row_no=data_row_no, payload=_build_payload(payload_keys, normalized))
            _fill_row(
                row=row,
                cells=normalized,
                mapping=mapping,
                channel=self.channel,
                scale=scale,
                stats=counters,
            )
            counters.rows += 1
            yield row

        if counters.rows == 0:
            raise NoDataRowsError(
                "文件里没有数据行，请检查导出范围",
                detail={"empty_rows_skipped": counters.empty_rows_skipped},
            )


_ALL_FIELDS: tuple[str, ...] = (
    "occurred_at",
    "amount",
    "direction",
    "counterparty",
    "item",
    "txn_type",
    "payment_method",
    "platform_category",
    "platform_status",
)


def normalize_cells(cells: Sequence[Any], width: int) -> list[Any]:
    """列数对齐：不足补 ``None``，超出截断（截断信息由调用方按需记 issue）。"""
    if width <= 0:
        return list(cells)
    if len(cells) == width:
        return list(cells)
    if len(cells) < width:
        return [*cells, *([None] * (width - len(cells)))]
    return list(cells[:width])


def is_blank_row(cells: Sequence[Any]) -> bool:
    for cell in cells:
        if cell is None:
            continue
        if isinstance(cell, str) and not cell.strip():
            continue
        return False
    return True


def build_payload_keys(columns: Sequence[str]) -> list[str]:
    """整行原貌的键名：优先列名，空列名用 ``column_{i}``，重名加后缀。"""
    keys: list[str] = []
    seen: dict[str, int] = {}
    for index, column in enumerate(columns):
        text = clean_text(column, empty_markers=("",)) or f"column_{index}"
        count = seen.get(text, 0)
        seen[text] = count + 1
        keys.append(text if count == 0 else f"{text}#{count + 1}")
    return keys


def _build_payload(keys: Sequence[str], cells: Sequence[Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for index, key in enumerate(keys):
        value = cells[index] if index < len(cells) else None
        if isinstance(value, datetime):
            payload[key] = value.replace(microsecond=0).isoformat()
        elif isinstance(value, date):
            payload[key] = value.isoformat()
        elif value is None or isinstance(value, (str, int, float, bool)):
            payload[key] = value
        else:
            payload[key] = str(value)
    return payload


def _cell(cells: Sequence[Any], index: int | None) -> Any:
    if index is None or index < 0 or index >= len(cells):
        return None
    return cells[index]


def _fill_row(
    *,
    row: ParsedRow,
    cells: Sequence[Any],
    mapping: MappingSpec,
    channel: Channel,
    scale: int,
    stats: ParseStats,
) -> None:
    raw_time = _cell(cells, mapping.column("occurred_at"))
    try:
        row.occurred_at = parse_time(raw_time)
    except TimeParseError:
        row.occurred_at = None
        row.add_issue(IssueCode.TIME_PARSE, column="occurred_at", raw_value=raw_time)
        stats.count_issue(IssueCode.TIME_PARSE)

    raw_amount = _cell(cells, mapping.column("amount"))
    try:
        row.amount_cents = parse_amount_to_cents(raw_amount, scale=scale)
    except AmountParseError:
        row.amount_cents = None
        row.add_issue(IssueCode.AMOUNT_PARSE, column="amount", raw_value=raw_amount)
        stats.count_issue(IssueCode.AMOUNT_PARSE)

    row.counterparty = clean_text(_cell(cells, mapping.column("counterparty")))
    row.item = clean_text(_cell(cells, mapping.column("item")))
    row.txn_type = clean_text(_cell(cells, mapping.column("txn_type")))
    row.payment_method = clean_text(_cell(cells, mapping.column("payment_method")))
    row.platform_category = clean_text(_cell(cells, mapping.column("platform_category")))
    row.platform_status = clean_text(_cell(cells, mapping.column("platform_status")))

    raw_direction = _cell(cells, mapping.column("direction"))
    hint = row.txn_type or row.item or row.platform_category
    direction, issue = parse_direction(
        raw_direction,
        channel,
        extra_map={key: Direction(value) for key, value in mapping.direction_map.items()},
        hint_text=hint,
    )
    row.direction = direction
    if issue is not None:
        row.add_issue(issue, column="direction", raw_value=raw_direction)
        stats.count_issue(issue)

    row.fingerprint = build_fingerprint(
        occurred_at=row.occurred_at,
        amount_cents=row.amount_cents,
        direction=row.direction,
        counterparty=row.counterparty,
        item=row.item,
    )


def dumps_payload(payload: dict[str, Any]) -> str:
    """``raw_payload`` 的落库形态：``ensure_ascii=False``，与 §5.1 约定一致。"""
    return json.dumps(payload, ensure_ascii=False)
