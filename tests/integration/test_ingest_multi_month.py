"""支付宝样例跨 5 月入库（C3-A §6.1 主用例 + U-IG-01）。

出口断言（一个都不能少）：

* 5 张 raw 表，逐月 **101/136/182/143/107**，``inserted=669``；
* ``monthly`` 之和 == ``inserted``；四数字自洽 ``total == inserted + skipped_dup
  + skipped_invalid``；
* ``transaction`` 只有 ``pending``、``category_*`` 全 ``NULL``（C3 不自创分类）；
* 无数据月份（2025-12）不建表；``mapping_snapshot`` 冻结回写（D-5）；
* 非 ``prechecked`` 确认 → 409 ``E2002`` 且状态不变；重复确认 → 409。
"""

from __future__ import annotations

import json
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

EXPECTED_MONTHLY = {
    "raw_2026_06": 101,
    "raw_2026_07": 136,
    "raw_2026_08": 182,
    "raw_2026_09": 143,
    "raw_2026_10": 107,
}


def _mapping(client: TestClient, batch_id: str) -> dict[str, Any]:
    preview = client.get(f"{PREFIX}/batches/{batch_id}/preview", params={"limit": 1}).json()["data"]
    payload = dict(preview["detected_fields"])
    payload.update({"direction_map": {}, "amount_scale": 1})
    return payload


def prepare(
    client: TestClient, upload, fixtures_dir: Path, name: str = SAMPLE
) -> str:
    batch = upload(fixtures_dir / name)
    client.put(f"{PREFIX}/batches/{batch['id']}/mapping", json=_mapping(client, batch["id"]))
    return str(batch["id"])


def make_service(db: Database, paths: DataPaths) -> IngestService:
    """与 ``api/deps.py`` 的装配保持一致（NullSink 是 A 线开发期默认）。"""
    buffer = BufferFileManager(paths.buffer_dir)
    return IngestService(
        uow=UnitOfWork(db),
        orchestrator=ImportOrchestrator(uow=UnitOfWork(db), buffer=buffer, database=db),
        sink=NullSink(),
        buffer=buffer,
    )


def _raw_table_counts(db: Database) -> dict[str, int]:
    tables = [
        str(row["name"])
        for row in db.query_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'raw_%' "
            "ORDER BY name"
        )
    ]
    return {name: db.scalar_int(f"SELECT COUNT(*) FROM {name}") for name in tables}


def _confirm(client: TestClient, batch_id: str) -> dict[str, Any]:
    response = client.post(f"{PREFIX}/batches/{batch_id}/confirm")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == "OK"
    return dict(body["data"])


