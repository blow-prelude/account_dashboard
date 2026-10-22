"""时间清洗（U-TM-01 / U-TM-02，EX-07）。

微信账单的时间单元格两种类型并存：带日期样式时 openpyxl 给 ``datetime``，
无样式时给 ``float`` 序列号。两者必须解析成**逐秒一致**的结果，否则同一份账单
会因为「有没有样式」产生两套时间，去重指纹随之失效。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from account_dashboard.infra.parsers.cleaning import TimeParseError, parse_time_to_iso

# 真实样例里的一个单元格：XML 存的是序列号浮点，带样式时 openpyxl 返回 datetime
SERIAL_SAMPLE = 46316.82503472222
SERIAL_SAMPLE_ISO = "2026-10-21T19:48:03"


def test_excel_serial_matches_datetime_branch() -> None:
    """U-TM-01：46316.82503472222 与 datetime 分支逐秒一致。"""
    assert parse_time_to_iso(SERIAL_SAMPLE) == SERIAL_SAMPLE_ISO
    assert parse_time_to_iso(datetime(2026, 10, 21, 19, 48, 3)) == SERIAL_SAMPLE_ISO


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-10-21 09:42:31", "2026-10-21T09:42:31"),
        ("2026/10/21 09:42:31", "2026-10-21T09:42:31"),
        ("2026-10-21 09:42", "2026-10-21T09:42:00"),
        ("2026/10/21 09:42", "2026-10-21T09:42:00"),
        ("2026-10-21", "2026-10-21T00:00:00"),
        ("20261021094231", "2026-10-21T09:42:31"),
        ("2026年10月21日 09:42:31", "2026-10-21T09:42:31"),
        ("2026年10月21日", "2026-10-21T00:00:00"),
        ("2026-10-21T09:42:31", "2026-10-21T09:42:31"),
    ],
)
def test_time_formats(raw: str, expected: str) -> None:
    assert parse_time_to_iso(raw) == expected


def test_microseconds_truncated() -> None:
    assert parse_time_to_iso(datetime(2026, 10, 21, 9, 42, 31, 987654)) == "2026-10-21T09:42:31"
    assert parse_time_to_iso("2026-10-21T09:42:31.987654") == "2026-10-21T09:42:31"


def test_excel_serial_rounds_to_nearest_second() -> None:
    """序列号 19:48:02.999999 必须进位成 19:48:03，而不是被截断成 02。"""
    near = (SERIAL_SAMPLE - 1e-9)
    assert parse_time_to_iso(near) == SERIAL_SAMPLE_ISO


@pytest.mark.parametrize("raw", [None, "", "/", "abc", "2026-13-01", 0, 999999, -3])
def test_time_parse_error(raw: object) -> None:
    with pytest.raises(TimeParseError):
        parse_time_to_iso(raw)
