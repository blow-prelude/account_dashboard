"""缓冲区与导入向导端点（C2 的 15 个，SDD §6.2.2 / C2-B §5.1）。

本层只做三件事：**校验入参 → 调 Service → 包统一响应**。不写 SQL、不 import 仓储
（``tests/integration/test_layering.py`` 会拦），也不做状态判断（那在 Service + 状态机里）。

上传走 ``anyio.to_thread``：落盘是同步阻塞的磁盘 IO（1MB 分块），放线程里执行，
避免 5MB 文件把事件循环卡住 —— 这是 ``asyncio`` 里最容易犯的错（阻塞 IO 混进协程）。
"""

from __future__ import annotations

from functools import partial
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, File, Form, Path, Query, UploadFile

from account_dashboard.api.deps import (
    get_import_orchestrator,
    get_mapping_service,
)
from account_dashboard.api.response import ApiResponse, Page, PageMeta, ok
from account_dashboard.api.validators import (
    clamp_preview_limit,
    validate_channel,
    validate_page,
    validate_sort,
    validate_status,
    validate_upload_meta,
)
from account_dashboard.errors import EntryValidationError, ErrorCode
from account_dashboard.limits import PAGE_SIZE_DEFAULT
from account_dashboard.models.staging import (
    BatchDetailDTO,
    BatchDTO,
    BufferUsageDTO,
    DiscardReq,
    EnsureDirDTO,
    MappingReq,
    MappingResultDTO,
    OrphanFileDTO,
    OverrideDTO,
    OverrideReq,
    OverrideRevokeDTO,
    ParseInfoDTO,
    PrecheckResultDTO,
    PreviewDTO,
    TemplateDTO,
    TemplateReq,
)
from account_dashboard.services.import_orchestrator import ImportOrchestrator
from account_dashboard.services.mapping_service import MappingService

router = APIRouter(prefix="/api/v1/staging", tags=["staging"])

Orchestrator = Annotated[ImportOrchestrator, Depends(get_import_orchestrator)]
Mapper = Annotated[MappingService, Depends(get_mapping_service)]


# ── 批次：上传 / 列表 / 详情 / 解析 / 预览 / 丢弃 ───────────────


@router.post("/batches", response_model=ApiResponse[BatchDTO])
async def upload_batch(
    orchestrator: Orchestrator,
    file: Annotated[UploadFile, File(description="CSV 或 xlsx 账单文件")],
    channel: Annotated[str | None, Form()] = None,
) -> ApiResponse[BatchDTO]:
    """上传 → 落盘 → 建批次（``uploaded``）→ 自动解析。

    解析失败（编码/表头/空文件/超行数）返回 4xx 且**批次已置 failed 并保留文件**，
    ``data.detail.batch_id`` 可直接用于 ``POST /batches/{id}/parse`` 重试。
    """
    declared_size = getattr(file, "size", None)
    validate_upload_meta(file.filename or "", file.content_type, declared_size)
    hint = validate_channel(channel)

    batch = await anyio.to_thread.run_sync(
        partial(
            orchestrator.create_batch,
            file.file,
            file.filename or "",
            int(declared_size or 0),
            hint,
        )
    )
    return ok(batch)


@router.get("/batches", response_model=ApiResponse[Page[BatchDTO]])
def list_batches(
    orchestrator: Orchestrator,
    status: Annotated[str | None, Query(description="按状态筛选")] = None,
    page: Annotated[int, Query()] = 1,
    page_size: Annotated[int, Query()] = PAGE_SIZE_DEFAULT,
    sort: Annotated[str | None, Query(description="created_at / -created_at")] = None,
) -> ApiResponse[Page[BatchDTO]]:
    validate_page(page, page_size)
    status_filter = validate_status(status)
    order = validate_sort(sort)

    items, total = orchestrator.list_batches(
        status=status_filter, page=page, page_size=page_size, sort=order
    )
    return ok(Page(items=items, meta=PageMeta.build(page, page_size, total)))


@router.get("/batches/{batch_id}", response_model=ApiResponse[BatchDetailDTO])
def get_batch(
    batch_id: Annotated[str, Path()], orchestrator: Orchestrator
) -> ApiResponse[BatchDetailDTO]:
    return ok(orchestrator.get_batch_detail(batch_id))


@router.post("/batches/{batch_id}/parse", response_model=ApiResponse[ParseInfoDTO])
def parse_batch(
    batch_id: Annotated[str, Path()], orchestrator: Orchestrator
) -> ApiResponse[ParseInfoDTO]:
    """重试解析 / 重新解析（``failed`` 与 ``prechecked`` 均可，后者回 ``mapped_pending``）。"""
    return ok(orchestrator.parse_batch(batch_id))


