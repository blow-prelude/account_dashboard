"""适配器注册表（C2-A §2.5，**D0 契约**）。

这是 B 线唯一的解析注入点（合稿 K9）：把注册表整体替换成 ``tests/fakes/fake_parser.py``
的 ``FakeParser``，15 个端点与全部用例仍应全绿 —— 所以本模块必须零格式知识。

解析顺序（``resolve``）：

1. ``channel_hint`` 命中 → 直接用该渠道适配器（用户上传时选了渠道，尊重其选择）；
2. 适配器声明了 ``extensions`` 且后缀命中 → 用它（快路径，不碰文件）；
3. 逐个 ``sniff``（只允许看扩展名/魔数/前几行）；
4. 都不中 → ``generic``；
5. 连 ``generic`` 都没有（A 线未合稿）→ ``ParseError``，由 B 线投影成 E1003。

第 5 条是并行开发的必要摩擦：A 线没就绪时 B 线必须能跑，但**不能假装解析成功**。
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from pathlib import Path

from account_dashboard.infra.logger import get_logger
from account_dashboard.infra.parsers.base import ParserAdapter
from account_dashboard.infra.parsers.errors import ParseError
from account_dashboard.models.internal import Channel

_logger = get_logger("parsers")

# A 线交付的适配器（延迟导入：模块不存在时注册表照常可用）
_BUILTIN_ADAPTERS: tuple[tuple[str, str], ...] = (
    ("wechat_xlsx", "WechatXlsxParser"),
    ("alipay_csv", "AlipayCsvParser"),
    ("generic", "GenericParser"),
)


class ParserRegistry:
    def __init__(self, adapters: Sequence[ParserAdapter] | None = None) -> None:
        self._by_name: dict[str, ParserAdapter] = {}
        self._ordered: list[ParserAdapter] = []
        for adapter in adapters or ():
            self.register(adapter)

    # ── 维护 ──────────────────────────────────────────────────
    def register(self, adapter: ParserAdapter) -> None:
        name = getattr(adapter, "name", "")
        if not name:
            raise ValueError("适配器必须有非空的 name")
        if name in self._by_name:
            raise ValueError(f"适配器重复注册：{name}")
        self._by_name[name] = adapter
        self._ordered.append(adapter)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._by_name

    def names(self) -> tuple[str, ...]:
        return tuple(self._by_name)

    # ── 查询 ──────────────────────────────────────────────────
    def get(self, name: str) -> ParserAdapter:
        """B 线重放时按名字取回同一适配器（``staging_batch.adapter``）。"""
        adapter = self._by_name.get(name)
        if adapter is None:
            raise ParseError(f"找不到解析器「{name}」，请重新解析该批次")
        return adapter

    def resolve(self, file_name: str, channel_hint: Channel | None = None) -> ParserAdapter:
        if channel_hint:
            for adapter in self._ordered:
                if getattr(adapter, "channel", None) == channel_hint:
                    return adapter

        suffix = Path(file_name).suffix.lower()
        for adapter in self._ordered:
            extensions = getattr(adapter, "extensions", None)
            if extensions and suffix in {str(item).lower() for item in extensions}:
                return adapter

        for adapter in self._ordered:
            try:
                if adapter.sniff(Path(file_name)):
                    return adapter
            except (OSError, ValueError) as exc:
                # sniff 只应看元信息；真去读文件失败也不该让选适配器整体失败
                _logger.debug("sniff 失败（忽略）：%s → %s", adapter.name, exc)
                continue

        generic = self._by_name.get("generic")
        if generic is not None:
            return generic
        raise ParseError("暂不支持该文件类型，请检查是否为 CSV 或 xlsx 账单导出文件")


def default_registry() -> ParserRegistry:
    """注册 A 线交付的全部适配器。

    合稿 M2 只需把 ``api/deps.get_parser_registry`` 从 Fake 切到本函数，业务代码零改动。
    A 线未合稿时返回空注册表（不报错），首个上传请求会得到可读的 ``E1003``，
    而不是启动期 ImportError —— 并行开发期这一点比"快速失败"更重要。
    """
    registry = ParserRegistry()
    for module_name, class_name in _BUILTIN_ADAPTERS:
        try:
            module = importlib.import_module(f"{__name__.rsplit('.', 1)[0]}.{module_name}")
        except ImportError:
            _logger.debug("适配器模块未就绪：%s", module_name)
            continue
        factory = getattr(module, class_name, None)
        if factory is None:
            _logger.warning("适配器模块 %s 缺少类 %s", module_name, class_name)
            continue
        registry.register(factory())
    if not registry.names():
        _logger.warning("未注册任何解析适配器：A 线（解析内核）尚未合稿")
    return registry


__all__ = ["ParserRegistry", "default_registry"]
