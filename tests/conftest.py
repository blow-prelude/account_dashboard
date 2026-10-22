"""全局 fixtures（SDD §13.2）：临时数据目录，绝不污染真实 ``data/``。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from account_dashboard.api.app_factory import create_app
from account_dashboard.config import BootstrapConfig
from account_dashboard.infra.paths import DataPaths, resolve_paths
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.schema_migrator import SchemaMigrator


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
