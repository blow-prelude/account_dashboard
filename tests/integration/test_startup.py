"""启动链路与退出码用例（SDD §2.3）。

退出码是面向非技术用户的契约：1 配置 / 2 目录校验 / 3 目录创建 / 4 迁移 / 5 锁或端口。
每个码都要有一次可复现的证据，不能只靠手工试。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import account_dashboard.main as main_module
from account_dashboard.api.app_factory import create_app
from account_dashboard.cli import main
from account_dashboard.config import BootstrapConfig
from account_dashboard.infra.paths import DataPaths, DirCreateError, resolve_paths
from account_dashboard.infra.reconciliation import ReconciliationReport
from account_dashboard.main import (
    EXIT_CONFIG,
    EXIT_DATA_DIR,
    EXIT_DIR_CREATE,
    EXIT_LOCK_OR_PORT,
    EXIT_MIGRATION,
    PortInUse,
    RuntimeState,
    StartupError,
    build_lifespan,
    startup,
)
from account_dashboard.repositories.database import Database


def write_config(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_exit_1_on_broken_toml(tmp_path: Path) -> None:
    config = write_config(tmp_path / "app.toml", "[server]\nport = = 1\n")
    assert main(["init-db", "--config", str(config)]) == EXIT_CONFIG


def test_exit_2_on_invalid_data_dir(tmp_path: Path) -> None:
    system_path = "C:/Windows" if os.name == "nt" else "/etc"
    config = write_config(
        tmp_path / "app.toml",
        f'[server]\nport = 8791\n[paths]\ndata_dir = "{system_path}"\n',
    )
    assert main(["init-db", "--config", str(config)]) == EXIT_DATA_DIR


def test_exit_3_on_dir_create_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = BootstrapConfig(data_dir=str(tmp_path / "data"))

    def boom(self: DataPaths) -> None:
        raise DirCreateError("无法创建目录，请检查权限")

    monkeypatch.setattr(DataPaths, "ensure_dirs", boom)
    with pytest.raises(StartupError) as excinfo:
        startup(config, acquire_lock=False, check_port=False)
    assert excinfo.value.exit_code == EXIT_DIR_CREATE


def test_exit_4_on_migration_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = BootstrapConfig(data_dir=str(tmp_path / "data"))

    def boom(self: object) -> int:
        from account_dashboard.repositories.schema_migrator import MigrationError

        raise MigrationError("迁移失败")

    monkeypatch.setattr(
        "account_dashboard.main.SchemaMigrator.migrate", boom
    )
    with pytest.raises(StartupError) as excinfo:
        startup(config, acquire_lock=False, check_port=False)
    assert excinfo.value.exit_code == EXIT_MIGRATION


def test_exit_5_on_port_in_use(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = BootstrapConfig(data_dir=str(tmp_path / "data"))

    def boom(host: str, port: int) -> None:
        raise PortInUse(f"端口 {port} 已被占用，请在 app.toml 修改 port")

    monkeypatch.setattr(main_module, "ensure_port_available", boom)
    with pytest.raises(StartupError) as excinfo:
        startup(config)
    assert excinfo.value.exit_code == EXIT_LOCK_OR_PORT


def test_exit_5_on_second_instance(tmp_path: Path) -> None:
    config = BootstrapConfig(data_dir=str(tmp_path / "data"))
    first = startup(config, check_port=False)
    try:
        with pytest.raises(StartupError) as excinfo:
            startup(config, check_port=False)
        assert excinfo.value.exit_code == EXIT_LOCK_OR_PORT
        assert "已有实例" in excinfo.value.message
    finally:
        first.shutdown()


def test_lifespan_does_not_restart_when_state_injected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI 已完成启动时，lifespan 不能再抢一次文件锁（真实踩过的坑）。"""
    config = BootstrapConfig(data_dir=str(tmp_path / "data"))
    paths = resolve_paths(config)
    paths.ensure_dirs()
    database = Database(paths.db_file)
    from account_dashboard.repositories.schema_migrator import SchemaMigrator

    SchemaMigrator(database).migrate()
    state = RuntimeState(config, paths, database, None, ReconciliationReport())

    def fail_startup(*args: object, **kwargs: object) -> None:
        raise AssertionError("lifespan 不应重复执行 startup")

    monkeypatch.setattr(main_module, "startup", fail_startup)
    app = create_app(
        config, database=database, paths=paths, lifespan=build_lifespan()  # type: ignore[arg-type]
    )
    app.state._runtime = state
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["data"]["db_ok"] is True
    database.close()


def test_health_degraded_without_database(tmp_path: Path) -> None:
    config = BootstrapConfig(data_dir=str(tmp_path / "data"))
    paths = resolve_paths(config)
    paths.ensure_dirs()
    app = create_app(config, database=None, paths=paths)
    with TestClient(app) as client:
        data = client.get("/api/v1/health").json()["data"]
    assert data["db_ok"] is False
    assert data["status"] == "degraded"
