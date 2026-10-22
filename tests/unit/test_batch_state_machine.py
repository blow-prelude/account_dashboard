"""批次状态机（U-BG-01，SDD §5.6 / C2 §4.5）。

7 个状态 × 6 个动作 = 42 组全矩阵参数化：合法的通过，非法的全部 ``E2002``。
这条用例同时是「C2 不写入库逻辑」的自证：``ingest`` / ``confirm`` 在任何状态下都是空的。
"""

from __future__ import annotations

import pytest

from account_dashboard.api.errors import BusinessRuleError
from account_dashboard.models.enums import BatchAction, BatchStatus
from account_dashboard.services import batch_guard

STATUSES = list(BatchStatus)
ACTIONS = list(BatchAction)


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("action", ACTIONS)
def test_transition_matrix(status: BatchStatus, action: BatchAction) -> None:
    expected_allowed = (status, action) in batch_guard.ALLOWED
    assert batch_guard.can_transition(status, action) is expected_allowed

    if expected_allowed:
        batch_guard.assert_transition(status, action)
        for target in batch_guard.targets(status, action):
            batch_guard.assert_transition(status, action, target=target)
    else:
        with pytest.raises(BusinessRuleError) as excinfo:
            batch_guard.assert_transition(status, action)
        assert excinfo.value.code.value == "E2002"
        assert excinfo.value.http_status == 409


def test_ingest_is_closed_in_c2() -> None:
    for status in STATUSES:
        assert not batch_guard.can_transition(status, BatchAction.INGEST)
        assert not batch_guard.can_transition(status, BatchAction.CONFIRM)


def test_terminal_states_accept_nothing() -> None:
    for status in (BatchStatus.INGESTED, BatchStatus.DISCARDED, BatchStatus.INGESTING):
        for action in ACTIONS:
            assert not batch_guard.can_transition(status, action)


def test_parse_may_fail_only_from_parseable_states() -> None:
    for status in (BatchStatus.UPLOADED, BatchStatus.FAILED, BatchStatus.PRECHECKED):
        assert BatchStatus.FAILED in batch_guard.targets(status, BatchAction.PARSE)
    assert not batch_guard.can_transition(BatchStatus.MAPPED_PENDING, BatchAction.PARSE)


def test_mapping_after_precheck_falls_back() -> None:
    """映射改了就退回待映射，强制重跑预检（EX-22 前置防护）。"""
    assert batch_guard.targets(BatchStatus.PRECHECKED, BatchAction.MAP) == {
        BatchStatus.MAPPED_PENDING
    }


def test_error_message_is_actionable() -> None:
    with pytest.raises(BusinessRuleError) as excinfo:
        batch_guard.assert_transition(BatchStatus.INGESTED, BatchAction.PARSE)
    message = excinfo.value.message
    assert "已入库" in message
    assert "解析" in message
    assert "刷新" in message
