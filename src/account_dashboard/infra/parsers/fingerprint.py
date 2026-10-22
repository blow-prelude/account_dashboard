"""去重指纹（SDD §8.7 / PRD 术语表）。

五项拼接：``occurred_at(秒) | amount_cents | direction | 归一化交易对方 | 归一化商品说明``。

设计取舍（改动前请先看 PRD 的指纹定义，它是契约）：

* **不含** ``batch_id`` / ``row_no`` / 平台单号 —— 否则跨文件重复导入永远识别不出来；
* **含 direction** —— 同一笔的「支出」与「退款收入」是两条真实记录，不应互相判重；
* 用**秒级时间**而非日期 —— 同日两笔同额同对方不同时刻的指纹不同（FR-04 规则 3）；
* 缺时间或缺金额 → ``None``，该行标 ``pending_manual``，**不参与自动去重**（EX-21）。

> 与 C2 分册 §4.3 的字面差异：分册把第五项写成「渠道」，而 PRD 术语表与 SDD §8.7
> 都把第五项定义为「商品说明」。以 PRD 为准（渠道已体现在「跨文件重复」的现实里：
> 同一笔流水不会同时出现在两个渠道的导出里，加 channel 只会削弱去重能力）。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from account_dashboard.infra.clock import to_iso
from account_dashboard.infra.parsers.cleaning import clean_text
from account_dashboard.models.enums import Direction

FP_HEX_LENGTH = 32
FP_VERSION = "v1"
_MASK_RE = re.compile(r"[（(]\s*\*+\s*[）)]")


def normalize_component(value: str | None) -> str:
    """NFKC → 去空白 → 去 ``(*)`` 掩码 → casefold；``None`` 与 ``""`` 等价。"""
    text = clean_text(value, empty_markers=("",))
    if not text:
        return ""
    text = _MASK_RE.sub("", text)
    return " ".join(text.split()).casefold()


def build_fingerprint(
    *,
    occurred_at: datetime | None,
    amount_cents: int | None,
    direction: Direction | None,
    counterparty: str | None,
    item: str | None,
) -> str | None:
    """五项齐全才产出指纹；任一缺失（时间/金额）返回 ``None``（EX-21）。"""
    if occurred_at is None or amount_cents is None:
        return None
    raw = "|".join(
        (
            to_iso(occurred_at),
            str(amount_cents),
            str(direction or Direction.NEUTRAL),
            normalize_component(counterparty),
            normalize_component(item),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:FP_HEX_LENGTH]
