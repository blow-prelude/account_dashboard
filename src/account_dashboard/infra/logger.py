"""应用日志（SDD §11.7 / §12.3）。

两条硬规则：

1. 日志只记聚合与标识，不记金额明细；
2. 即使调用方误把对方名称/文件名塞进 ``key=value``，脱敏过滤器也会截断。
"""

from __future__ import annotations

import logging
import re
import sys
from contextlib import suppress
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "account_dashboard"
LOG_FILE_NAME = "app.log"
MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5

_SENSITIVE_PATTERN = re.compile(
    r"(?i)\b(counterparty|item|file_name|merchant|merchant_name)\s*[=:]\s*([^\s,;&]+)"
)


def mask_value(value: str) -> str:
    """保留前 2 个字符，其余打码。"""
    if len(value) <= 2:
        return "***"
    return f"{value[:2]}***"


class RedactFilter(logging.Filter):
    """把 ``counterparty=某某商店`` 变成 ``counterparty=某某***``。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - 防御性分支
            return True
        redacted = _SENSITIVE_PATTERN.sub(
            lambda m: f"{m.group(1)}={mask_value(m.group(2))}", message
        )
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(level: str = "INFO", logs_dir: Path | None = None) -> logging.Logger:
    """配置根应用日志；重复调用是幂等的（清空旧 handler 后重建）。"""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    redactor = RedactFilter()

    _reconfigure_stream(sys.stdout)
    stream = logging.StreamHandler(stream=sys.stdout)
    stream.setFormatter(formatter)
    stream.addFilter(redactor)
    logger.addHandler(stream)

    if logs_dir is not None:
        logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            logs_dir / LOG_FILE_NAME,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redactor)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def _reconfigure_stream(stream: object) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        with suppress(OSError, ValueError):  # 非标准流（如重定向管道）
            reconfigure(encoding="utf-8")
