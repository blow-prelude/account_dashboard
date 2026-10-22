"""时间与格式的唯一来源（I5：ISO 8601 本地时间，秒级，无时区后缀）。"""

from __future__ import annotations

from datetime import datetime

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"


def now_iso() -> str:
    """当前本地时间的 ISO 表示，精确到秒。"""
    return datetime.now().strftime(ISO_FORMAT)


def to_iso(moment: datetime) -> str:
    """把 ``datetime`` 截断到秒；**不做时区转换**。"""
    return moment.replace(microsecond=0).strftime(ISO_FORMAT)
