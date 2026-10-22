"""健康检查（SDD §6.2.1）。

启动脚本与前端都靠它判活，因此：

* 不查业务数据，只做存活探测与两个计数；
* 任何一项失败都不能 500 —— 返回 ``db_ok=false`` 让调用方决定，而不是让探活本身崩掉。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from account_dashboard.api.response import ApiResponse, ok
from account_dashboard.models.common import HealthDTO
from account_dashboard.services.health_service import HealthService

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", response_model=ApiResponse[HealthDTO])
def health(request: Request) -> ApiResponse[HealthDTO]:
    return ok(HealthService.from_app_state(request.app.state).snapshot())
