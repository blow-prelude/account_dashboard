"""C2B.5 预检零写入（I-PC-01，FR-04 规则 6）。

自证方式：调用前后各数一次 ``transaction`` / ``raw_*`` / ``staging_batch.total_rows``，
三组数字必须全等。允许变化的是 ``new_count/dup_count/pending_count``（预检结果缓存，
不是数据写入），但 ``total_rows`` 一个都不许动 —— 它描述的是"文件里有多少行"。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.integration.conftest import (
    StagingFlow,
    buffer_files,
    count_rows,
    raw_tables,
)


def snapshot(db, batch_id: str) -> tuple:
    tables = raw_tables(db)
    return (
        count_rows(db, "transaction"),
        tuple((table, count_rows(db, table)) for table in sorted(tables)),
        db.query_one("SELECT total_rows FROM staging_batch WHERE id = ?", (batch_id,))[0],
    )


def test_precheck_is_read_only(api: TestClient, db, flow: StagingFlow, paths) -> None:
    batch = flow.ready_batch()
    before = snapshot(db, batch["id"])
    files_before = sorted(item.name for item in buffer_files(paths))

    response = flow.precheck(batch["id"])

    assert response.status_code == 200
    after = snapshot(db, batch["id"])
    assert before == after, "预检不得写 transaction / raw_*，也不得改 total_rows"
    assert sorted(item.name for item in buffer_files(paths)) == files_before


def test_precheck_updates_counts_only(api: TestClient, db, flow: StagingFlow) -> None:
    batch = flow.ready_batch()

    summary = flow.precheck(batch["id"]).json()["data"]["summary"]
    row = db.query_one(
        "SELECT new_count, dup_count, pending_count, total_rows FROM staging_batch WHERE id = ?",
        (batch["id"],),
    )

    assert (row["new_count"], row["dup_count"], row["pending_count"]) == (
        summary["new"],
        summary["dup"],
        summary["pending_manual"],
    )
    assert row["total_rows"] == 5


def test_precheck_is_idempotent(api: TestClient, flow: StagingFlow) -> None:
    batch = flow.ready_batch()

    first = flow.precheck(batch["id"]).json()["data"]["summary"]
    second = flow.precheck(batch["id"]).json()["data"]["summary"]

    assert first == second
    assert first["total"] == first["new"] + first["dup"] + first["pending_manual"]


def test_precheck_never_creates_raw_tables(api: TestClient, db, flow: StagingFlow) -> None:
    batch = flow.ready_batch()
    flow.precheck(batch["id"])

    assert raw_tables(db) == [], "raw_* 只在 C3 入库事务内产生"
    assert count_rows(db, "transaction") == 0
