"""raw 分表命名（K1/K2/K8 的唯一收口，Gate 0 冻结）。

全项目**唯一**允许拼接 SQL 标识符的地方：``raw_YYYY_MM`` 是物理表名，无法
参数化，因此月份必须先过 :data:`RAW_MONTH_RE` 白名单再拼字符串。A 线建表、
B 线查表都不得自己写 ``f"raw_{...}"`` —— 那样会绕过正则校验，也让「月份键的
两种形态」失去单一事实源：

* ``IngestReportDTO.monthly`` 的键是归档表名 ``raw_2026_06``（**带**前缀）；
* ``RawMonthDTO.month`` 是月份键 ``2026_06``（**不带**前缀）。
  两处不同构是有意的（前端 ``raw.js`` 按 ``month.slice(5)`` 拼表名），不要"修整齐"。

月份来源恒为行内 ``occurred_at``（``2026-10-21T19:48:03`` → ``2026_10``），
**不信任文件名**：文件名里的月份可能与行内时间不一致（EX-22 同类问题）。
"""

from __future__ import annotations

import re

from account_dashboard.errors import ErrorCode, TransactionError

RAW_TABLE_PREFIX = "raw_"
RAW_MONTH_RE = re.compile(r"^\d{4}_\d{2}$")


def month_key(occurred_at: str) -> str:
    """ISO 时间 → 月份键（``2026-10-21T19:48:03`` → ``2026_10``）。

    派生结果仍要过白名单：``occurred_at`` 若被污染成空串或非 ISO 形态，
    这里就必须炸，而不是把一个坏月份拼进 DDL。
    """
    key = occurred_at[:7].replace("-", "_")
    if not RAW_MONTH_RE.match(key):
        raise TransactionError(
            ErrorCode.RAW_TABLE_ERROR,
            "交易时间无法解析，无法归入原始库月份",
            detail={"occurred_at": occurred_at},
        )
    return key


def table_name(month: str) -> str:
    """月份键 → 归档表名（``2026_10`` → ``raw_2026_10``）；非法直接 ``E3002``。

    这是全项目唯一的 SQL 标识符拼接处（表名不能参数化），改动前先读本模块文档字符串。
    """
    if not RAW_MONTH_RE.match(month):
        raise TransactionError(
            ErrorCode.RAW_TABLE_ERROR,
            "原始库月份格式不合法",
            detail={"month": month, "pattern": RAW_MONTH_RE.pattern},
        )
    return f"{RAW_TABLE_PREFIX}{month}"


__all__ = ["RAW_MONTH_RE", "RAW_TABLE_PREFIX", "month_key", "table_name"]
