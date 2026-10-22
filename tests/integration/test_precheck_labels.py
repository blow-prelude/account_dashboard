"""C2B.5 预检标注三态：``new`` / ``dup`` / ``pending_manual``。

判定顺序不可换（C2-B §4.5）：先判"能不能入库"，再判"是否已入过库"。
缺时间或缺金额的行必须先落 ``pending_manual``，否则它会以 ``new`` 的身份混进入库队列，
C3 写入 ``transaction``（``occurred_at NOT NULL``）时才炸 —— 那时已经晚了（D-3）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.fakes.fake_parser import FakeParser, make_row
from tests.integration.conftest import StagingFlow, insert_transaction


def labels_of(payload: dict) -> dict[int, str]:
    return {row["row_no"]: row["label"] for row in payload["rows"]}


def test_all_new_when_database_is_empty(api: TestClient, flow: StagingFlow) -> None:
    batch = flow.ready_batch()

    payload = flow.precheck(batch["id"]).json()["data"]

    assert payload["summary"] == {"total": 5, "new": 5, "dup": 0, "pending_manual": 0}
    assert set(labels_of(payload).values()) == {"new"}


def test_existing_fingerprint_marks_dup(
    api: TestClient, db, parser: FakeParser, flow: StagingFlow
) -> None:
    target = make_row(2)
    insert_transaction(db, fp=target.fp)
    parser._rows = [make_row(1), target, make_row(3)]  # noqa: SLF001

    batch = flow.ready_batch()
    payload = flow.precheck(batch["id"]).json()["data"]

    assert labels_of(payload) == {1: "new", 2: "dup", 3: "new"}
    assert payload["summary"]["dup"] == 1


def test_invalid_rows_go_pending_manual(
    api: TestClient, parser: FakeParser, flow: StagingFlow
) -> None:
    parser._rows = [  # noqa: SLF001
        make_row(1),
        make_row(2, occurred_at=None, amount_cents=None),
        make_row(3, amount_cents=None),
    ]

    batch = flow.ready_batch()
    payload = flow.precheck(batch["id"]).json()["data"]

    assert labels_of(payload) == {1: "new", 2: "pending_manual", 3: "pending_manual"}
    assert payload["summary"]["pending_manual"] == 2
    assert payload["summary"]["total"] == 3


def test_pending_rows_do_not_pollute_dup_detection(
    api: TestClient, db, parser: FakeParser, flow: StagingFlow
) -> None:
    """``fp is None`` 的行即使库里有同样"空指纹"也不能算 dup。"""
    insert_transaction(db, fp="", batch_id="seed")
    parser._rows = [make_row(1, occurred_at=None)]  # noqa: SLF001

    batch = flow.ready_batch()
    payload = flow.precheck(batch["id"]).json()["data"]

    assert labels_of(payload) == {1: "pending_manual"}


def test_issues_are_exposed_per_row(api: TestClient, parser: FakeParser, flow: StagingFlow) -> None:
    parser._rows = [make_row(1, amount_cents=None)]  # noqa: SLF001

    batch = flow.ready_batch()
    row = flow.precheck(batch["id"]).json()["data"]["rows"][0]

    assert [issue["code"] for issue in row["issues"]] == ["AMOUNT_PARSE"]
    assert row["issues"][0]["field"] == "amount"


def test_summary_is_self_consistent(
    api: TestClient, db, parser: FakeParser, flow: StagingFlow
) -> None:
    insert_transaction(db, fp=make_row(1).fp)
    parser._rows = [  # noqa: SLF001
        make_row(1),
        make_row(2),
        make_row(3, occurred_at=None),
    ]

    batch = flow.ready_batch()
    summary = flow.precheck(batch["id"]).json()["data"]["summary"]

    assert summary["total"] == 3
    assert summary["new"] + summary["dup"] + summary["pending_manual"] == summary["total"]


@pytest.mark.parametrize("bad_row_no", [0, -1, 6, 999])
def test_override_row_no_must_be_in_range(
    api: TestClient, flow: StagingFlow, bad_row_no: int
) -> None:
    batch = flow.ready_batch()

    response = api.post(
        f"/api/v1/staging/batches/{batch['id']}/overrides",
        json={"row_no": bad_row_no, "reason": "确认是同一笔"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "E1008"
