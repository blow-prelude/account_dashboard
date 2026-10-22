"""引导配置装载（文件级配置，SDD §11.1 ~ §11.3）。

只负责「读文件 + 校验形状」，不做路径合法化（那是 ``infra.path_guard`` 的职责），
也不碰数据库（业务设置存在 ``setting`` 表，属于 C5）。
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_LOG_LEVEL = "INFO"

ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})
ALLOWED_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})
PORT_RANGE = (1024, 65535)

_LINE_RE = re.compile(r"line\s+(\d+)", re.IGNORECASE)
CONFIG_ENV_VAR = "ACCOUNT_DASHBOARD_CONFIG"


class ConfigError(Exception):
    """配置文件语法或取值非法。对应启动退出码 1。"""

    def __init__(self, message: str, line: int | None = None) -> None:
        self.line = line
        self.reason = message
        super().__init__(f"配置文件第 {line} 行格式错误：{message}" if line else message)


@dataclass(frozen=True, slots=True)
class BootstrapConfig:
    """``app.toml`` 的强类型视图。"""

    data_dir: str = ""
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    open_browser: bool = True
    single_instance: bool = True
    log_level: str = DEFAULT_LOG_LEVEL
    source: Path | None = None


def default_config_path() -> Path:
    """配置文件位置：环境变量优先，其次当前工作目录下的 ``app.toml``。"""
    override = os.environ.get(CONFIG_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.cwd() / "app.toml"


def load_bootstrap_config(path: Path | None = None) -> BootstrapConfig:
    """装载配置；文件不存在时全部使用默认值（不创建文件）。"""
    config_path = path or default_config_path()
    if not config_path.exists():
        return BootstrapConfig(source=None)

    try:
        raw_bytes = config_path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {config_path}：{exc}") from exc

    try:
        data = tomllib.loads(raw_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ConfigError(f"配置文件必须是 UTF-8 编码：{config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(exc.args[0] if exc.args else str(exc), _extract_line(exc)) from exc

    server = _table(data, "server")
    paths = _table(data, "paths")
    logging_table = _table(data, "logging")

    host = _as_str(server, "host", DEFAULT_HOST).strip().lower()
    if host not in ALLOWED_HOSTS:
        raise ConfigError("server.host 只允许 127.0.0.1 或 localhost，后端不对外监听")

    port = _as_int(server, "port", DEFAULT_PORT)
    if not PORT_RANGE[0] <= port <= PORT_RANGE[1]:
        raise ConfigError(f"server.port 必须在 {PORT_RANGE[0]}~{PORT_RANGE[1]} 之间")

    log_level = _as_str(logging_table, "level", DEFAULT_LOG_LEVEL).strip().upper()
    if log_level not in ALLOWED_LOG_LEVELS:
        raise ConfigError("logging.level 只允许 DEBUG / INFO / WARNING / ERROR")

    return BootstrapConfig(
        data_dir=_as_str(paths, "data_dir", "").strip(),
        host=host,
        port=port,
        open_browser=_as_bool(server, "open_browser", True),
        single_instance=_as_bool(server, "single_instance", True),
        log_level=log_level,
        source=config_path,
    )


def _extract_line(exc: Exception) -> int | None:
    match = _LINE_RE.search(str(exc))
    return int(match.group(1)) if match else None


def _table(data: dict[str, object], name: str) -> dict[str, object]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] 必须是一个表（section）")
    return value


def _as_str(table: dict[str, object], key: str, default: str) -> str:
    value = table.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{key} 必须是字符串")
    return value


def _as_int(table: dict[str, object], key: str, default: int) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} 必须是整数")
    return value


def _as_bool(table: dict[str, object], key: str, default: bool) -> bool:
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key} 必须是 true 或 false")
    return value
