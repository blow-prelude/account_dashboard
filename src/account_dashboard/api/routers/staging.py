"""导入缓冲区路由（FZ-2 冻结，SDD §6.2.2）。

路由只做三件事：**取参数 → 调服务 → 包统一响应**。所有业务判断都在
``ImportOrchestrator`` 里，这样接口层不会长出第二套规则。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from account_dashboard.api.deps import get_cleanup_service, get_orchestrator
from account_dashboard.api.errors import EntryValidationError, ErrorCode
from account_dashboard.api.response import ApiResponse, Page, ok
from account_dashboard.api.validators import (
    validate_declared_size,
    validate_limit,
    validate_page,
    validate_upload_meta,
)
from account_dashboard.models.enums import BatchStatus, Channel
from account_dashboard.models.ingest import OrphanCleanupDTO
from account_dashboard.models.staging import (
    BatchDetailDTO,
    BatchDTO,
    BufferUsageDTO,
    DiscardReq,
    EnsureDirDTO,
    MappingReq,
    MappingResultDTO,
    OrphanCleanupReq,
    OrphanFileDTO,
    OverrideDTO,
    OverrideReq,
    ParseResultDTO,
    PrecheckResultDTO,
    PreviewDTO,
    RemovedDTO,
    TemplateDTO,
    TemplateReq,
)
from account_dashboard.services.cleanup_service import CleanupService
from account_dashboard.services.import_orchestrator import PREVIEW_MAX_LIMIT, ImportOrchestrator

router = APIRouter(prefix="/api/v1/staging", tags=["staging"])


# ── 批次 ────────────────────────────────────────────────────
@router.post("/batches", response_model=ApiResponse[BatchDetailDTO])
async def create_batch(
    file: UploadFile = File(...),
    channel: str | None = Form(default=None),
    orchestrator: ImportOrchestrator = Depends(get_orchestrator),
) -> ApiResponse[BatchDetailDTO]:
    file_name = file.filename or "upload"
    validate_upload_meta(file_name, file.content_type)
    declared_size = int(getattr(file, "size", 0) or 0)
    validate_declared_size(declared_size)
    batch = await orchestrator.create_batch(
        file, file_name, declared_size, _parse_channel(channel)
    )
    return ok(batch)


@router.get("/batches", response_model=ApiResponse[Page[BatchDTO]])
def list_batches(
    status: str | None = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=50),
    orchestrator: ImportOrchestrator = Depends(get_orchestrator),
) -> ApiResponse[Page[BatchDTO]]:
    validate_page(page, page_size)
    return ok(
        orchestrator.list_batches(
            status=_parse_status(status), page=page, page_size=page_size
        )
    )


@router.get("/batches/{batch_id}", response_model=ApiResponse[BatchDetailDTO])
def get_batch(
    batch_id: str,
    orchestrator: ImportOrchestrator = Depends(get_orchestrator),
) -> ApiResponse[BatchDetailDTO]:
    return ok(orchestrator.get_batch(batch_id))


@router.post("/batches/{batch_id}/parse", response_model=ApiResponse[ParseResultDTO])
def parse_batch(
    batch_id: str,
    orchestrator: ImportOrchestrator = Depends(get_orchestrator),
) -> ApiResponse[ParseResultDTO]:
    return ok(orchestrator.parse_batch(batch_id))


@router.get("/batches/{batch_id}/preview", response_model=ApiResponse[PreviewDTO])
def preview_batch(
    batch_id: str,
    limit: int = Query(default=20),
    orchestrator: ImportOrchestrator = Depends(get_orchestrator),
) -> ApiResponse[PreviewDTO]:
    safe_limit = validate_limit(limit, maximum=PREVIEW_MAX_LIMIT)
    return ok(orchestrator.preview(batch_id, safe_limit))


@router.put("/batches/{batch_id}/mapping", response_model=ApiResponse[MappingResultDTO])
def save_mapping(
    batch_id: str,
    payload: MappingReq,
    orchestrator: ImportOrchestrator = Depends(get_orchestrator),
) -> ApiResponse[MappingResultDTO]:
    return ok(orchestrator.apply_mapping(batch_id, payload))


@router.post("/batches/{batch_id}/precheck", response_model=ApiResponse[PrecheckResultDTO])
def precheck_batch(
    batch_id: str,
    orchestrator: ImportOrchestrator = Depends(get_orchestrator),
) -> ApiResponse[PrecheckResultDTO]:
    return ok(orchestrator.run_precheck(batch_id))


@router.post("/batches/{batch_id}/overrides", response_model=ApiResponse[OverrideDTO])
def add_override(
    batch_id: str,
    payload: OverrideReq,
    orchestrator: ImportOrchestrator = Depends(get_orchestrator),
) -> ApiResponse[OverrideDTO]:
    return ok(orchestrator.add_override(batch_id, payload))


@router.delete(
    "/batches/{batch_id}/overrides/{row_no}", response_model=ApiResponse[RemovedDTO]
)
def remove_override(
    batch_id: str,
    row_no: int,
    orchestrator: ImportOrchestrator = Depends(get_orchestrator),
) -> ApiResponse[RemovedDTO]:
    return ok(orchestrator.remove_override(batch_id, row_no))


@router.post("/batches/{batch_id}/discard", response_model=ApiResponse[BatchDetailDTO])
def discard_batch(
    batch_id: str,
    payload: DiscardReq | None = None,
    orchestrator: ImportOrchestrator = Depends(get_orchestrator),
) -> ApiResponse[BatchDetailDTO]:
    confirm = bool(payload.confirm) if payload is not None else False
    return ok(orchestrator.discard(batch_id, confirm=confirm))


# ── 模板 ────────────────────────────────────────────────────
@router.get("/templates", response_model=ApiResponse[list[TemplateDTO]])
def list_templates(
    channel: str | None = Query(default=None),
    orchestrator: ImportOrchestrator = Depends(get_orchestrator),
) -> ApiResponse[list[TemplateDTO]]:
    return ok(orchestrator.list_templates(_parse_channel(channel)))


@router.post("/templates", response_model=ApiResponse[TemplateDTO])
def create_template(
    payload: TemplateReq,
    orchestrator: ImportOrchestrator = Depends(get_orchestrator),
) -> ApiResponse[TemplateDTO]:
    return ok(orchestrator.save_template(payload))


# ── 缓冲区维护 ──────────────────────────────────────────────
@router.get("/orphans", response_model=ApiResponse[list[OrphanFileDTO]])
def list_orphans(
    orchestrator: ImportOrchestrator = Depends(get_orchestrator),
) -> ApiResponse[list[OrphanFileDTO]]:
    return ok(orchestrator.orphans())


@router.post("/orphans/cleanup", response_model=ApiResponse[OrphanCleanupDTO])
def cleanup_orphans(
    payload: OrphanCleanupReq,
    cleanup: CleanupService = Depends(get_cleanup_service),
) -> ApiResponse[OrphanCleanupDTO]:
    """清理孤儿文件（前端"清理"按钮已调用，C3-B 补后端）。

    三重白名单（路径防穿越 → 名字形态 → 不在已知批次）见
    ``CleanupService.cleanup_orphans``；任一不过整体拒绝，验证阶段不删文件。
    """
    return ok(cleanup.cleanup_orphans(payload.names))


@router.get("/usage", response_model=ApiResponse[BufferUsageDTO])
def buffer_usage(
    orchestrator: ImportOrchestrator = Depends(get_orchestrator),
) -> ApiResponse[BufferUsageDTO]:
    return ok(orchestrator.usage())


@router.post("/ensure-dir", response_model=ApiResponse[EnsureDirDTO])
def ensure_dir(
    orchestrator: ImportOrchestrator = Depends(get_orchestrator),
) -> ApiResponse[EnsureDirDTO]:
    return ok(orchestrator.ensure_dir())


# ── 参数转换 ────────────────────────────────────────────────
def _parse_channel(value: str | None) -> Channel | None:
    if value is None or not value.strip():
        return None
    try:
        return Channel(value.strip().lower())
    except ValueError as exc:
        raise EntryValidationError(
            ErrorCode.INVALID_ENUM_VALUE,
            f"渠道只支持 {', '.join(item.value for item in Channel)}，收到『{value}』",
        ) from exc


def _parse_status(value: str | None) -> BatchStatus | None:
    if value is None or not value.strip():
        return None
    try:
        return BatchStatus(value.strip().lower())
    except ValueError as exc:
        raise EntryValidationError(
            ErrorCode.INVALID_ENUM_VALUE,
            f"状态只支持 {', '.join(item.value for item in BatchStatus)}，收到『{value}』",
        ) from exc
