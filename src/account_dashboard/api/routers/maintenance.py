"""运维端点（C3-B §5.1）：待清理队列的查看与手动重试。

两个端点，前端 ``pages/buffer.js`` 已按此实现：

* ``GET /maintenance/cleanup?status=pending`` 返回**数组**（不是分页对象）——
  前端直接 ``.map`` 消费；
* ``POST /maintenance/cleanup/{id}/retry`` 幂等：已 ``done`` 的重复重试
  返回当前状态，不报错（用户重复点"重试"不该看到红条）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from account_dashboard.api.deps import get_cleanup_service
from account_dashboard.api.response import ApiResponse, ok
from account_dashboard.models.ingest import CleanupItemDTO
from account_dashboard.services.cleanup_service import CleanupService

router = APIRouter(prefix="/api/v1/maintenance", tags=["maintenance"])


@router.get("/cleanup", response_model=ApiResponse[list[CleanupItemDTO]])
def list_cleanup(
    status: str | None = Query(default=None, description="pending/done/abandoned；缺省返回全部"),
    service: CleanupService = Depends(get_cleanup_service),
) -> ApiResponse[list[CleanupItemDTO]]:
    return ok(service.list_items(status))


@router.post("/cleanup/{cleanup_id}/retry", response_model=ApiResponse[CleanupItemDTO])
def retry_cleanup(
    cleanup_id: str,
    service: CleanupService = Depends(get_cleanup_service),
) -> ApiResponse[CleanupItemDTO]:
    return ok(service.retry(cleanup_id))
