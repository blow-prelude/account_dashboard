"""启动链路：六阶段（SDD §2.3）。

顺序不可调：

1. 配置装载 → 退出码 1
2. 数据目录校验 → 2
3. 目录创建 + 日志就位 → 3
4. schema 迁移 → 4
5. 启动对账 → **失败不退出**（只记日志）
6. 单实例锁 + 端口占用 → 5

``lifespan`` 只在被 uvicorn 直接拉起（``uvicorn account_dashboard.main:create_app``）
时才自行执行启动；由 CLI 启动时状态已注入，lifespan 只负责优雅关闭。
"""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from account_dashboard.config import BootstrapConfig, ConfigError, load_bootstrap_config
from account_dashboard.infra.filelock import AlreadyRunning, SingleInstanceLock
from account_dashboard.infra.logger import get_logger, setup_logging
from account_dashboard.infra.path_guard import InvalidDataDir
from account_dashboard.infra.paths import DataPaths, DirCreateError, resolve_paths
from account_dashboard.infra.reconciliation import ReconciliationReport, run_startup_reconciliation
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.schema_migrator import MigrationError, SchemaMigrator

_logger = get_logger("startup")

EXIT_CONFIG = 1
EXIT_DATA_DIR = 2
EXIT_DIR_CREATE = 3
EXIT_MIGRATION = 4
EXIT_LOCK_OR_PORT = 5


class StartupError(Exception):
    def __init__(self, exit_code: int, message: str) -> None:
        self.exit_code = exit_code
        self.message = message
        super().__init__(message)


class PortInUse(Exception):
    pass


@dataclass
class RuntimeState:
    config: BootstrapConfig
    paths: DataPaths
    database: Database
    lock: SingleInstanceLock | None
    reconciliation: ReconciliationReport

    def shutdown(self) -> None:
        self.database.close()
        if self.lock is not None:
            self.lock.release()
        _logger.info("服务已停止，数据目录：%s", self.paths.data_dir)


def startup(
    config: BootstrapConfig | None = None,
    *,
    config_path: Path | None = None,
    acquire_lock: bool = True,
    check_port: bool = True,
) -> RuntimeState:
    try:
        cfg = config or load_bootstrap_config(config_path)
    except ConfigError as exc:
        raise StartupError(EXIT_CONFIG, str(exc)) from exc

    try:
        paths = resolve_paths(cfg)
    except InvalidDataDir as exc:
        raise StartupError(
            EXIT_DATA_DIR, f"数据目录不可用：{exc.reason}，请修改 app.toml 的 data_dir"
        ) from exc

    try:
        paths.ensure_dirs()
    except DirCreateError as exc:
        raise StartupError(EXIT_DIR_CREATE, str(exc)) from exc

    setup_logging(cfg.log_level, paths.logs_dir)
    _logger.info("数据目录：%s", paths.data_dir)

    database = Database(paths.db_file)
    try:
        SchemaMigrator(database).migrate()
    except MigrationError as exc:
        database.close()
        raise StartupError(
            EXIT_MIGRATION, f"数据库升级失败，已回滚；请从 data/backups 恢复（{exc}）"
        ) from exc

    report = ReconciliationReport()
    try:
        report = run_startup_reconciliation(database, paths)
    except Exception as exc:  # 对账失败不阻塞启动
        _logger.warning("启动对账异常，已忽略（数据不受影响）：%s", exc)

    lock: SingleInstanceLock | None = None
    if cfg.single_instance and acquire_lock:
        lock = SingleInstanceLock(paths.data_dir)
        try:
            lock.acquire()
        except AlreadyRunning as exc:
            database.close()
            raise StartupError(EXIT_LOCK_OR_PORT, str(exc)) from exc

    if check_port:
        try:
            ensure_port_available(cfg.host, cfg.port)
        except PortInUse as exc:
            if lock is not None:
                lock.release()
            database.close()
            raise StartupError(EXIT_LOCK_OR_PORT, str(exc)) from exc

    _logger.info("启动完成：http://%s:%s", cfg.host, cfg.port)
    return RuntimeState(
        config=cfg, paths=paths, database=database, lock=lock, reconciliation=report
    )


def ensure_port_available(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError as exc:
            raise PortInUse(f"端口 {port} 已被占用，请在 app.toml 修改 port") from exc


def build_lifespan() -> object:
    """给 uvicorn 用的 lifespan：状态已注入则跳过启动，只负责关闭。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        state: RuntimeState | None = getattr(app.state, "_runtime", None)
        owned = False
        if state is None and getattr(app.state, "database", None) is None:
            state = startup(check_port=False)
            app.state._runtime = state
            app.state.database = state.database
            app.state.paths = state.paths
            app.state.config = state.config
            owned = True
        try:
            yield
        finally:
            if owned and state is not None:
                state.shutdown()

    return lifespan
