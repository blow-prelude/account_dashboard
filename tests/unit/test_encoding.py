"""编码探测（U-EN-01 / U-EN-02，SDD §8.4）。

GB18030 被误判成 UTF-8 的典型症状是「解码成功但全是乱码」，之后表头识别会失败，
把用户引向错误的方向。所以这里断言的不只是「能解」，还包括「解出来的中文是对的」。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from account_dashboard.infra.errors import EncodingDetectionError
from account_dashboard.infra.parsers.encoding import detect_and_decode, is_xlsx


def test_gb18030_chinese_is_not_garbled(fixtures_dir: Path) -> None:
    raw = (fixtures_dir / "alipay_sample_gb18030.csv").read_bytes()
    text, encoding = detect_and_decode(raw)
    assert encoding == "gb18030"
    assert "交易时间" in text
    assert "不计收支" in text
    assert "\ufffd" not in text


def test_utf8_preferred_when_valid(fixtures_dir: Path) -> None:
    raw = (fixtures_dir / "alipay_sample_utf8.csv").read_bytes()
    text, encoding = detect_and_decode(raw)
    assert encoding == "utf-8"
    assert "交易时间" in text


def test_bom_detected() -> None:
    text, encoding = detect_and_decode("\ufeff交易时间,金额".encode())
    assert encoding == "utf-8-sig"
    assert text.lstrip("\ufeff").startswith("交易时间")


def test_broken_bytes_raise_e1002(fixtures_dir: Path) -> None:
    raw = (fixtures_dir / "broken_encoding.csv").read_bytes()
    with pytest.raises(EncodingDetectionError) as excinfo:
        detect_and_decode(raw)
    assert excinfo.value.code == "E1002"


def test_empty_bytes_rejected() -> None:
    with pytest.raises(EncodingDetectionError) as excinfo:
        detect_and_decode(b"")
    assert excinfo.value.code == "E1004"


def test_xlsx_magic(fixtures_dir: Path) -> None:
    assert is_xlsx((fixtures_dir / "wechat_sample_sanitized.xlsx").read_bytes()[:8])
    assert not is_xlsx((fixtures_dir / "alipay_sample_gb18030.csv").read_bytes()[:8])
