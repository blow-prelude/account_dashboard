"""``raw_YYYY_MM`` 分表命名的唯一收口（K1 / K2 / K8，Gate 0 冻结）。

全项目**唯一**允许拼接 SQL 标识符的地方：SQLite 的表名不能参数化，
因此所有 ``raw_`` 表名必须经 :func:`table_name` 校验后拼出，两侧
（A 线写入、B 线只读）都不得自己写 ``f"raw_{month}"``。

两种月份键形态**有意为之不同构**（写进注释，防止后来者"顺手统一"）：

* ``IngestReportDTO.monthly`` 的键是**归档表名** ``"raw_2026_06"``；
* ``/raw/months[].month`` 是**月份键** ``"2026_06"``（前端 ``raw.js``
  用 ``x.month.slice(5)`` 取月份、拼 ``raw_${ym}`` 查表，多一个前缀就查空表）。

月份一律由 ``occurred_at`` 推出（``occurred_at[:7].replace("-", "_")``），
**不信任文件名** —— 文件名里的月份可以与内容差一个月（EX-14）。
"""

from __future__ import annotations

import re

from account_dashboard.infra.errors import RawTableError

# 月份键："2026_06"（无 raw_ 前缀）
RAW_MONTH_RE = re.compile(r"^\d{4}_\d{2}$")
# 归档表名："raw_2026_06"
RAW_TABLE_RE = re.compile(r"^raw_\d{4}_\d{2}$")


def month_key(occurred_at: str) -> str:
    """从 ISO 时间推出月份键：``"2026-10-21T19:48:03"`` → ``"2026_10"``。

    非法（空串、长度不足、含异体字符）一律抛 ``E3002`` —— 调用方
    （A 线建表、B 线追溯）都不允许把未校验的字符串带进 SQL。
    """
    key = occurred_at[:7].replace("-", "_")
    if not RAW_MONTH_RE.match(key):
        raise RawTableError(
            f"无法从时间戳推出月份：{occurred_at!r}",
            detail={"occurred_at": occurred_at},
        )
    return key


def table_name(month: str) -> str:
    """月份键 → 归档表名：``"2026_10"`` → ``"raw_2026_10"``（非法 → ``E3002``）。"""
    if not RAW_MONTH_RE.match(month):
        raise RawTableError(
            f"月份格式应为 YYYY_MM，收到 {month!r}",
            detail={"month": month},
        )
    return f"raw_{month}"


def month_of_table(table: str) -> str | None:
    """归档表名 → 月份键；不是合法 raw 表名时返回 ``None``（供枚举用）。"""
    if not RAW_TABLE_RE.match(table):
        return None
    return table[len("raw_") :]
