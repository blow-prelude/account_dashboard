"""支付宝交易明细（csv / GB18030）适配器（SDD §8.8 右表）。

特征：13 列（末列为空，行尾多余逗号）、GB18030 编码、时间与金额都是字符串、
订单号列尾部带 Tab（669/669 行），金额形如 ``"45.90"``。
"""

from __future__ import annotations

from pathlib import Path

from account_dashboard.infra.parsers.base import BaseAdapter, CsvRowSource, RowSource
from account_dashboard.infra.parsers.encoding import XLSX_MAGIC
from account_dashboard.models.enums import Channel

FILENAME_MARKERS: tuple[str, ...] = ("支付宝", "alipay", "zhifubao")
CONTENT_MARKERS: tuple[str, ...] = ("支付宝", "交易分类", "对方账号", "不计收支")
SNIFF_PROBE_BYTES = 8192


class AlipayCsvAdapter(BaseAdapter):
    name = "alipay_csv"
    channel = Channel.ALIPAY
    extensions = (".csv",)

    def sniff(self, path: Path, head: bytes) -> float:
        if not head or head[:4] == XLSX_MAGIC:
            return 0.0
        lowered = path.name.casefold()
        if any(marker in lowered for marker in FILENAME_MARKERS):
            return 0.95
        probe = _probe_text(head)
        if any(marker in probe for marker in CONTENT_MARKERS):
            return 0.9
        return 0.0

    def open_source(
        self,
        path: Path,
        *,
        text: str | None = None,
        encoding: str | None = None,
    ) -> RowSource:
        if text is None:
            from account_dashboard.infra.parsers.encoding import decode_file

            text, _ = decode_file(path)
        return CsvRowSource(text=text)


def _probe_text(head: bytes) -> str:
    """仅供探测用：把头部字节用两种常见编码各解一遍（忽略错误），拼接后找标记。

    不能只试一种是踩过的坑：落盘后文件名是 ``uuid.csv``，英文名标记全失效，只能靠内容。
    而 GB18030 的中文用 utf-8 + ignore 解码会被整体丢掉，于是「支付宝」三个字消失，
    适配器被误判成 generic（进而把模板错存到 other 渠道）。
    """
    chunks: list[str] = []
    for encoding in ("utf-8", "gb18030"):
        try:
            chunks.append(head[:SNIFF_PROBE_BYTES].decode(encoding, errors="ignore"))
        except LookupError:  # pragma: no cover - 编码名固定，不会发生
            continue
    return "\n".join(chunks)
