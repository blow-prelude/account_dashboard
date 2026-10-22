"""基座契约用例：UoW 事务、依赖注入、事件日志、静态挂载。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from account_dashboard.api.app_factory import create_app
from account_dashboard.api.deps import get_config, get_database, get_paths, get_uow
from account_dashboard.api.static_mount import mount_spa
from account_dashboard.config import BootstrapConfig
from account_dashboard.infra.event_log import EventLogger
from account_dashboard.infra.paths import DataPaths
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.unit_of_work import UnitOfWork


# ── UnitOfWork ────────────────────────────────────────────────
def test_uow_commits(db: Database) -> None:
    uow = UnitOfWork(db)
    with uow.begin() as tx:
        assert tx.in_transaction is True
        tx.conn.execute(
            "INSERT INTO setting(key, value, updated_at) VALUES ('k','1','2026-10-22T10:00:00')"
        )
    assert uow.in_transaction is False
    assert db.scalar_int("SELECT COUNT(*) FROM setting") == 1


def test_uow_rolls_back_on_error(db: Database) -> None:
    uow = UnitOfWork(db)
    with pytest.raises(RuntimeError), uow.begin() as tx:
        tx.conn.execute(
            "INSERT INTO setting(key, value, updated_at) VALUES ('k','1','2026-10-22T10:00:00')"
        )
        raise RuntimeError("boom")
    assert uow.in_transaction is False
    assert db.scalar_int("SELECT COUNT(*) FROM setting") == 0


def test_uow_rejects_nesting(db: Database) -> None:
    uow = UnitOfWork(db)
    with pytest.raises(RuntimeError, match="不可嵌套"), uow.begin(), uow.begin():
        pass


# ── 依赖注入 ──────────────────────────────────────────────────
def test_deps_resolve_from_app_state(
    db: Database, paths: DataPaths, config: BootstrapConfig
) -> None:
    app = create_app(config, database=db, paths=paths)

    @app.get("/_probe")
    def probe(
        uow: Annotated[UnitOfWork, Depends(get_uow)],
        database: Annotated[Database, Depends(get_database)],
        resolved_paths: Annotated[DataPaths, Depends(get_paths)],
        resolved_config: Annotated[BootstrapConfig, Depends(get_config)],
    ) -> dict[str, object]:
        return {
            "in_tx": uow.in_transaction,
            "same_db": database is db,
            "data_dir": str(resolved_paths.data_dir),
            "port": resolved_config.port,
        }

    with TestClient(app) as client:
        body = client.get("/_probe").json()
    assert body == {
        "in_tx": False,
        "same_db": True,
        "data_dir": str(paths.data_dir),
        "port": config.port,
    }


def test_get_database_requires_startup() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database=None)))
    with pytest.raises(RuntimeError, match="数据库尚未初始化"):
        get_database(request)  # type: ignore[arg-type]


# ── 事件日志 ──────────────────────────────────────────────────
def test_event_log_disabled_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "account_dashboard.infra.event_log._logger.info", lambda *a, **k: calls.append(a)
    )
    EventLogger(enabled=False).record("batch.uploaded", {"batch_id": "b1"})
    assert calls == []


def test_event_log_filters_unsafe_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "account_dashboard.infra.event_log._logger.info", lambda *a, **k: calls.append(a)
    )
    logger = EventLogger(enabled=True)
    logger.record("backup.created", {"count": 1, "counterparty": "某某商店", "amount": 4590})
    assert len(calls) == 1
    payload = calls[0][2]
    assert payload == {"count": 1}, "金额与对方名称不得进入事件日志"


def test_event_log_toggle_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "account_dashboard.infra.event_log._logger.info", lambda *a, **k: calls.append(a)
    )
    logger = EventLogger(enabled=False)
    logger.set_enabled(True)
    assert logger.enabled is True
    assert calls and calls[0][1] == "event_log.toggled"
    assert calls[0][2] == {"enabled": True}


# ── 静态挂载 ──────────────────────────────────────────────────
def test_mount_spa_without_build(tmp_path: Path) -> None:
    assert mount_spa(FastAPI(), tmp_path) is False


def test_mount_spa_serves_index_and_assets(tmp_path: Path) -> None:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (static / "favicon.ico").write_bytes(b"ico")

    app = FastAPI()

    @app.get("/api/v1/ping")
    def ping() -> dict[str, str]:
        return {"ok": "1"}

    assert mount_spa(app, static) is True
    with TestClient(app) as client:
        assert client.get("/").text == "<html>spa</html>"
        assert client.get("/transactions").text == "<html>spa</html>", "history fallback"
        assert client.get("/favicon.ico").content == b"ico"
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/api/v1/ping").json() == {"ok": "1"}
        assert client.get("/api/v1/not-exists").status_code == 404, "API 不被 fallback 吞掉"
