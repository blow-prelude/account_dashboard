"""字段清洗：文本归一、金额转分、时间归一、方向判定（SDD §8.5 / §8.6）。

三个纯函数，全部无 IO —— 这是本项目 TDD 的核心区：先在测试里钉死
`8.8 → 880`、`4.35 → 435`、`"¥1,234.5" → 123450`、`46316.82503472222 → 2026-10-21T19:48:03`，
再让实现去满足它们。

**金额禁止 ``float * 100``**：``8.8 * 100 = 880.0000000000001``、
``4.35 * 100 = 434.99999999999994``，``int()`` 之后一个变 880（对的）、一个变 434（错的）。
因此一律走 ``Decimal(str(v))``。
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from account_dashboard.infra.clock import to_iso
from account_dashboard.models.enums import Channel, Direction, IssueCode

# ── 文本 ────────────────────────────────────────────────────
EMPTY_MARKERS: tuple[str, ...] = ("", "/", "-", "—", "N/A")

_ZERO_WIDTH = dict.fromkeys(map(ord, "\ufeff\u200b\u200c\u200d\u2060"), None)
_SPACE_RE = re.compile(r"\s+")

# ── 金额 ────────────────────────────────────────────────────
_AMOUNT_NOISE = re.compile(r"[¥￥,，\s\t\u00a0元]")
_CENT = Decimal("0.01")
_ONE = Decimal("1")
MAX_AMOUNT_CENTS = 10**9

# ── 时间 ────────────────────────────────────────────────────
_MOMENT_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d",
    "%Y%m%d%H%M%S",
    "%Y年%m月%d日 %H:%M:%S",
    "%Y年%m月%d日",
)
# Excel 1900 日期系统：以 1899-12-30 为基准，自动覆盖 Excel 的「1900-02-29」历史 bug
EXCEL_EPOCH = datetime(1899, 12, 30)
MIN_EXCEL_SERIAL = 1
MAX_EXCEL_SERIAL = 200_000
_SECONDS_PER_DAY = Decimal(86400)


class TextParseError(ValueError):
    """文本清洗失败（目前不会发生，保留给未来强校验字段）。"""


class AmountParseError(ValueError):
    """金额无法解析 → 行级 issue ``AMOUNT_PARSE``，不阻断批次（EX-06）。"""


class TimeParseError(ValueError):
    """时间无法解析 → 行级 issue ``TIME_PARSE``（EX-07）。"""


def clean_text(
    value: Any,
    *,
    empty_markers: tuple[str, ...] = EMPTY_MARKERS,
    strip_trailing_colon: bool = True,
) -> str | None:
    """NFKC → 去 BOM/零宽/Tab → 折叠空白 → 去尾冒号 → empty_markers 归一为 ``None``。

    注意：``/`` 默认被视为空值，但微信「收/支」列的 ``/`` 是 **neutral 语义**，
    因此方向字段必须先查映射表再回退到本函数（见 :func:`parse_direction`）。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, float) and value.is_integer():
        # 461.0 这类数值型单元格不该输出成 "461.0"
        text = str(int(value))
    else:
        text = str(value)

    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)
    text = _SPACE_RE.sub(" ", text).strip()
    if strip_trailing_colon and text.endswith(":"):
        text = text[:-1].strip()
    if text in empty_markers:
        return None
    return text


def parse_amount_to_cents(value: Any, *, scale: int = 1) -> int:
    """金额 → 整数分（I4：金额恒非负，方向由 ``direction`` 承载）。

    ``scale`` 语义（与 ``MappingReq.amount_scale`` 一致）：

    * ``1``（默认）：原始数值单位是**元**，``Decimal → quantize(0.01) → ×100``；
    * ``100``：原始数值单位是**分**，直接取整为分（个别银行导出如此）。

    失败抛 :class:`AmountParseError`（行级 issue，不阻断批次）。
    """
    if value is None:
        raise AmountParseError("金额为空")
    if isinstance(value, bool):
        raise AmountParseError(f"金额不是数字：{value!r}")

    if isinstance(value, str):
        raw = unicodedata.normalize("NFKC", value)
        text = _AMOUNT_NOISE.sub("", raw).strip()
        if text in ("", "-", "—", "/", "N/A"):
            raise AmountParseError(f"金额为空：{value!r}")
    else:
        text = str(value).strip()

    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise AmountParseError(f"金额无法识别：{value!r}") from exc

    if not amount.is_finite():
        raise AmountParseError(f"金额无法识别：{value!r}")
    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -3:
        raise AmountParseError(f"金额小数位过多：{value!r}")

    amount = abs(amount)
    if scale == 100:
        cents = int(amount.quantize(_ONE, rounding=ROUND_HALF_UP))
    else:
        yuan = amount.quantize(_CENT, rounding=ROUND_HALF_UP)
        cents = int((yuan * 100).to_integral_value(rounding=ROUND_HALF_UP))

    if cents > MAX_AMOUNT_CENTS:
        raise AmountParseError(f"金额超出上限（{MAX_AMOUNT_CENTS} 分）：{value!r}")
    return cents


