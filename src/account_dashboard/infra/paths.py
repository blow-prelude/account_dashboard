"""运行时数据目录布局（SDD §3.1 / §3.6）。

代码与数据严格分离：``data_dir`` 由引导配置决定，库、缓冲区、备份、日志都在其下，
绝不进入 wheel，也不进入 git。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from account_dashboard.config import BootstrapConfig
from account_dashboard.infra.path_guard import validate_data_dir

APP_DIR_NAME = "AccountDashboard"


class DirCreateError(Exception):
    """目录创建失败（权限不足等）。映射为启动退出码 3。"""


@dataclass(frozen=True, slots=True)
class DataPaths:
    """四个落点的唯一来源。"""

    data_dir: Path

    @property
    def db_dir(self) -> Path:
        return self.data_dir / "db"

    @property
    def db_file(self) -> Path:
        return self.db_dir / "ledger.db"

    @property
    def buffer_dir(self) -> Path:
        return self.data_dir / "buffer"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def lock_file(self) -> Path:
        return self.data_dir / "instance.lock"

    def required_dirs(self) -> tuple[Path, ...]:
        return (self.db_dir, self.buffer_dir, self.backups_dir, self.logs_dir)

    def ensure_dirs(self) -> None:
        for directory in self.required_dirs():
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise DirCreateError(f"无法创建目录 {directory}，请检查权限") from exc


def default_data_dir() -> Path:
    """未配置 ``data_dir`` 时的系统用户数据目录。"""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_DIR_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "account-dashboard"
    return Path.home() / ".local" / "share" / "account-dashboard"


def resolve_paths(config: BootstrapConfig) -> DataPaths:
    """把配置解析成 :class:`DataPaths`，显式路径必须先过 ``path_guard``。"""
    raw = config.data_dir.strip()
    resolved = validate_data_dir(raw) if raw else validate_data_dir(default_data_dir())
    return DataPaths(data_dir=resolved)


def static_dir() -> Path:
    """前端产物目录（C5 打进 wheel；开发期不存在则跳过挂载）。"""
    return Path(__file__).resolve().parent.parent / "static"
