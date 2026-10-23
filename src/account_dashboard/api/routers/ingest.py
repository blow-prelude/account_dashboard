"""入库路由（SDD §6.2.2，C3-A 的两个端点）。

路由只做三件事：**取参数 → 调服务 → 包统一响应**。所有业务判断都在
``IngestService`` 里，这样接口层不会长出第二套规则。

错误码契约（前端 ``pages/import.js`` 的 catch 分支依赖它）：

* ``409 E2002`` —— 批次状态冲突（非 ``prechecked`` 或重复确认）；
* ``500 E3001`` —— 入库事务失败（已回滚，可重试）；
* ``507 E4001`` —— 磁盘空间不足；
* ``200`` + ``files_deleted=false`` —— 数据已提交但文件没删掉（D-7，**不是** 409）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from account_dashboard.api.deps import get_ingest_service
from account_dashboard.api.response import ApiResponse, ok
from account_dashboard.models.ingest import IngestReportDetailDTO, IngestReportDTO
from account_dashboard.services.ingest_service import IngestService

router = APIRouter(prefix="/api/v1/staging", tags=["ingest"])


@router.post("/batches/{batch_id}/confirm", response_model=ApiResponse[IngestReportDTO])
def confirm_batch(
    batch_id: str,
    service: IngestService = Depends(get_ingest_service),
) -> ApiResponse[IngestReportDTO]:
    """确认入库：单事务双写 + 事务外删文件。重复确认 → 409 E2002。"""
    return ok(service.confirm(batch_id))


@router.get("/batches/{batch_id}/report", response_model=ApiResponse[IngestReportDetailDTO])
def get_batch_report(
    batch_id: str,
    include_skipped: bool = Query(default=False),
    service: IngestService = Depends(get_ingest_service),
) -> ApiResponse[IngestReportDetailDTO]:
    """导入报告；``skipped[]`` 明细仅 ``include_skipped=true`` 时返回（D-6）。"""
    return ok(service.report(batch_id, include_skipped=include_skipped))