@router.get("/batches/{batch_id}/preview", response_model=ApiResponse[PreviewDTO])
def preview_batch(
    batch_id: Annotated[str, Path()],
    orchestrator: Orchestrator,
    limit: Annotated[int | None, Query(description="预览行数，上限 50")] = None,
) -> ApiResponse[PreviewDTO]:
    """只读预览，**不改批次状态**（前端可以边拖滑块边看）。"""
    return ok(orchestrator.preview(batch_id, clamp_preview_limit(limit)))


@router.post("/batches/{batch_id}/discard", response_model=ApiResponse[BatchDTO])
def discard_batch(
    batch_id: Annotated[str, Path()],
    orchestrator: Orchestrator,
    payload: DiscardReq | None = None,
) -> ApiResponse[BatchDTO]:
    """丢弃批次（同时删除缓冲区文件）；删除失败返回 409 且状态不变（C3 改为队列）。"""
    if payload is not None and not payload.confirm:
        raise EntryValidationError(ErrorCode.INVALID_ENUM_VALUE, "请二次确认后再丢弃批次")
    return ok(orchestrator.discard(batch_id))


# ── 映射与模板 ────────────────────────────────────────────────


@router.put("/batches/{batch_id}/mapping", response_model=ApiResponse[MappingResultDTO])
def save_mapping(
    batch_id: Annotated[str, Path()],
    payload: MappingReq,
    orchestrator: Orchestrator,
) -> ApiResponse[MappingResultDTO]:
    """保存字段映射。成功即置 ``prechecked``（D-1：映射确认 + 可预检）。"""
    return ok(orchestrator.apply_mapping(batch_id, payload))


@router.get("/templates", response_model=ApiResponse[list[TemplateDTO]])
def list_templates(
    mapper: Mapper,
    channel: Annotated[str | None, Query()] = None,
) -> ApiResponse[list[TemplateDTO]]:
    return ok(mapper.list_templates(validate_channel(channel)))


@router.post("/templates", response_model=ApiResponse[TemplateDTO])
def create_template(payload: TemplateReq, mapper: Mapper) -> ApiResponse[TemplateDTO]:
    """保存渠道模板；三策略：abort(409) / overwrite(降级旧 default) / save_as(加后缀)。"""
    spec, policy, channel = payload.spec, payload.policy, payload.channel
    return ok(mapper.save_template(channel, payload.name, spec, policy))


# ── 预检与强制新增 ────────────────────────────────────────────


@router.post("/batches/{batch_id}/precheck", response_model=ApiResponse[PrecheckResultDTO])
def precheck_batch(
    batch_id: Annotated[str, Path()], orchestrator: Orchestrator
) -> ApiResponse[PrecheckResultDTO]:
    """去重预检（只读）：只比对 ``transaction.fp``，不写任何业务表。"""
    return ok(orchestrator.run_precheck(batch_id))


@router.post("/batches/{batch_id}/overrides", response_model=ApiResponse[OverrideDTO])
def mark_override(
    batch_id: Annotated[str, Path()],
    payload: OverrideReq,
    orchestrator: Orchestrator,
) -> ApiResponse[OverrideDTO]:
    """单条强制新增（幂等：同 ``(batch_id, row_no)`` 重复调用只更新原因）。"""
    return ok(orchestrator.mark_override(batch_id, payload.row_no, payload.reason))


@router.delete(
    "/batches/{batch_id}/overrides/{row_no}", response_model=ApiResponse[OverrideRevokeDTO]
)
def revoke_override(
    batch_id: Annotated[str, Path()],
    row_no: Annotated[int, Path(ge=1)],
    orchestrator: Orchestrator,
) -> ApiResponse[OverrideRevokeDTO]:
    """撤销强制新增；不存在时返回 ``{"removed": false}``（幂等，不报错）。"""
    return ok(orchestrator.revoke_override(batch_id, row_no))


# ── 缓冲区运维 ────────────────────────────────────────────────


@router.get("/usage", response_model=ApiResponse[BufferUsageDTO])
def buffer_usage(orchestrator: Orchestrator) -> ApiResponse[BufferUsageDTO]:
    return ok(orchestrator.buffer_usage())


@router.post("/ensure-dir", response_model=ApiResponse[EnsureDirDTO])
def ensure_buffer_dir(orchestrator: Orchestrator) -> ApiResponse[EnsureDirDTO]:
    """重建缓冲区目录（EX-23）；重建成功不掩盖"相关批次文件已丢失"。"""
    return ok(orchestrator.ensure_buffer_dir())


@router.get("/orphans", response_model=ApiResponse[list[OrphanFileDTO]])
def list_orphans(orchestrator: Orchestrator) -> ApiResponse[list[OrphanFileDTO]]:
    """孤儿文件清单（只读，忽略 ``.tmp`` 残片）。清理动作属 C3。"""
    return ok(orchestrator.orphans())


__all__ = ["router"]
