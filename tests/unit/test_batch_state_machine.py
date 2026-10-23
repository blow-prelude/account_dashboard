"""批次状态机（U-BG-01，SDD §5.6 / C2 §4.5 / C3-A §4.1）。

7 个状态 × 6 个动作 = 42 组全矩阵参数化：合法的通过，非法的全部 ``E2002``。
C3-A 起 ``ingest`` / ``confirm`` 两列开放（C2 期间它们是全空的，那时的
"closed" 用例已随之替换为 C3 的矩阵断言）。
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


def test_ingest_and_confirm_columns() -> None:
    """C3-A：``ingest`` / ``confirm`` 的合法单元格只有三个，其余全空。"""
    assert batch_guard.targets(BatchStatus.PRECHECKED, BatchAction.CONFIRM) == {
        BatchStatus.INGESTED
    }
    assert batch_guard.targets(BatchStatus.PRECHECKED, BatchAction.INGEST) == {
        BatchStatus.INGESTING
    }
    # 第二跳只在内存里校验（ingesting 在库里查不到，D-8），但必须存在于矩阵
    assert batch_guard.targets(BatchStatus.INGESTING, BatchAction.INGEST) == {
        BatchStatus.INGESTED
    }
    closed = [s for s in STATUSES if s not in (BatchStatus.PRECHECKED, BatchStatus.INGESTING)]
    for status in closed:
        for action in (BatchAction.INGEST, BatchAction.CONFIRM):
            assert not batch_guard.can_transition(status, action), f"{status} × {action} 应为空"


def test_confirm_on_terminal_states_rejected() -> None:
    """``ingested`` / ``discarded`` / ``failed`` 上 confirm 全 ``E2002``。"""
    for status in (BatchStatus.INGESTED, BatchStatus.DISCARDED, BatchStatus.FAILED):
        with pytest.raises(BusinessRuleError) as excinfo:
            batch_guard.assert_transition(status, BatchAction.CONFIRM)
        assert excinfo.value.code.value == "E2002"


def test_terminal_states_accept_nothing() -> None:
    for status in (BatchStatus.INGESTED, BatchStatus.DISCARDED):
        for action in ACTIONS:
            assert not batch_guard.can_transition(status, action)


def test_ingesting_is_transient_but_in_matrix() -> None:
    """``ingesting`` 是事务内瞬态：对外只认 INGEST 第二跳，其他动作一律拒绝。"""
    for action in ACTIONS:
        expected = action is BatchAction.INGEST
        assert batch_guard.can_transition(BatchStatus.INGESTING, action) is expected


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
