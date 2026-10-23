"""原始库只读浏览（C3-B §5.1；FZ-3 端点，前端 ``pages/raw.js`` 已按此实现）。

三条口径（与 A 线对不上就查空表 / 数字错位）：

* ``/raw/months[].month`` 是 ``"2026_06"``（**无** ``raw_`` 前缀）——
  前端 ``x.month.slice(5)`` 取月份、拼 ``raw_${ym}`` 查表；
* ``{yyyy_mm}`` 正则 ``^\\d{4}_\\d{2}$``，否则 422 ``E1008``；
* 月份表不存在 → **空数组 + ``meta.total=0``**（缺月是常态，不是错误）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from account_dashboard.api.deps import get_raw_browse_service
from account_dashboard.api.errors import BusinessRuleError, ErrorCode
from account_dashboard.api.response import ApiResponse, Page, ok
from account_dashboard.api.validators import validate_month, validate_page
from account_dashboard.models.ingest import RawMonthDTO, RawRecordDetailDTO, RawRecordDTO
from account_dashboard.services.raw_browse_service import RawBrowseService

router = APIRouter(prefix="/api/v1/raw", tags=["raw"])


@router.get("/months", response_model=ApiResponse[list[RawMonthDTO]])
def list_months(
    service: RawBrowseService = Depends(get_raw_browse_service),
) -> ApiResponse[list[RawMonthDTO]]:
    """有数据的月份（降序）；``count`` 与导入报告的 ``monthly`` 逐月相等。"""
    return ok(service.months())


@router.get("/{yyyy_mm}/records", response_model=ApiResponse[Page[RawRecordDTO]])
def list_records(
    yyyy_mm: str,
    page: int = Query(default=1),
    page_size: int = Query(default=50),
    service: RawBrowseService = Depends(get_raw_browse_service),
) -> ApiResponse[Page[RawRecordDTO]]:
    validate_month(yyyy_mm)
    validate_page(page, page_size)
    return ok(service.records(yyyy_mm, page, page_size))


@router.get("/records/{record_id}", response_model=ApiResponse[RawRecordDetailDTO])
def get_record(
    record_id: int,
    service: RawBrowseService = Depends(get_raw_browse_service),
) -> ApiResponse[RawRecordDetailDTO]:
    """详情带 ``raw_payload``（导入原貌，I7）；列表不带（5 万行时 JSON 会爆）。"""
    detail = service.detail(record_id)
    if detail is None:
        raise BusinessRuleError(
            ErrorCode.BATCH_NOT_FOUND,
            "原始记录不存在，可能已被清理",
            detail={"record_id": record_id},
        )
    return ok(detail)