def parse_time(value: Any) -> datetime:
    """时间四路分派 → 秒级截断的本地时间（I5，**不做时区转换**）。

    ``datetime`` / Excel 序列号（``int`` / ``float``）/ 字符串 三条来源都要兼容：
    同一份微信账单里，单元格带日期样式时 openpyxl 给 ``datetime``，无样式时给
    ``float`` 序列号 —— 两种必须解析成**逐秒一致**的结果（U-TM-01）。
    """
    if value is None:
        raise TimeParseError("时间为空")
    if isinstance(value, datetime):
        return value.replace(microsecond=0, tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, bool):
        raise TimeParseError(f"时间无法识别：{value!r}")
    if isinstance(value, (int, float)):
        return _from_excel_serial(value)

    text = clean_text(value)
    if text is None:
        raise TimeParseError(f"时间为空：{value!r}")

    for fmt in _MOMENT_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:  # ISO 8601（含 T 分隔、带微秒）
        return datetime.fromisoformat(text).replace(microsecond=0, tzinfo=None)
    except ValueError as exc:
        raise TimeParseError(f"时间格式无法识别：{value!r}") from exc


def parse_time_to_iso(value: Any) -> str:
    """时间 → ``YYYY-MM-DDTHH:MM:SS``（落库与 DTO 的唯一表示）。"""
    return to_iso(parse_time(value))


def _from_excel_serial(serial: int | float) -> datetime:
    if not MIN_EXCEL_SERIAL < serial < MAX_EXCEL_SERIAL:
        raise TimeParseError(f"Excel 序列号超出范围：{serial!r}")
    # 用 Decimal 精确到秒再四舍五入，避免 float 误差把 19:48:03 变成 19:48:02
    seconds = Decimal(str(serial)) * _SECONDS_PER_DAY
    return EXCEL_EPOCH + timedelta(seconds=int(seconds.to_integral_value(rounding=ROUND_HALF_UP)))


# ── 方向 ────────────────────────────────────────────────────
CHANNEL_DIRECTION_MAP: dict[Channel, dict[str, Direction]] = {
    Channel.WECHAT: {
        "支出": Direction.EXPENSE,
        "收入": Direction.INCOME,
        "/": Direction.NEUTRAL,
        "不计收支": Direction.NEUTRAL,
    },
    Channel.ALIPAY: {
        "支出": Direction.EXPENSE,
        "收入": Direction.INCOME,
        "不计收支": Direction.NEUTRAL,
        "/": Direction.NEUTRAL,
    },
    Channel.BANK: {
        "支出": Direction.EXPENSE,
        "收入": Direction.INCOME,
        "支出/转出": Direction.EXPENSE,
        "收入/转入": Direction.INCOME,
        "借": Direction.EXPENSE,
        "贷": Direction.INCOME,
        "转出": Direction.EXPENSE,
        "转入": Direction.INCOME,
    },
    Channel.OTHER: {
        "支出": Direction.EXPENSE,
        "收入": Direction.INCOME,
        "不计收支": Direction.NEUTRAL,
        "/": Direction.NEUTRAL,
        "支": Direction.EXPENSE,
        "收": Direction.INCOME,
        "借": Direction.EXPENSE,
        "贷": Direction.INCOME,
        "-": Direction.EXPENSE,
        "+": Direction.INCOME,
        "out": Direction.EXPENSE,
        "in": Direction.INCOME,
    },
}

# 二次推断（仅当渠道映射缺失时使用，绝不覆盖渠道给出的值）
NEUTRAL_KEYWORDS: tuple[str, ...] = (
    "零钱通",
    "余额宝",
    "理财通",
    "申购",
    "赎回",
    "信用卡还款",
    "还款",
    "转账",
    "提现",
    "存入",
    "转出",
)
INCOME_KEYWORDS: tuple[str, ...] = ("奖学金", "助学金", "父母", "生活费", "拨款", "红包")


def parse_direction(
    value: Any,
    channel: Channel,
    *,
    extra_map: dict[str, Direction] | None = None,
    hint_text: str | None = None,
) -> tuple[Direction, IssueCode | None]:
    """方向判定，返回 ``(direction, issue)``。

    顺序：**模板覆盖表 → 渠道内置表 → 关键词二次推断 → neutral + issue**。

    不能先 ``clean_text``：它会把 ``/`` 当空值，而微信的 ``/`` 恰恰是 neutral 的
    合法表示（4 行实测）；先映射可避免把「不计收支」误判成「未知」。
    """
    key = _direction_key(value)

    if extra_map:
        hit = extra_map.get(key) if key else None
        if hit is not None:
            return Direction(hit), None

    table = CHANNEL_DIRECTION_MAP.get(channel, {})
    if key:
        hit = table.get(key)
        if hit is not None:
            return hit, None

    # 原始方向为空/未知 → 用「交易类型 / 商品」关键词兜底
    inferred = _infer_direction(hint_text or key)
    if inferred is not None:
        if key:
            # 渠道给了值但不在映射表：保留推断结果，同时记 issue 供人工核对
            return inferred, IssueCode.DIRECTION_UNKNOWN
        return inferred, None

    return Direction.NEUTRAL, IssueCode.DIRECTION_UNKNOWN


def _direction_key(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).translate(_ZERO_WIDTH)
    return _SPACE_RE.sub("", text).strip()


def _infer_direction(text: str) -> Direction | None:
    if not text:
        return None
    lowered = text.casefold()
    if any(keyword in text for keyword in NEUTRAL_KEYWORDS):
        return Direction.NEUTRAL
    if any(keyword in text for keyword in INCOME_KEYWORDS):
        return Direction.INCOME
    if any(keyword in lowered for keyword in ("refund", "income")):
        return Direction.INCOME
    return None
