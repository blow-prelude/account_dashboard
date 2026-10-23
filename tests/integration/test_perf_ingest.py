"""669 行入库性能（C3-A §6.1：< 1.5s）。

口径：``IngestService.confirm`` 一次完整调用（重放 + 二次去重 + 建 5 表 +
双写 1338 行 + 报告），``perf_counter`` 计时。不含上传与预检。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.infra.paths import DataPaths
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.unit_of_work import UnitOfWork
from account_dashboard.services.import_orchestrator import ImportOrchestrator
from account_dashboard.services.ingest_ports import NullSink
from account_dashboard.services.ingest_service import IngestService

PREFIX = "/api/v1/staging"
SAMPLE = "alipay_sample_gb18030.csv"


def _mapping(client: TestClient, batch_id: str) -> dict[str, Any]:
    preview = client.get(f"{PREFIX}/batches/{batch_id}/preview", params={"limit": 1}).json()["data"]
    payload = dict(preview["detected_fields"])
    payload.update({"direction_map": {}, "amount_scale": 1})
    return payload


def test_ingest_669_rows_under_1_5_seconds(
    client: TestClient, upload, fixtures_dir: Path, db: Database, paths: DataPaths
) -> None:
    batch = upload(fixtures_dir / SAMPLE)
    batch_id = str(batch["id"])
    client.put(f"{PREFIX}/batches/{batch_id}/mapping", json=_mapping(client, batch_id))
    client.post(f"{PREFIX}/batches/{batch_id}/precheck")

    buffer = BufferFileManager(paths.buffer_dir)
    service = IngestService(
        uow=UnitOfWork(db),
        orchestrator=ImportOrchestrator(uow=UnitOfWork(db), buffer=buffer, database=db),
        sink=NullSink(),
        buffer=buffer,
    )

    start = time.perf_counter()
    report = service.confirm(batch_id)
    elapsed = time.perf_counter() - start

    assert report.inserted == 669
    assert elapsed < 1.5, f"入库耗时 {elapsed:.3f}s，超过 1.5s 预算"
