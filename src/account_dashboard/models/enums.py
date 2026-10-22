"""全库统一枚举（SDD §5.1）。

字面量是**契约**：``channel`` / ``direction`` / ``status`` 的取值已冻结在 ``V001__init.sql``
的 CHECK 约束里，改动等同 schema 变更。界面层负责中文映射，后端只认英文小写。
"""

from __future__ import annotations

from enum import StrEnum


class Channel(StrEnum):
    WECHAT = "wechat"
    ALIPAY = "alipay"
    BANK = "bank"
    OTHER = "other"


class Direction(StrEnum):
    """收支方向（I1）。

    ``neutral`` 是「不计收支」的合法语义（微信 ``/``、支付宝 ``不计收支``），
    既不是空值也不是未知值 —— 它参与存储，但不进统计。
    """

    INCOME = "income"
    EXPENSE = "expense"
    NEUTRAL = "neutral"


class BatchStatus(StrEnum):
    """批次 7 态（SDD §5.6）。故意不含「待上传」。"""

    UPLOADED = "uploaded"
    MAPPED_PENDING = "mapped_pending"
    PRECHECKED = "prechecked"
    INGESTING = "ingesting"
    INGESTED = "ingested"
    DISCARDED = "discarded"
    FAILED = "failed"


TERMINAL_STATUSES = frozenset({BatchStatus.INGESTED, BatchStatus.DISCARDED})


class BatchAction(StrEnum):
    """批次动作。C2 只实现前四个，``ingest`` 留给 C3（现在一律 E2002）。"""

    PARSE = "parse"
    MAP = "map"
    PRECHECK = "precheck"
    DISCARD = "discard"
    INGEST = "ingest"
    CONFIRM = "confirm"


class IssueCode(StrEnum):
    """行级解析问题（不阻断批次，EX-06/07）。"""

    AMOUNT_PARSE = "AMOUNT_PARSE"
    TIME_PARSE = "TIME_PARSE"
    DIRECTION_UNKNOWN = "DIRECTION_UNKNOWN"
    EXTRA_COLUMNS = "EXTRA_COLUMNS"
    EMPTY_ROW = "EMPTY_ROW"


class DedupLabel(StrEnum):
    NEW = "new"
    DUP = "dup"
    PENDING_MANUAL = "pending_manual"
