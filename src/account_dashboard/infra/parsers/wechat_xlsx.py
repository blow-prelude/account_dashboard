"""微信支付账单（xlsx）适配器（SDD §8.8 左表）。

特征：11 列、无尾随空列；时间列可能是 ``datetime`` 也可能是不带日期样式的
Excel 序列号浮点；金额列是**数值型**（int 461 / float 228）—— 这正是
``Decimal(str(v))`` 存在的理由。
"""

from __future__ import annotations

from pathlib import Path

from account_dashboard.infra.parsers.base import BaseAdapter, RowSource, XlsxRowSource
from account_dashboard.infra.parsers.encoding import XLSX_MAGIC
from account_dashboard.models.enums import Channel

SNIFF_MARKERS: tuple[str, ...] = ("微信", "wechat", "wxpay")
CONTENT_MARKERS: tuple[str, ...] = ("微信支付", "微信昵称", "微信账单")
SNIFF_SCAN_ROWS = 12


class WechatXlsxAdapter(BaseAdapter):
    name = "wechat_xlsx"
    channel = Channel.WECHAT
    extensions = (".xlsx",)

    def sniff(self, path: Path, head: bytes) -> float:
        if not head or head[:4] != XLSX_MAGIC:
            return 0.0
        lowered = path.name.casefold()
        if any(marker in lowered for marker in SNIFF_MARKERS):
            return 0.95
        return 0.95 if self._content_marker(path) else 0.0

    def _content_marker(self, path: Path) -> bool:
        """读前若干行的前几列找「微信支付」字样；打不开就当不是微信账单。"""
        source = XlsxRowSource(path=path)
        try:
            for index, row in enumerate(source.iter_rows()):
                if index >= SNIFF_SCAN_ROWS:
                    break
                joined = " ".join(str(cell) for cell in row[:4] if cell is not None)
                if any(marker in joined for marker in CONTENT_MARKERS):
                    return True
        except Exception:  # noqa: BLE001 - 探测失败不应影响上传（交给 openpyxl 在解析阶段报错）
            return False
        finally:
            source.close()
        return False

    def open_source(
        self,
        path: Path,
        *,
        text: str | None = None,
        encoding: str | None = None,
    ) -> RowSource:
        return XlsxRowSource(path=path)
