"""标准内部模型（**D0 契约**，C2-A §2.1 / §2.4）。

本文件是 A/B 两条并行线唯一的编译期依赖：字段名、类型、``None`` 语义一经签字即为
FZ-2 的一部分，改名等于让另一条线返工。B 线只读不写。

三个必须记住的语义：

* ``row_no`` 是 **1-based 数据行号**（不含前言与表头），与未来 ``raw_YYYY_MM.row_no``
  一一对应 —— 报告页"第 N 行有问题"能直接定位到原文件；
* ``rows`` **包含** ``is_valid=False`` 的行，不得在解析层过滤，否则预检的
  ``pending_manual`` 计数与报告四数字对不上（D-3）；
* ``amount_cents`` 是**整数分**，``fp`` 缺时间或金额时为 ``None``（EX-21）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Direction = Literal["income", "expense", "neutral"]
Channel = Literal["wechat", "alipay", "bank", "other"]
IssueCode = Literal["AMOUNT_PARSE", "TIME_PARSE", "DIRECTION_UNKNOWN", "EMPTY_ROW"]


class ParseIssue(BaseModel):
    """行级问题：不阻断批次，只让该行进入待确认（EX-06/07/21）。"""

    code: IssueCode
    row_no: int  # 1-based，与 raw.row_no 一致
    field: str | None = None  # "amount" / "occurred_at" / "direction"
    raw: str | None = None  # 原始值（截断 64 字符）


class ParsedRow(BaseModel):
    row_no: int  # 1-based，数据行序号（不含前言与表头）
    occurred_at: str | None  # ISO 本地时间；解析失败为 None
    amount_cents: int | None  # 整数分；解析失败为 None
    direction: Direction  # 无法判定时为 neutral + issue
    counterparty: str | None
    item: str | None
    txn_type: str | None
    payment_method: str | None
    platform_category: str | None
    platform_status: str | None
    channel: Channel
    fp: str | None  # 缺时间或金额时为 None（EX-21）
    raw_payload: dict[str, Any]  # 整行原貌：{表头名: 原始值}

    @property
    def is_valid(self) -> bool:
        """时间与金额都可解析 → 可参与指纹比对与入库。"""
        return self.occurred_at is not None and self.amount_cents is not None


class ParseMeta(BaseModel):
    sheet: str | None = None
    delimiter: str | None = None
    preamble_rows: int = 0
    header_row_no: int = 0  # 0-based
    empty_rows_skipped: int = 0  # 数据区整行空行，必须可见、不得静默丢弃
    issues: dict[str, int] = Field(default_factory=dict)  # {"TIME_PARSE": 1}


class ParseResult(BaseModel):
    rows: list[ParsedRow]
    header_row_no: int
    encoding: str  # "xlsx" / "gb18030" / "utf-8"
    adapter: str  # "wechat_xlsx" / "alipay_csv" / "generic"
    columns: int  # 识别出的列数（含尾随空列）
    meta: ParseMeta


class MappingSpec(BaseModel):
    """列索引映射。``-1`` 或 ``None`` 表示未映射。

    ``amount_scale`` 语义（D-4，两条线必须一致）：它是「原始数值 → 分」的**倍率**。
    ``1`` 走常规路径（``Decimal(v) * 100``）；``100`` 表示文件本身以分为单位。
    只允许 ``{1, 100}``，其他值由 B 线入口校验报 ``E1008``。
    """

    occurred_at: int
    amount: int
    direction: int
    counterparty: int | None = None
    item: int | None = None
    txn_type: int | None = None
    payment_method: int | None = None
    platform_category: int | None = None
    platform_status: int | None = None
    direction_map: dict[str, Direction] = Field(default_factory=dict)
    amount_scale: int = 1


__all__ = [
    "Channel",
    "Direction",
    "IssueCode",
    "MappingSpec",
    "ParseIssue",
    "ParseMeta",
    "ParseResult",
    "ParsedRow",
]
