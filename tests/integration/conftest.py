"""C2-B（缓冲区与向导）集成用例共用夹具。

核心是 ``api`` fixture：它把 ``ParserRegistry([FakeParser(...)])`` 注入 ``create_app``，
于是整条链路（上传→解析→映射→预检）完全脱离 A 线的真实适配器 ——
这正是 C2-B §1.2 承诺的"可验证的独立性"。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from tests.fakes.fake_parser import FakeParser, make_rows

from account_dashboard.api.app_factory import create_app
from account_dashboard.config import BootstrapConfig
from account_dashboard.infra.parsers.registry import ParserRegistry
from account_dashboard.infra.paths import DataPaths
from account_dashboard.repositories.database import Database


@pytest.fixture
def rows() -> list:
    return make_rows(5)


@pytest.fixture
def parser(rows: list) -> FakeParser:
    return FakeParser(rows, columns=3)


@pytest.fixture
def registry(parser: FakeParser) -> ParserRegistry:
    return ParserRegistry([parser])


@pytest.fixture
def api(
    db: Database,
    paths: DataPaths,
    config: BootstrapConfig,
    registry: ParserRegistry,
) -> Iterator[TestClient]:
    app = create_app(config, database=db, paths=paths, parser_registry=registry)
    with TestClient(app) as client:
        yield client


class StagingFlow:
    """把"上传→映射→预检"这类多步操作收敛成一行，让用例专注断言。"""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def upload(
        self,
        content: bytes = b"fake-bill-payload" * 16,
        *,
        file_name: str = "bill.csv",
        channel: str | None = None,
        content_type: str = "text/csv",
    ) -> Response:
        data: dict[str, Any] = {"channel": channel} if channel else {}
        return self.client.post(
            "/api/v1/staging/batches",
            files={"file": (file_name, content, content_type)},
            data=data,
        )

    def upload_ok(self, **kwargs: Any) -> dict[str, Any]:
        response = self.upload(**kwargs)
        assert response.status_code == 200, response.text
        return response.json()["data"]

    def mapping(self, batch_id: str, **overrides: Any) -> Response:
        payload = {
            "occurred_at": 0,
            "amount": 1,
            "direction": 2,
            "counterparty": 0,
            "item": 1,
            "amount_scale": 1,
        }
        payload.update(overrides)
        return self.client.put(f"/api/v1/staging/batches/{batch_id}/mapping", json=payload)

    def precheck(self, batch_id: str) -> Response:
        return self.client.post(f"/api/v1/staging/batches/{batch_id}/precheck")

    def detail(self, batch_id: str) -> dict[str, Any]:
        response = self.client.get(f"/api/v1/staging/batches/{batch_id}")
        assert response.status_code == 200, response.text
        return response.json()["data"]

    def ready_batch(self) -> dict[str, Any]:
        """上传 + 保存映射 → 状态 ``prechecked``，可直接预检。"""
        batch = self.upload_ok()
        response = self.mapping(batch["id"])
        assert response.status_code == 200, response.text
        return batch


@pytest.fixture
def flow(api: TestClient) -> StagingFlow:
    return StagingFlow(api)


def count_rows(db: Database, table: str) -> int:
    return db.scalar_int(f'SELECT COUNT(*) FROM "{table}"')


def insert_transaction(db: Database, *, fp: str, batch_id: str = "seed-batch") -> None:
    """预置一条主数据层记录，用于模拟"这个指纹已经入过库"。"""
    db.execute(
        'INSERT INTO "transaction" (id, occurred_at, amount_cents, direction, channel, '
        "status, batch_id, row_no, fp, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
        (
            f"txn-{fp[:8]}",
            "2026-06-01T10:00:00",
            1000,
            "expense",
            "other",
            batch_id,
            1,
            fp,
            "2026-06-01T10:00:00",
            "2026-06-01T10:00:00",
        ),
    )


def raw_tables(db: Database) -> list[str]:
    rows = db.query_all("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'raw_%'")
    return [str(row["name"]) for row in rows]


def set_buffer_threshold(db: Database, megabytes: int) -> None:
    db.execute(
        "INSERT INTO setting (key, value, updated_at) VALUES ('buffer_size_threshold_mb', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (json.dumps(megabytes), "2026-10-22T00:00:00"),
    )


def buffer_files(paths: DataPaths) -> list[Path]:
    return [item for item in paths.buffer_dir.iterdir() if item.is_file()]
