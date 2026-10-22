"""批次状态机（SDD §5.6 的 C2 子集）。

用**表驱动**而不是 if-else：7 个状态 × 6 个动作要能被一条参数化用例全矩阵覆盖
（U-BG-01），手写分支一定会漏。

C2 只开放 parse / map / precheck / discard 四条动作；``ingest`` / ``confirm`` 明确
留空 —— 任何在 C2 期间出现的入库状态流转都会得到 ``E2002``，这就是「本周期不写
入库逻辑」的代码级保证。
"""

from __future__ import annotations

from account_dashboard.api.errors import BusinessRuleError, ErrorCode
from account_dashboard.models.enums import BatchAction, BatchStatus

ACTIONS: tuple[BatchAction, ...] = (
    BatchAction.PARSE,
    BatchAction.MAP,
    BatchAction.PRECHECK,
    BatchAction.DISCARD,
    BatchAction.INGEST,
    BatchAction.CONFIRM,
)

STATUS_LABELS: dict[BatchStatus, str] = {
    BatchStatus.UPLOADED: "已上传",
    BatchStatus.MAPPED_PENDING: "待映射",
    BatchStatus.PRECHECKED: "待确认",
    BatchStatus.INGESTING: "入库中",
    BatchStatus.INGESTED: "已入库",
    BatchStatus.DISCARDED: "已丢弃",
    BatchStatus.FAILED: "解析失败",
}

ACTION_LABELS: dict[BatchAction, str] = {
    BatchAction.PARSE: "解析",
    BatchAction.MAP: "保存映射",
    BatchAction.PRECHECK: "去重预检",
    BatchAction.DISCARD: "丢弃",
    BatchAction.INGEST: "入库",
    BatchAction.CONFIRM: "确认入库",
}

_MAPPED = frozenset({BatchStatus.MAPPED_PENDING})
_FAILED_OR_READY = frozenset({BatchStatus.MAPPED_PENDING, BatchStatus.FAILED})
_DISCARDABLE = frozenset(
    {
        BatchStatus.UPLOADED,
        BatchStatus.MAPPED_PENDING,
        BatchStatus.PRECHECKED,
        BatchStatus.FAILED,
    }
)

ALLOWED: dict[tuple[BatchStatus, BatchAction], frozenset[BatchStatus]] = {
    # 解析：已上传 / 失败重试 / 待确认重解析
    # 注意：重解析保留 mapped_fields（列没变，不必让用户重映射），
    # 但预检产物（三项计数 + mapping_snapshot）一律作废 —— 见合稿验收 #7 / D-5
    (BatchStatus.UPLOADED, BatchAction.PARSE): _FAILED_OR_READY,
    (BatchStatus.FAILED, BatchAction.PARSE): _FAILED_OR_READY,
    (BatchStatus.PRECHECKED, BatchAction.PARSE): _FAILED_OR_READY,
    # 映射：成功后状态不变（计数更新）；待确认改映射 → 退回待映射，强制重跑预检
    (BatchStatus.MAPPED_PENDING, BatchAction.MAP): _MAPPED,
    (BatchStatus.PRECHECKED, BatchAction.MAP): _MAPPED,
    # EX-03 兜底：表头只命中 4 个核心时转手动映射，允许在 failed 上直接保存映射
    (BatchStatus.FAILED, BatchAction.MAP): _MAPPED,
    # 预检：可重复执行（幂等），结果缓存到批次计数
    (BatchStatus.MAPPED_PENDING, BatchAction.PRECHECK): frozenset({BatchStatus.PRECHECKED}),
    (BatchStatus.PRECHECKED, BatchAction.PRECHECK): frozenset({BatchStatus.PRECHECKED}),
    # 丢弃
    **{
        (status, BatchAction.DISCARD): frozenset({BatchStatus.DISCARDED})
        for status in _DISCARDABLE
    },
    # 入库：C3 才开放（此处留空是刻意的）
}


def targets(status: BatchStatus, action: BatchAction) -> frozenset[BatchStatus]:
    return ALLOWED.get((status, action), frozenset())


def can_transition(status: BatchStatus, action: BatchAction) -> bool:
    return bool(targets(status, action))


def assert_transition(
    status: BatchStatus,
    action: BatchAction,
    *,
    target: BatchStatus | None = None,
) -> None:
    """非法流转一律 ``E2002``，文案告诉用户下一步该做什么。"""
    allowed = targets(status, action)
    if not allowed:
        raise BusinessRuleError(
            ErrorCode.BATCH_STATE_CONFLICT,
            f"批次当前状态为『{STATUS_LABELS[status]}』，不能执行『{ACTION_LABELS[action]}』，"
            "请刷新页面查看最新状态",
            detail={
                "status": str(status),
                "action": str(action),
                "allowed_targets": sorted(str(item) for item in allowed),
            },
        )
    if target is not None and target not in allowed:
        raise BusinessRuleError(
            ErrorCode.BATCH_STATE_CONFLICT,
            f"批次当前状态为『{STATUS_LABELS[status]}』，无法流转到『{STATUS_LABELS[target]}』，"
            "请刷新页面查看最新状态",
            detail={
                "status": str(status),
                "action": str(action),
                "target": str(target),
                "allowed_targets": sorted(str(item) for item in allowed),
            },
        )
