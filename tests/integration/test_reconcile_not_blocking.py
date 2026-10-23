"""对账不阻塞启动（C3-B §4.3 / SDD §2.3）：3 个文件全删失败，服务仍起得来。

阻塞启动反而让用户进不去界面处理 —— 删不掉的文件只影响它自己，
进待清理队列等用户手动重试。``/health`` 仍 200（db 本身是好的）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.helpers.ingest_state import make_ingested_batch

from account_dashboard.api.app_factory import create_app
from account_dashboard.config import BootstrapConfig
from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.infra.paths import resolve_paths
from account_dashboard.main import startup
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.schema_migrator import SchemaMigrator


def test_service_starts_when_all_deletes_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = BootstrapConfig(data_dir=str(tmp_path / "data"), host="127.0.0.1", port=8899)
    paths = resolve_paths(config)
    paths.ensure_dirs()

    # 预置残局：3 个「已入库 + flag=1 + 文件在」的批次
    database = Database(paths.db_file)
    SchemaMigrator(database).migrate()
    for i in range(3):
        stored_name = f"{i:032d}" + ".csv"
        (paths.buffer_dir / stored_name).write_text("x", encoding="utf-8")
        with database.conn:
            make_ingested_batch(
                database.conn,
                batch_id=f"{i:032d}",
                stored_name=stored_name,
                file_name=f"账单{i}.csv",
                pending_delete_flag=1,
            )
    database.close()

    monkeypatch.setattr(BufferFileManager, "delete_with_retry", lambda self, path, **kw: False)

    state = startup(config, acquire_lock=False, check_port=False)
    try:
        assert state.reconciliation.pending_deletes == 3
        assert state.reconciliation.deleted_files == 0
        assert state.reconciliation.enqueued_files == 3

        app = create_app(config, database=state.database, paths=state.paths)
        with TestClient(app) as client:
            response = client.get("/api/v1/health")
        assert response.status_code == 200
        body = response.json()["data"]
        assert body["db_ok"] is True
        assert body["backlog"]["cleanup"] == 3, "删不掉的文件进待清理队列，健康检查可见"
    finally:
        state.shutdown()
