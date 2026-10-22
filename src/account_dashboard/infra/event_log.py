"""事件日志接口（PRD 10.4）。

C1 只固定接口与开关语义；落库（``event_log`` 表）在 C5.4 实装，届时
``record`` 的内部实现替换即可，调用方与签名不变。
"""

from __future__ import annotations

from typing import Any

from account_dashboard.infra.logger import get_logger

_logger = get_logger("event")


class EventLogger:
    """``enabled=False`` 时全部丢弃；启用时当前落到应用日志，字段不含金额与对方名称。"""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def record(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        safe = {key: value for key, value in (payload or {}).items() if _is_safe(key)}
        _logger.info("event=%s payload=%s", kind, safe)

    def set_enabled(self, enabled: bool) -> None:
        if enabled == self.enabled:
            return
        self.enabled = enabled
        self.record("event_log.toggled", {"enabled": enabled})


_SAFE_KEYS = frozenset(
    {
        "batch_id",
        "row_no",
        "count",
        "inserted",
        "skipped_dup",
        "pending",
        "duration_ms",
        "enabled",
        "rule_id",
        "scope",
        "updated",
    }
)


def _is_safe(key: str) -> bool:
    return key in _SAFE_KEYS
