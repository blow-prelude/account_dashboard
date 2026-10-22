"""去重预检与强制新增（I-PC-01/02/03，FR-04，EX-21/22）。

三条硬断言：

* **零写入**：预检前后 ``transaction`` 与 ``raw_*`` 计数不变（FR-04 规则 6）；
* **不误判**：同日同额不同对方都标 ``new``（规则 3，用样例里的 29 组组合）；
* **可补救**：override 后翻成 ``new`` 并留痕，撤销后回到 ``dup``（P0-1）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from account_dashboard.api.errors import BusinessRuleError, ErrorCode
from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.infra.paths import DataPaths
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.unit_of_work import UnitOfWork
from account_dashboard.services.import_orchestrator import ImportOrchestrator

PREFIX = "/api/v1/staging"


def _mapping(client: TestClient, batch_id: str) -> dict[str, Any]:
    preview = client.get(f"{PREFIX}/batches/{batch_id}/preview", params={"limit": 1}).json()["data"]
    payload = dict(preview["detected_fields"])
    payload.update({"direction_map": {}, "amount_scale": 1})
    return payload


def prepare(
    client: TestClient,
    upload,
    fixtures_dir: Path,
    name: str = "alipay_sample_gb18030.csv",
) -> str:
    batch = upload(fixtures_dir / name)
    client.put(f"{PREFIX}/batches/{batch['id']}/mapping", json=_mapping(client, batch["id"]))
    return str(batch["id"])


def _counts(db: Database) -> tuple[int, int]:
    raw_tables = db.scalar_int(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'raw_%'"
    )
    return db.scalar_int('SELECT COUNT(*) FROM "transaction"'), raw_tables


def test_precheck_is_read_only(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    """I-PC-01：预检前后业务表计数不变。"""
    batch_id = prepare(client, upload, fixtures_dir)
    before = _counts(db)

    response = client.post(f"{PREFIX}/batches/{batch_id}/precheck")
    assert response.status_code == 200
    data = response.json()["data"]

    assert _counts(db) == before == (0, 0)
    assert data["summary"]["total"] == 669
    assert data["summary"]["new"] == 669
    assert data["summary"]["dup"] == 0
    assert len(data["rows"]) == 669
    assert data["rows"][0]["label"] == "new"

    detail = client.get(f"{PREFIX}/batches/{batch_id}").json()["data"]
    assert detail["status"] == "prechecked"
    assert detail["new_count"] == 669, "预检结果允许写批次计数（缓存，不是业务数据）"
    assert detail["total_rows"] == 669


def test_same_day_same_amount_different_counterparty_are_new(
    client: TestClient, upload, fixtures_dir: Path
) -> None:
    """I-PC-02：样例里 29 组「同日同额不同对方」必须全部标 new。"""
    batch_id = prepare(client, upload, fixtures_dir)
    data = client.post(f"{PREFIX}/batches/{batch_id}/precheck").json()["data"]

    groups: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    for row in data["rows"]:
        key = (row["occurred_at"], row["amount_cents"])
        groups.setdefault(key, []).append(row)

    pairs = [
        rows
        for rows in groups.values()
        if len(rows) == 2 and rows[0]["counterparty"] != rows[1]["counterparty"]
    ]
    assert len(pairs) == 29, f"样例应含 29 组同日同额组合，实际 {len(pairs)} 组"
    for rows in pairs:
        assert {row["label"] for row in rows} == {"new"}
        assert rows[0]["fingerprint"] != rows[1]["fingerprint"]


def _insert_transaction(db: Database, row: dict[str, Any]) -> None:
    db.execute(
        'INSERT INTO "transaction"(id, occurred_at, amount_cents, direction, channel, batch_id, '
        "row_no, fp, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "txn-" + str(row["row_no"]),
            row["occurred_at"],
            row["amount_cents"],
            row["direction"],
            "alipay",
            "batch-old",
            row["row_no"],
            row["fingerprint"],
            "2026-10-22T10:00:00",
            "2026-10-22T10:00:00",
        ),
    )


def test_dup_detection_and_override_flip(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    """I-PC-03：命中 → dup；override 后翻 new 且留痕；撤销后回 dup。"""
    batch_id = prepare(client, upload, fixtures_dir)
    first = client.post(f"{PREFIX}/batches/{batch_id}/precheck").json()["data"]
    target = first["rows"][7]
    _insert_transaction(db, target)

    second = client.post(f"{PREFIX}/batches/{batch_id}/precheck").json()["data"]
    labels = {row["row_no"]: row for row in second["rows"]}
    assert labels[target["row_no"]]["label"] == "dup"
    assert second["summary"]["dup"] == 1
    assert second["summary"]["new"] == 668

    created = client.post(
        f"{PREFIX}/batches/{batch_id}/overrides",
        json={"row_no": target["row_no"], "reason": "确认为独立消费", "note": "小票已核对"},
    )
    assert created.status_code == 200
    assert created.json()["data"]["reason"] == "确认为独立消费"

    third = client.post(f"{PREFIX}/batches/{batch_id}/precheck").json()["data"]
    flipped = {row["row_no"]: row for row in third["rows"]}[target["row_no"]]
    assert flipped["label"] == "new"
    assert flipped["override"] is True
    assert third["summary"]["dup"] == 0

    marked = db.query_one(
        "SELECT reason, note FROM override_mark WHERE batch_id=? AND row_no=?",
        (batch_id, target["row_no"]),
    )
    assert marked is not None and marked["reason"] == "确认为独立消费"

    removed = client.delete(f"{PREFIX}/batches/{batch_id}/overrides/{target['row_no']}")
    assert removed.status_code == 200
    assert removed.json()["data"]["removed"] is True

    fourth = client.post(f"{PREFIX}/batches/{batch_id}/precheck").json()["data"]
    assert {row["row_no"]: row for row in fourth["rows"]}[target["row_no"]]["label"] == "dup"


def test_override_rejects_invalid_row(client: TestClient, upload, fixtures_dir: Path) -> None:
    batch_id = prepare(client, upload, fixtures_dir)
    response = client.post(
        f"{PREFIX}/batches/{batch_id}/overrides", json={"row_no": 99999, "reason": "x"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "E1008"


def test_pending_manual_rows_not_compared(
    client: TestClient, upload, tmp_path: Path
) -> None:
    """EX-21：时间/金额解析失败的行标 pending_manual，不参与比对也不是 dup。"""
    target = tmp_path / "bank_sample.csv"
    target.write_text(
        "交易时间,交易对方,商品,收/支,金额\n"
        "2026-10-01 10:00:00,某便利店,矿泉水,支出,abc\n"
        "不是时间,某便利店,面包,支出,12.30\n"
        "2026-10-01 10:00:02,某便利店,面包,支出,12.30\n",
        encoding="utf-8",
    )
    batch = upload(target)
    client.put(f"{PREFIX}/batches/{batch['id']}/mapping", json=_mapping(client, batch["id"]))
    data = client.post(f"{PREFIX}/batches/{batch['id']}/precheck").json()["data"]

    assert data["summary"] == {"total": 3, "new": 1, "dup": 0, "pending_manual": 2}
    labels = {row["row_no"]: row["label"] for row in data["rows"]}
    assert labels == {1: "pending_manual", 2: "pending_manual", 3: "new"}
    assert "人工核对" in data["message"]
    assert data["issues"]["AMOUNT_PARSE"] == 1
    assert data["issues"]["TIME_PARSE"] == 1

    detail = client.get(f"{PREFIX}/batches/{batch['id']}").json()["data"]
    assert detail["pending_count"] == 2


def test_snapshot_written_for_replay(
    client: TestClient,
    upload,
    fixtures_dir: Path,
    db: Database,
    paths: DataPaths,
) -> None:
    """预检成功后写映射快照；``replay`` 能按快照重放（C3/C4 的交接契约）。"""
    batch_id = prepare(client, upload, fixtures_dir)
    data = client.post(f"{PREFIX}/batches/{batch_id}/precheck").json()["data"]

    detail = client.get(f"{PREFIX}/batches/{batch_id}").json()["data"]
    snapshot = detail["mapping_snapshot"]
    assert snapshot["adapter"] == "alipay_csv"
    assert snapshot["header_row_no"] == 23
    assert snapshot["fp_version"] == "v1"
    assert snapshot["column_map"]["amount"] == 6
    assert snapshot["created_at"] == data["snapshot_at"]

    orchestrator = ImportOrchestrator(
        uow=UnitOfWork(db), buffer=BufferFileManager(paths.buffer_dir), database=db
    )
    rows = orchestrator.replay(batch_id)
    assert len(rows) == 669
    assert rows[0].fingerprint == data["rows"][0]["fingerprint"]
    assert rows[-1].row_no == 669


def test_replay_without_snapshot_rejected(db: Database, paths: DataPaths, client) -> None:
    """没有快照就重放 = 口径不明，必须拒绝（E2002），不能"猜一个"映射。"""
    orchestrator = ImportOrchestrator(
        uow=UnitOfWork(db), buffer=BufferFileManager(paths.buffer_dir), database=db
    )
    with pytest.raises(BusinessRuleError) as missing:
        orchestrator.replay("missing-batch")
    assert missing.value.code is ErrorCode.BATCH_NOT_FOUND


def test_precheck_requires_mapping(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv")
    response = client.post(f"{PREFIX}/batches/{batch['id']}/precheck")
    assert response.status_code == 400
    assert response.json()["code"] == "E1007"
    assert _counts(db) == (0, 0)


def test_precheck_twice_is_idempotent(client: TestClient, upload, fixtures_dir: Path) -> None:
    batch_id = prepare(client, upload, fixtures_dir)
    first = client.post(f"{PREFIX}/batches/{batch_id}/precheck").json()["data"]
    second = client.post(f"{PREFIX}/batches/{batch_id}/precheck")
    assert second.status_code == 200
    assert second.json()["data"]["summary"] == first["summary"]


def test_override_requires_reason(client: TestClient, upload, fixtures_dir: Path) -> None:
    batch_id = prepare(client, upload, fixtures_dir)
    response = client.post(
        f"{PREFIX}/batches/{batch_id}/overrides", json={"row_no": 1, "reason": ""}
    )
    assert response.status_code == 422


def test_raw_tables_stay_absent(db: Database) -> None:
    """C2 边界：不建任何 raw 分表（那是 C3 的事）。"""
    tables = {
        row["name"] for row in db.query_all("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert not [name for name in tables if name.startswith("raw_")]
    assert isinstance(db.conn, sqlite3.Connection)
