"""解析内核的数据结构（全部是无 IO 的纯值对象，便于 TDD）。

字段命名与 SDD §8.1 一致；``ParsedRow`` 是 C3 入库与 C4 重算的共同输入，
因此它是**交接契约**，改字段名等于改契约（须走 CONTRACT-CHANGELOG）。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from account_dashboard.infra.clock import to_iso
from account_dashboard.models.enums import Direction, IssueCode


@dataclass(frozen=True, slots=True)
class ParseIssue:
    """行级问题：不阻断批次，但要能在预览/预检页看见（EX-06/07）。"""

    code: IssueCode
    row_no: int
    field: str | None = None
    raw_value: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": str(self.code),
            "row_no": self.row_no,
            "field": self.field,
            "raw_value": self.raw_value,
        }


@dataclass(frozen=True, slots=True)
class HeaderMatch:
    """一行表头的识别结果。"""

    row_index: int  # 0-based，表头在 rows[row_index]
    mapping: dict[str, int]  # canonical_field -> column index
    score: float  # 0..1，分母固定 15
    matched_core: int  # 命中核心字段数（0..5）
    columns: tuple[str, ...]  # 归一化后的表头文本（保留空列）
    meta: dict[str, Any] = field(default_factory=dict)  # {preamble_rows, sheet, delimiter}

    @property
    def header_row_no(self) -> int:
        """与 DB 一致的 0-based 行号。"""
        return self.row_index


@dataclass(slots=True)
class ParsedRow:
    """一行清洗后的标准数据。"""

    row_no: int  # 1-based，数据行序号（不含前言与表头；空行占位也占号）
    occurred_at: datetime | None = None
    amount_cents: int | None = None
    direction: Direction | None = None
    counterparty: str | None = None
    item: str | None = None
    txn_type: str | None = None
    payment_method: str | None = None
    platform_category: str | None = None
    platform_status: str | None = None
    fingerprint: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    issues: list[ParseIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """时间与金额都可解析（D-6：不可解析的行既不写 raw 也不写 transaction，
        只在导入报告的 ``skipped_invalid`` 里留痕）。方向有关键词兜底，不会为 None。
        """
        return self.occurred_at is not None and self.amount_cents is not None

    @property
    def occurred_at_iso(self) -> str | None:
        return to_iso(self.occurred_at) if self.occurred_at is not None else None

    def add_issue(
        self,
        code: IssueCode,
        *,
        column: str | None = None,
        raw_value: Any = None,
    ) -> None:
        text = None if raw_value is None else str(raw_value)
        self.issues.append(ParseIssue(code=code, row_no=self.row_no, field=column, raw_value=text))


@dataclass(slots=True)
class ParseStats:
    """解析过程的计数（写进 ``parse_meta``，不做静默丢弃）。"""

    rows: int = 0
    empty_rows_skipped: int = 0
    issue_counts: Counter[str] = field(default_factory=Counter)

    def count_issue(self, code: IssueCode) -> None:
        self.issue_counts[str(code)] += 1

    def as_dict(self) -> dict[str, int]:
        return dict(sorted(self.issue_counts.items()))
