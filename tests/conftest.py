"""全局 fixtures（SDD §13.2）：临时数据目录，绝不污染真实 ``data/``。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from account_dashboard.api.app_factory import create_app
from account_dashboard.config import BootstrapConfig
from account_dashboard.infra.paths import DataPaths, resolve_paths
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.schema_migrator import SchemaMigrator

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
API_PREFIX = "/api/v1"


@pytest.fixture
def config(tmp_path: Path) -> BootstrapConfig:
    return BootstrapConfig(data_dir=str(tmp_path / "data"), host="127.0.0.1", port=8899)


@pytest.fixture
def paths(config: BootstrapConfig) -> DataPaths:
    resolved = resolve_paths(config)
    resolved.ensure_dirs()
    return resolved


@pytest.fixture
def db(paths: DataPaths) -> Iterator[Database]:
    database = Database(paths.db_file)
    SchemaMigrator(database).migrate()
    yield database
    database.close()


@pytest.fixture
def client(db: Database, paths: DataPaths, config: BootstrapConfig) -> Iterator[TestClient]:
    app = create_app(config, database=db, paths=paths)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """C2 的真实样例（结构与统计特征与线上账单一致，内容已脱敏）。"""
    return FIXTURES_DIR


@pytest.fixture
def fresh_client(
    db: Database, paths: DataPaths, config: BootstrapConfig
) -> Iterator[Callable[[], TestClient]]:
    """造一个「刷新页面」等价的新 TestClient —— 验证批次不依赖进程内状态。"""

    def _make() -> TestClient:
        return TestClient(create_app(config, database=db, paths=paths))

    yield _make


@pytest.fixture
def upload(client: TestClient) -> Callable[..., dict[str, Any]]:
    """上传账单并返回 ``BatchDetailDTO``。"""

    def _upload(path: Path, channel: str | None = None, **kwargs: Any) -> dict[str, Any]:
        with path.open("rb") as handle:
            files = {"file": (path.name, handle, "application/octet-stream")}
            data = {"channel": channel} if channel else {}
            response = client.post(
                f"{API_PREFIX}/staging/batches", files=files, data=data, **kwargs
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["code"] == "OK", body
        return dict(body["data"])

    return _upload
