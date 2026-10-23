"""主数据路由（C3 只开 ``trace`` 一个子路径；C4 再开其余）。

``GET /transactions/{id}/trace`` 返回四块（前端 ``pages/raw.js`` 与
``core/tx-drawer.js`` 已按此实现）：主数据 → 来源批次 → raw 原始行 →
入库时的映射快照。缺块的处理见 ``services/trace_service.py``
（batch / raw_record 缺失是 200 + null + WARN，不是 500）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from account_dashboard.api.deps import get_trace_service
from account_dashboard.api.errors import BusinessRuleError, ErrorCode
from account_dashboard.api.response import ApiResponse, ok
from account_dashboard.models.ingest import TraceDTO
from account_dashboard.services.trace_service import TraceService

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])


@router.get("/{transaction_id}/trace", response_model=ApiResponse[TraceDTO])
def trace_transaction(
    transaction_id: str,
    service: TraceService = Depends(get_trace_service),
) -> ApiResponse[TraceDTO]:
    result = service.trace(transaction_id)
    if result is None:
        raise BusinessRuleError(
            ErrorCode.TRANSACTION_NOT_FOUND,
            "这条流水不存在，无法追溯",
            detail={"transaction_id": transaction_id},
        )
    return ok(result)
