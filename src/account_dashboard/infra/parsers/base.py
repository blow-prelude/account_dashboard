"""解析适配器协议（C2-A §2.3，**D0 契约**）。

两个约束值得单独说明：

1. ``parse(path, spec)`` 的 ``spec`` 分支必须**可重放** —— 同一个 ``MappingSpec``
   解析两次，结果必须逐字段相同。C3 的入库与 C4 的重算全靠这条路径；
2. ``sniff`` 只允许看扩展名/魔数/前几行，**不做完整解析**，否则注册表选适配器
   会变成 O(文件大小)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from account_dashboard.models.internal import Channel, MappingSpec, ParseResult


@runtime_checkable
class ParserAdapter(Protocol):
    name: str  # "wechat_xlsx"
    channel: Channel

    def sniff(self, path: Path) -> bool:
        """只看扩展名/魔数/前几行，不做完整解析。"""
        ...

    def parse(self, path: Path, spec: MappingSpec | None = None) -> ParseResult:
        """``spec=None`` → 自动探测表头 + 默认列映射；

        ``spec`` 非空 → 按给定列索引解析（C3 重放 / C4 重算依赖这条路径）。
        """
        ...


__all__ = ["ParserAdapter"]
