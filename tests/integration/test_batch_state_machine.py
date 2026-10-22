"""C2B.2 批次状态机：7 状态 × 4 动作全矩阵（28 格全覆盖）。

矩阵的唯一来源是 ``models/staging.TRANSITIONS``；本用例的作用不是"再抄一遍表"，
而是**锁住边界**：任何一格被改动都会让参数化 id 直接报出是哪个 (状态, 动作) 变了。

D-1 的两条额外断言（矩阵优先）：
* ``PUT /mapping`` 成功即 ``prechecked``；
* 在 ``mapped_pending`` 上 precheck → 409，文案「请先确认字段映射」。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.integration.conftest import StagingFlow

from account_dashboard.api.guards import BatchGuard
from account_dashboard.errors import BusinessRuleError, ErrorCode
from account_dashboard.models.staging import (
    BATCH_STATES,
    C2_ACTIONS,
    STATUS_LABELS,
    TRANSITIONS,
    assert_transition,
)


@pytest.mark.parametrize("status", BATCH_STATES)
@pytest.mark.parametrize("action", C2_ACTIONS)
def test_transition_matrix(status: str, action: str) -> None:
    allowed = (status, action) in TRANSITIONS
    if allowed:
        assert_transition(status, action)  # 不抛即通过
        return

    with pytest.raises(BusinessRuleError) as excinfo:
        assert_transition(status, action)

    assert excinfo.value.code is ErrorCode.BATCH_STATE_CONFLICT
    assert excinfo.value.http_status == 409
    assert STATUS_LABELS[status] in excinfo.value.message


def test_matrix_covers_28_cells() -> None:
    assert len(BATCH_STATES) == 7
    assert len(C2_ACTIONS) == 4, "C2 只实现 parse/map/precheck/discard"
    assert len(BATCH_STATES) * len(C2_ACTIONS) == 28
    assert all(target in BATCH_STATES for targets in TRANSITIONS.values() for target in targets)


def test_target_must_be_reachable() -> None:
    with pytest.raises(BusinessRuleError):
        assert_transition("uploaded", "parse", "ingested")


def test_guard_facade_matches_matrix() -> None:
    with pytest.raises(BusinessRuleError):
        BatchGuard.assert_transition("discarded", "parse")
    BatchGuard.assert_transition("prechecked", "precheck")


def test_confirm_is_left_to_c3() -> None:
    with pytest.raises(BusinessRuleError) as excinfo:
        assert_transition("prechecked", "confirm")
    assert excinfo.value.code is ErrorCode.BATCH_STATE_CONFLICT
    with pytest.raises(NotImplementedError):
        BatchGuard.try_enter_ingesting()


def test_all_seven_statuses_round_trip(db) -> None:
    """7 个状态字面量都能写库并原样读回（DDL 的 CHECK 与模型字面量必须一致）。"""
    from account_dashboard.repositories.staging_repo import StagingRepo

    repo = StagingRepo(db.conn)
    for status in BATCH_STATES:
        db.execute(
            "INSERT INTO staging_batch (id, file_name, stored_name, file_size, channel, status, "
            "created_at, updated_at) VALUES (?, ?, ?, 1, 'other', ?, ?, ?)",
            (
                f"batch-{status}",
                "a.csv",
                f"{status}.csv",
                status,
                "2026-10-22T00:00:00",
                "2026-10-22T00:00:00",
            ),
        )
        assert repo.get(f"batch-{status}")["status"] == status


# ── 端点级边界（矩阵之外的真实调用路径）──────────────────────


def test_upload_lands_on_mapped_pending(flow: StagingFlow) -> None:
    batch = flow.upload_ok()
    assert batch["status"] == "mapped_pending"
    assert batch["total_rows"] == 5


def test_precheck_on_mapped_pending_is_conflict(flow: StagingFlow) -> None:
    batch = flow.upload_ok()

    response = flow.precheck(batch["id"])

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == ErrorCode.BATCH_STATE_CONFLICT.value
    assert "请先确认字段映射" in body["message"]


def test_mapping_moves_to_prechecked(api: TestClient, flow: StagingFlow) -> None:
    batch = flow.upload_ok()

    response = flow.mapping(batch["id"])

    assert response.status_code == 200
    assert response.json()["data"]["batch"]["status"] == "prechecked"
    assert flow.detail(batch["id"])["mapped_fields"]["occurred_at"] == 0


def test_reparse_from_prechecked_goes_back_to_mapped_pending(
    api: TestClient, flow: StagingFlow
) -> None:
    batch = flow.ready_batch()

    response = api.post(f"/api/v1/staging/batches/{batch['id']}/parse")

    assert response.status_code == 200
    assert response.json()["data"]["batch"]["status"] == "mapped_pending"


def test_discarded_batch_rejects_everything(api: TestClient, flow: StagingFlow) -> None:
    batch = flow.upload_ok()
    assert api.post(f"/api/v1/staging/batches/{batch['id']}/discard").status_code == 200

    for method, path in (
        ("post", f"/api/v1/staging/batches/{batch['id']}/parse"),
        ("post", f"/api/v1/staging/batches/{batch['id']}/precheck"),
        ("post", f"/api/v1/staging/batches/{batch['id']}/discard"),
    ):
        response = getattr(api, method)(path)
        assert response.status_code == 409, path
        assert response.json()["code"] == ErrorCode.BATCH_STATE_CONFLICT.value


def test_unknown_batch_is_404(api: TestClient) -> None:
    response = api.get("/api/v1/staging/batches/not-a-batch")

    assert response.status_code == 404
    assert response.json()["code"] == ErrorCode.BATCH_NOT_FOUND.value
