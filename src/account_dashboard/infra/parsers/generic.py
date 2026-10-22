"""兜底适配器（EX-03）：未知渠道 / 未知列名，靠别名表 + 手动映射。

它是「永远能打开文件」的那一层：不看渠道、不看文件名，只按别名猜列；
猜不出 5 核心就抛 E1003，前端转手动映射后仍用本适配器解析。
"""

from __future__ import annotations

from pathlib import Path

from account_dashboard.infra.parsers.base import (
    BaseAdapter,
    CsvRowSource,
    RowSource,
    XlsxRowSource,
)
from account_dashboard.infra.parsers.encoding import XLSX_MAGIC, decode_file
from account_dashboard.models.enums import Channel


class GenericAdapter(BaseAdapter):
    name = "generic"
    channel = Channel.OTHER
    extensions = (".csv", ".xlsx")

    def sniff(self, path: Path, head: bytes) -> float:
        """兜底分：任何能打开的文件都拿基础分，但不高于具体渠道适配器。"""
        if not head:
            return 0.0
        return 0.7 if head[:4] == XLSX_MAGIC else 0.6

    def open_source(
        self,
        path: Path,
        *,
        text: str | None = None,
        encoding: str | None = None,
    ) -> RowSource:
        with path.open("rb") as handle:
            head = handle.read(4)
        if head == XLSX_MAGIC:
            return XlsxRowSource(path=path)
        if text is None:
            text, _ = decode_file(path)
        return CsvRowSource(text=text)
