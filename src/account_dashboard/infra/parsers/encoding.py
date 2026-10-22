"""编码探测与解码（SDD §8.4）。

顺序固定：BOM → utf-8 严格 → gb18030 严格 → chardet（置信度 > 0.7 且在白名单）→ E1002。

为什么要「严格」：支付宝账单是 GB18030，``raw.decode("utf-8", errors="replace")`` 会
"成功"返回一堆 ``\\ufffd``，后续表头识别会拿到乱码列名，最终表现成「表头不可识别」，
把用户引向错误的排查方向。严格模式 + 替换字符兜底检查，可以把问题锁定在编码环节。
"""

from __future__ import annotations

from pathlib import Path

import chardet

from account_dashboard.infra.errors import EncodingDetectionError

BOM_MAP: dict[bytes, str] = {
    b"\xef\xbb\xbf": "utf-8-sig",
    b"\xff\xfe": "utf-16-le",
    b"\xfe\xff": "utf-16-be",
}

CHARDET_MIN_CONFIDENCE = 0.7
CHARDET_PROBE_BYTES = 64 * 1024
CHARDET_WHITELIST = frozenset(
    {
        "utf-8",
        "utf-8-sig",
        "ascii",
        "gb18030",
        "gbk",
        "gb2312",
        "big5",
        "utf-16",
        "utf-16-le",
        "utf-16-be",
    }
)

XLSX_MAGIC = b"PK\x03\x04"
REPLACEMENT_CHAR = "\ufffd"


def is_xlsx(head: bytes) -> bool:
    """按魔数判断 xlsx（zip 容器），不信任扩展名（EX-01 的宽容处理）。"""
    return head[:4] == XLSX_MAGIC


def detect_and_decode(raw: bytes) -> tuple[str, str]:
    """返回 ``(text, encoding_name)``；全部失败抛 :class:`EncodingDetectionError`。"""
    if not raw:
        raise EncodingDetectionError("文件为空，无法识别编码", code="E1004")

    for bom, encoding in BOM_MAP.items():
        if raw.startswith(bom):
            text = _decode_strict(raw, encoding)
            if text is not None:
                return text, encoding

    for encoding in ("utf-8", "gb18030"):
        text = _decode_strict(raw, encoding)
        if text is not None:
            return text, encoding

    guess = chardet.detect(raw[:CHARDET_PROBE_BYTES])
    encoding = (guess.get("encoding") or "").lower()
    confidence = float(guess.get("confidence") or 0.0)
    if encoding in CHARDET_WHITELIST and confidence > CHARDET_MIN_CONFIDENCE:
        text = _decode_strict(raw, encoding)
        if text is not None:
            return text, encoding

    raise EncodingDetectionError(
        "无法识别文件编码，请用 Excel 另存为『CSV UTF-8』后重试"
    )


def decode_file(path: Path) -> tuple[str, str]:
    """读整个文本文件并解码（≤5MB，一次读入可接受）。"""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EncodingDetectionError(f"读取文件失败：{exc}") from exc
    return detect_and_decode(raw)


def _decode_strict(raw: bytes, encoding: str) -> str | None:
    try:
        text = raw.decode(encoding, errors="strict")
    except (UnicodeDecodeError, LookupError):
        return None
    if REPLACEMENT_CHAR in text:  # 严格模式理论上不会出现，防御性检查
        return None
    return text