def test_confirm_alipay_sample_five_raw_tables(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    """主出口：669 行跨 5 月 → 5 张 raw 表 101/136/182/143/107。"""
    batch_id = prepare(client, upload, fixtures_dir)
    client.post(f"{PREFIX}/batches/{batch_id}/precheck")

    report = _confirm(client, batch_id)

    # ── 四数字 + monthly ──
    assert report["total"] == 669
    assert report["inserted"] == 669
    assert report["skipped_dup"] == 0
    assert report["skipped_invalid"] == 0
    assert report["pending"] == 669
    assert report["monthly"] == EXPECTED_MONTHLY
    assert sum(report["monthly"].values()) == report["inserted"]
    assert report["total"] == (
        report["inserted"] + report["skipped_dup"] + report["skipped_invalid"]
    )
    assert report["batch_id"] == batch_id
    assert report["finished_at"]
    # NullSink：假装删成功（B 线的 CleanupService 上线后这里才是真删除）
    assert report["files_deleted"] is True
    assert report["cleanup_pending"] is False
    assert report["cleanup_id"] is None

    # ── 落库事实 ──
    assert _raw_table_counts(db) == EXPECTED_MONTHLY
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 669
    assert db.scalar_int("SELECT COUNT(*) FROM raw_2026_06") == 101
    # 无数据月份不建表
    assert db.scalar_int(
        "SELECT COUNT(*) FROM sqlite_master WHERE name = 'raw_2025_12'"
    ) == 0

    # ── 批次终态 ──
    detail = client.get(f"{PREFIX}/batches/{batch_id}").json()["data"]
    assert detail["status"] == "ingested"
    assert detail["report"]["inserted"] == 669
    assert detail["report"]["monthly"] == EXPECTED_MONTHLY

    row = db.query_one("SELECT * FROM staging_batch WHERE id = ?", (batch_id,))
    assert row is not None
    assert row["status"] == "ingested"
    assert row["pending_delete_flag"] == 1  # 删除意图（清零归 B 线）
    assert row["committed_at"] == report["finished_at"]
    assert row["ingest_started_at"]
    # D-5：快照在事务内原样回写（内容与预检那份一致，此后只读）
    assert json.loads(str(row["mapping_snapshot"]))["adapter"] == "alipay_csv"
    stored = json.loads(str(row["report_json"]))
    assert stored["total"] == 669 and stored["inserted"] == 669
    assert stored["skipped"] == []


def test_transaction_rows_are_pending_without_category(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    """C3 边界自证：``status`` 只有 ``pending``，``category_*`` 全 NULL（分类归 C4）。"""
    batch_id = prepare(client, upload, fixtures_dir)
    client.post(f"{PREFIX}/batches/{batch_id}/precheck")
    _confirm(client, batch_id)

    statuses = {
        str(row["status"]) for row in db.query_all('SELECT DISTINCT status FROM "transaction"')
    }
    assert statuses == {"pending"}
    nulls = db.scalar_int(
        'SELECT COUNT(*) FROM "transaction" WHERE category_l1 IS NOT NULL '
        "OR category_l2 IS NOT NULL"
    )
    assert nulls == 0
    # (batch_id, row_no) 唯一且与 ParsedRow.row_no 一致（B 线追溯主键，K7）
    dupes = db.scalar_int(
        'SELECT COUNT(*) FROM (SELECT batch_id, row_no FROM "transaction" '
        "GROUP BY batch_id, row_no HAVING COUNT(*) > 1)"
    )
    assert dupes == 0
    assert db.scalar_int(
        'SELECT COUNT(DISTINCT row_no) FROM "transaction" WHERE batch_id = ?', (batch_id,)
    ) == 669


def test_confirm_requires_prechecked_status(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    """U-IG-01：非 prechecked 确认 → 409 E2002，且状态不变、零写入。"""
    batch = upload(fixtures_dir / SAMPLE)  # 上传后自动解析，停在 mapped_pending
    before = client.get(f"{PREFIX}/batches/{batch['id']}").json()["data"]["status"]
    assert before in {"uploaded", "mapped_pending", "failed"}

    response = client.post(f"{PREFIX}/batches/{batch['id']}/confirm")

    assert response.status_code == 409
    assert response.json()["code"] == "E2002"
    detail = client.get(f"{PREFIX}/batches/{batch['id']}").json()["data"]
    assert detail["status"] == before
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 0
    assert _raw_table_counts(db) == {}


def test_confirm_twice_is_rejected(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    """幂等闸门：重复确认 → 409 E2002，数据不翻倍。"""
    batch_id = prepare(client, upload, fixtures_dir)
    client.post(f"{PREFIX}/batches/{batch_id}/precheck")
    _confirm(client, batch_id)

    response = client.post(f"{PREFIX}/batches/{batch_id}/confirm")
    assert response.status_code == 409
    assert response.json()["code"] == "E2002"

    detail = client.get(f"{PREFIX}/batches/{batch_id}").json()["data"]
    assert detail["status"] == "ingested"
    assert db.scalar_int('SELECT COUNT(*) FROM "transaction"') == 669
    assert db.scalar_int(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'raw_%'"
    ) == 5


def test_report_endpoint_and_skipped_flag(
    client: TestClient, upload, fixtures_dir: Path
) -> None:
    """report 端点：``skipped[]`` 仅 ``include_skipped=true`` 时填充。"""
    batch_id = prepare(client, upload, fixtures_dir)
    client.post(f"{PREFIX}/batches/{batch_id}/precheck")

    missing = client.get(f"{PREFIX}/batches/{batch_id}/report")
    assert missing.status_code == 409
    assert missing.json()["code"] == "E2002"

    _confirm(client, batch_id)

    brief = client.get(f"{PREFIX}/batches/{batch_id}/report").json()["data"]
    assert brief["skipped"] == []
    assert brief["inserted"] == 669
    assert brief["monthly"] == EXPECTED_MONTHLY

    detail = client.get(
        f"{PREFIX}/batches/{batch_id}/report", params={"include_skipped": True}
    ).json()["data"]
    assert detail["skipped"] == []
    assert detail["total"] == 669


def test_report_files_deleted_follows_pending_flag(
    client: TestClient, upload, fixtures_dir: Path, db: Database, paths: DataPaths
) -> None:
    """D-7/K4：``files_deleted`` 的唯一事实源是 ``pending_delete_flag``。

    NullSink 不清零 → 读时为 False（文件确实还在）；模拟 B 线清零后 → True。
    """
    batch_id = prepare(client, upload, fixtures_dir)
    client.post(f"{PREFIX}/batches/{batch_id}/precheck")
    _confirm(client, batch_id)

    before = client.get(f"{PREFIX}/batches/{batch_id}/report").json()["data"]
    assert before["files_deleted"] is False
    assert before["cleanup_pending"] is True

    db.execute(
        "UPDATE staging_batch SET pending_delete_flag = 0, deleted_at = ? WHERE id = ?",
        ("2026-10-22T11:00:00", batch_id),
    )
    after = client.get(f"{PREFIX}/batches/{batch_id}/report").json()["data"]
    assert after["files_deleted"] is True
    assert after["cleanup_pending"] is False

    batch_detail = client.get(f"{PREFIX}/batches/{batch_id}").json()["data"]
    assert batch_detail["report"]["files_deleted"] is True


def test_confirm_missing_batch_is_404(
    client: TestClient, upload, fixtures_dir: Path
) -> None:
    response = client.post(f"{PREFIX}/batches/does-not-exist/confirm")
    assert response.status_code == 404
    assert response.json()["code"] == "E2001"
    report = client.get(f"{PREFIX}/batches/does-not-exist/report")
    assert report.status_code == 404
    assert report.json()["code"] == "E2001"


def test_service_level_confirm_matches_http(
    client: TestClient, upload, fixtures_dir: Path, db: Database, paths: DataPaths
) -> None:
    """服务层直调与 HTTP 同口径（供故障注入用例复用同一装配）。"""
    batch_id = prepare(client, upload, fixtures_dir)
    client.post(f"{PREFIX}/batches/{batch_id}/precheck")

    report = make_service(db, paths).confirm(batch_id)
    assert report.inserted == 669
    assert report.monthly == EXPECTED_MONTHLY
    assert report.files_deleted is True
