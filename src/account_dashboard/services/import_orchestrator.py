"""导入编排（SDD §4.2.1 / §7.1~§7.4）：上传 → 解析 → 映射 → 预检。

边界很清楚：**本模块不写任何业务数据**。C2 全程只有 ``staging_batch`` 与
``channel_template`` / ``override_mark`` 会被写入，``transaction`` 与 ``raw_*``
必须保持零行 —— 这是 C2 出口检查表的自证项，也是 C3 的开工前提。

对外只暴露 DTO；``replay()`` 返回 ``ParsedRow`` 列表，是 C3 入库与 C4 重算的重放入口。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from account_dashboard.api.errors import (
    AppError,
    BusinessRuleError,
    EntryValidationError,
    ErrorCode,
)
from account_dashboard.api.response import Page, PageMeta
from account_dashboard.infra.buffer_file import BufferFileManager, UploadStream
from account_dashboard.infra.clock import now_iso
from account_dashboard.infra.errors import (
    BufferDirError,
    FileDeleteError,
    HeaderUnrecognizedError,
    InfraError,
)
from account_dashboard.infra.event_log import EventLogger
from account_dashboard.infra.logger import get_logger
from account_dashboard.infra.parsers.base import CsvRowSource, XlsxRowSource, is_blank_row
from account_dashboard.infra.parsers.encoding import decode_file
from account_dashboard.infra.parsers.models import ParsedRow
from account_dashboard.infra.parsers.registry import ParserRegistry
from account_dashboard.models.enums import BatchAction, BatchStatus, Channel, DedupLabel
from account_dashboard.models.internal import MAPPING_FIELDS, MappingSnapshot, MappingSpec
from account_dashboard.models.staging import (
    BatchDetailDTO,
    BatchDTO,
    BufferUsageDTO,
    EnsureDirDTO,
    MappingReq,
    MappingResultDTO,
    OrphanFileDTO,
    OverrideDTO,
    OverrideReq,
    ParseInfoDTO,
    ParseIssueDTO,
    ParseMetaDTO,
    ParseResultDTO,
    PrecheckResultDTO,
    PrecheckRowDTO,
    PreviewDTO,
    PreviewRowDTO,
    RemovedDTO,
    TemplateDTO,
    TemplateReq,
)
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.override_repo import OverrideRepo
from account_dashboard.repositories.staging_repo import BatchRow, StagingRepo
from account_dashboard.repositories.unit_of_work import UnitOfWork
from account_dashboard.services import batch_guard
from account_dashboard.services.dedup_checker import DedupChecker, DedupRowResult
from account_dashboard.services.error_mapping import (
    to_app_error,
    translate_infra,
    translate_infra_async,
)
from account_dashboard.services.mapping_service import MappingService

_logger = get_logger("import")

DEFAULT_TEMPLATE_NAME = "默认"
DEFAULT_BUFFER_THRESHOLD_MB = 500
BUFFER_THRESHOLD_SETTING_KEY = "buffer_size_threshold_mb"
PREVIEW_MAX_LIMIT = 200


class ImportOrchestrator:
    def __init__(
        self,
        uow: UnitOfWork,
        buffer: BufferFileManager,
        registry: ParserRegistry | None = None,
        *,
        database: Database | None = None,
        events: EventLogger | None = None,
        threshold_bytes: int | None = None,
    ) -> None:
        self._uow = uow
        self._buffer = buffer
        self._registry = registry or ParserRegistry()
        self._database = database
        self._events = events or EventLogger()
        self._threshold_bytes = threshold_bytes
        conn = uow.conn
        self._staging = StagingRepo(conn)
        self._overrides = OverrideRepo(conn)
        self._mapping = MappingService(conn)
        self._dedup = DedupChecker(conn)

    # ══ 上传 ══════════════════════════════════════════════════
    @translate_infra_async
    async def create_batch(
        self,
        stream: UploadStream,
        file_name: str,
        declared_size: int = 0,
        channel_hint: Channel | None = None,
    ) -> BatchDetailDTO:
        """流式落盘 → 建批次（``uploaded``）→ 自动解析（失败只置 ``failed``，不阻断上传）。"""
        stored = await self._buffer.save_stream(stream, file_name, declared_size)
        batch_id = uuid4().hex
        try:
            with self._uow.begin():
                self._staging.create(
                    batch_id=batch_id,
                    file_name=file_name,
                    stored_name=stored.stored_name,
                    file_size=stored.size,
                    channel=channel_hint or Channel.OTHER,
                )
        except BaseException:
            # 记账失败 → 回滚文件，避免「文件在、批次不在」的孤儿
            _discard_quiet(self._buffer, stored.path)
            raise

        self._events.record("batch.created", {"batch_id": batch_id, "count": stored.size})
        self._try_parse(batch_id)
        return self.get_batch(batch_id)

    def _try_parse(self, batch_id: str) -> None:
        """自动解析失败不抛出：批次已落库，用户可以「重新解析」或丢弃。"""
        try:
            self.parse_batch(batch_id)
        except AppError as exc:
            _logger.info("批次 %s 自动解析失败：%s", batch_id, exc.message)

    # ══ 解析 ══════════════════════════════════════════════════
    @translate_infra
    def parse_batch(self, batch_id: str) -> ParseResultDTO:
        batch = self._load(batch_id)
        batch_guard.assert_transition(batch.status_enum, BatchAction.PARSE)
        path = self._path_of(batch)

        try:
            result = self._registry.parse(path, channel_hint=batch.channel_enum)
        except AppError:
            raise
        except InfraError as exc:
            app_error = to_app_error(exc)
            self._mark_failed(batch, app_error.message)
            raise app_error from exc
        except Exception as exc:  # noqa: BLE001 - 损坏的 zip/异常单元格不应 500
            _logger.exception("批次 %s 解析异常", batch_id)
            app_error = EntryValidationError(
                ErrorCode.EMPTY_FILE,
                "文件已损坏或格式不支持，请用 Excel 重新导出后再试",
            )
            self._mark_failed(batch, app_error.message)
            raise app_error from exc

        channel = batch.channel_enum if batch.channel_enum != Channel.OTHER else result.channel
        parse_meta = json.dumps(result.meta, ensure_ascii=False)
        with self._uow.begin():
            updated = self._staging.update_after_parse(
                batch_id,
                channel=channel,
                encoding=result.encoding,
                adapter=result.adapter,
                header_row_no=result.header.row_index,
                total_rows=result.total_rows,
                parse_meta=parse_meta,
                expected_from=batch.status_enum,
            )
            if updated == 0:
                raise BusinessRuleError(
                    ErrorCode.BATCH_STATE_CONFLICT,
                    "批次状态已被其他操作改变，请刷新后重试",
                    detail={"batch_id": batch_id},
                )
            self._staging.set_status(
                batch_id, to=BatchStatus.MAPPED_PENDING, expected_from=batch.status_enum
            )

        self._events.record(
            "batch.parsed", {"batch_id": batch_id, "count": result.total_rows, "scope": "parse"}
        )
        return ParseResultDTO(
            batch=self._batch_dto(self._load(batch_id)),
            parse=ParseInfoDTO(
                adapter=result.adapter,
                encoding=result.encoding,
                header_row_no=result.header.row_index,
                total_rows=result.total_rows,
                empty_rows_skipped=result.stats.empty_rows_skipped,
                columns=list(result.header.columns),
                issues=result.stats.as_dict(),
            ),
        )

    def _mark_failed(self, batch: BatchRow, message: str) -> None:
        try:
            with self._uow.begin():
                self._staging.set_status(batch.id, to=BatchStatus.FAILED, reason=message)
        except sqlite3.Error:  # pragma: no cover - 状态写入失败不应掩盖原始解析错误
            _logger.exception("批次 %s 置为 failed 时失败", batch.id)

    # ══ 查询 ══════════════════════════════════════════════════
    def list_batches(
        self,
        *,
        status: BatchStatus | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Page[BatchDTO]:
        rows, total = self._staging.list(status=status, page=page, page_size=page_size)
        return Page[BatchDTO](
            items=[self._batch_dto(row) for row in rows],
            meta=PageMeta.build(page, page_size, total),
        )

    def get_batch(self, batch_id: str) -> BatchDetailDTO:
        batch = self._load(batch_id)
        return self._batch_detail(batch)

    # ══ 预览 ══════════════════════════════════════════════════
    @translate_infra
    def preview(self, batch_id: str, limit: int = 20) -> PreviewDTO:
        batch = self._load(batch_id)
        path = self._path_of(batch)
        limit = max(1, min(limit, PREVIEW_MAX_LIMIT))
        spec = self._spec_from_row(batch)

        try:
            result = self._registry.parse(
                path,
                channel_hint=batch.channel_enum,
                mapping=spec,
                adapter_name=batch.adapter,
                allow_partial=True,
            )
        except AppError:
            raise
        except HeaderUnrecognizedError:
            return self._preview_without_header(batch, path, limit)

        rows = [
            _preview_row(row) for row in result.rows[:limit]
        ]
        return PreviewDTO(
            batch_id=batch.id,
            header_row_no=result.header.row_index,
            header_recognized=True,
            columns=list(result.header.columns),
            detected_fields={
                name: index
                for name, index in result.mapping.as_column_map().items()
                if index is not None
            },
            rows=rows,
            total_rows=result.total_rows,
            empty_rows_skipped=result.stats.empty_rows_skipped,
            issues=result.stats.as_dict(),
            limit=limit,
        )

    def _preview_without_header(self, batch: BatchRow, path: Path, limit: int) -> PreviewDTO:
        """EX-03：表头识别不出来时也要能看到「文件里到底是什么列」，否则无法手动映射。"""
        columns = _first_row_columns(path)
        return PreviewDTO(
            batch_id=batch.id,
            header_row_no=batch.header_row_no if batch.header_row_no is not None else -1,
            header_recognized=False,
            columns=columns,
            detected_fields={},
            rows=[],
            total_rows=batch.total_rows,
            limit=limit,
            message="没有识别到表头，请在映射页手动指定各列含义",
        )

    # ══ 映射 ══════════════════════════════════════════════════
    @translate_infra
    def apply_mapping(self, batch_id: str, req: MappingReq) -> MappingResultDTO:
        batch = self._load(batch_id)
        batch_guard.assert_transition(batch.status_enum, BatchAction.MAP)
        path = self._path_of(batch)

        probe = self._registry.parse(
            path,
            channel_hint=batch.channel_enum,
            adapter_name=batch.adapter,
            allow_partial=True,
            parse_rows=False,
        )
        self._mapping.validate(req, column_count=len(probe.header.columns))

        template_id: str | None = None
        with self._uow.begin():
            if req.save_template:
                template = self._mapping.save_template(
                    TemplateReq(
                        channel=probe.channel,
                        name=req.template_name or DEFAULT_TEMPLATE_NAME,
                        spec=req,
                        policy=req.template_policy,
                    )
                )
                template_id = template.id

            spec = self._mapping.to_spec(req, template_id=template_id)
            self._staging.update_mapping(
                batch_id,
                mapped_fields=json.dumps(spec.to_dict(), ensure_ascii=False),
                channel=probe.channel,
                header_row_no=probe.header.row_index,
            )
            # 映射变了 → 旧预检结果作废，强制重跑（EX-22 的前置防护）
            self._staging.reset_precheck(batch_id, status=BatchStatus.MAPPED_PENDING)

        refreshed = self._load(batch_id)
        return MappingResultDTO(
            batch_id=batch_id,
            mapping=req,
            columns=list(probe.header.columns),
            template_id=template_id,
            status=refreshed.status_enum,
        )

    def list_templates(self, channel: Channel | None = None) -> list[TemplateDTO]:
        return self._mapping.list_templates(channel)

    @translate_infra
    def save_template(self, req: TemplateReq) -> TemplateDTO:
        with self._uow.begin():
            return self._mapping.save_template(req)

    # ══ 预检 ══════════════════════════════════════════════════
    @translate_infra
    def run_precheck(self, batch_id: str) -> PrecheckResultDTO:
        batch = self._load(batch_id)
        batch_guard.assert_transition(batch.status_enum, BatchAction.PRECHECK)
        spec = self._spec_from_row(batch)
        if spec is None:
            raise EntryValidationError(
                ErrorCode.MAPPING_INCOMPLETE, "请先保存字段映射，再做去重预检"
            )
        missing = spec.missing_core()
        if missing:
            raise EntryValidationError(
                ErrorCode.MAPPING_INCOMPLETE,
                "映射缺少核心字段，请回到映射页补齐后再预检",
                detail={"missing_fields": missing},
            )
        path = self._path_of(batch)

        result = self._registry.parse(
            path,
            mapping=spec,
            adapter_name=batch.adapter,
            allow_partial=True,
        )
        overrides = self._overrides.list_by_batch(batch_id)
        dedup = self._dedup.check(result.rows, overrides.keys())

        snapshot = MappingSnapshot(
            adapter=result.adapter,
            encoding=result.encoding,
            header_row_no=result.header.row_index,
            column_map=spec.as_column_map(),
            direction_map={key: str(value) for key, value in spec.direction_map.items()},
            amount_scale=spec.amount_scale,
            template_id=spec.template_id,
            created_at=now_iso(),
        )

        with self._uow.begin():
            self._staging.update_precheck(
                batch_id,
                new_count=dedup.summary.get("new", 0),
                dup_count=dedup.summary.get("dup", 0),
                pending_count=dedup.summary.get("pending_manual", 0),
                mapping_snapshot=json.dumps(snapshot.to_dict(), ensure_ascii=False),
            )

        labels = {item.row_no: item for item in dedup.rows}
        rows = [_precheck_row(row, labels.get(row.row_no)) for row in result.rows]
        message = ""
        if dedup.summary.get("pending_manual", 0):
            message = (
                f"{dedup.summary['pending_manual']} 条记录时间或金额缺失，"
                "未参与自动去重，请人工核对"
            )
        self._events.record(
            "batch.prechecked",
            {"batch_id": batch_id, "count": dedup.summary.get("total", 0)},
        )
        return PrecheckResultDTO(
            batch_id=batch_id,
            summary=dedup.summary,
            rows=rows,
            snapshot_at=snapshot.created_at,
            issues=result.stats.as_dict(),
            message=message,
        )

    # ══ 强制新增 ══════════════════════════════════════════════
    @translate_infra
    def add_override(self, batch_id: str, req: OverrideReq) -> OverrideDTO:
        batch = self._load(batch_id)
        if batch.total_rows and not 1 <= req.row_no <= batch.total_rows:
            raise EntryValidationError(
                ErrorCode.INVALID_ENUM_VALUE,
                f"行号 {req.row_no} 超出范围（本批次共 {batch.total_rows} 行）",
                detail={"row_no": req.row_no, "total_rows": batch.total_rows},
            )
        with self._uow.begin():
            record = self._overrides.upsert(batch_id, req.row_no, req.reason, req.note)
        return OverrideDTO(
            batch_id=record.batch_id,
            row_no=record.row_no,
            reason=record.reason,
            note=record.note,
            created_at=record.created_at,
        )

    def remove_override(self, batch_id: str, row_no: int) -> RemovedDTO:
        self._load(batch_id)
        with self._uow.begin():
            removed = self._overrides.delete(batch_id, row_no) > 0
        return RemovedDTO(removed=removed)

    # ══ 丢弃 / 缓冲区管理 ═════════════════════════════════════
    @translate_infra
    def discard(self, batch_id: str, *, confirm: bool = False) -> BatchDetailDTO:
        batch = self._load(batch_id)
        batch_guard.assert_transition(batch.status_enum, BatchAction.DISCARD)
        if not confirm:
            raise EntryValidationError(
                ErrorCode.INVALID_ENUM_VALUE, "丢弃会删除缓冲区文件，请先确认（confirm=true）"
            )

        with self._uow.begin():
            self._staging.set_status(
                batch_id, to=BatchStatus.DISCARDED, expected_from=batch.status_enum
            )

        path = self._buffer.path_for(batch.stored_name)
        try:
            self._buffer.delete(path)
        except FileDeleteError as exc:
            # 文件被占用：记入待清理队列（C3 会重试），批次丢弃本身已成功
            _logger.warning("批次 %s 文件删除失败，已入待清理：%s", batch_id, exc.message)
            self._enqueue_cleanup(batch_id, path, exc.message)

        return self._batch_detail(self._load(batch_id))

    def _enqueue_cleanup(self, batch_id: str, path: Path, reason: str) -> None:
        try:
            with self._uow.begin():
                self._uow.conn.execute(
                    "INSERT INTO cleanup_queue(id, batch_id, file_path, reason, attempts, status, "
                    "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        uuid4().hex,
                        batch_id,
                        str(path),
                        reason[:200],
                        0,
                        "pending",
                        now_iso(),
                        now_iso(),
                    ),
                )
        except sqlite3.Error:  # pragma: no cover - 队列写入失败只告警
            _logger.exception("待清理队列写入失败：%s", path.name)

    def orphans(self) -> list[OrphanFileDTO]:
        known = self._staging.known_stored_names()
        return [
            OrphanFileDTO(
                name=item.name, size_bytes=item.size_bytes, modified_at=item.modified_at
            )
            for item in self._buffer.scan_orphans(known)
        ]

    def usage(self) -> BufferUsageDTO:
        threshold = self._threshold_bytes or self._buffer_threshold_bytes()
        stats = self._buffer.usage(threshold_bytes=threshold)
        return BufferUsageDTO(
            file_count=stats.file_count,
            total_bytes=stats.total_bytes,
            threshold_bytes=stats.threshold_bytes,
            exceeded=stats.exceeded,
            oldest_at=stats.oldest_at,
        )

    def ensure_dir(self) -> EnsureDirDTO:
        try:
            created = self._buffer.ensure_dir()
        except BufferDirError as exc:
            raise to_app_error(exc) from exc
        return EnsureDirDTO(path=str(self._buffer.buffer_dir), created=created)

    def _buffer_threshold_bytes(self) -> int:
        """缓冲区阈值默认 500MB；C5 的 ``setting`` 表若已写入则以其为准。"""
        megabytes = DEFAULT_BUFFER_THRESHOLD_MB
        if self._database is not None:
            try:
                row = self._database.query_one(
                    "SELECT value FROM setting WHERE key = ?", (BUFFER_THRESHOLD_SETTING_KEY,)
                )
                if row is not None:
                    megabytes = max(10, int(json.loads(str(row["value"]))))
            except (sqlite3.Error, ValueError, TypeError):
                megabytes = DEFAULT_BUFFER_THRESHOLD_MB
        return megabytes * 1024 * 1024

    # ══ 重放（C3/C4 交接） ════════════════════════════════════
    @translate_infra
    def replay(
        self,
        batch_id: str,
        mapping_snapshot: MappingSnapshot | dict[str, Any] | None = None,
    ) -> list[ParsedRow]:
        """用映射快照重放解析（I11）。C3 入库与 C4 重算都靠它。

        签名是**交接契约**：``replay(batch_id, mapping_snapshot) -> list[ParsedRow]``，
        不要改成返回 report 或加必填参数。
        """
        batch = self._load(batch_id)
        snapshot = self._resolve_snapshot(batch, mapping_snapshot)
        path = self._path_of(batch)
        result = self._registry.parse(
            path,
            mapping=snapshot.as_mapping_spec(),
            adapter_name=snapshot.adapter,
            allow_partial=True,
        )
        return result.rows

    def _resolve_snapshot(
        self,
        batch: BatchRow,
        snapshot: MappingSnapshot | dict[str, Any] | None,
    ) -> MappingSnapshot:
        if isinstance(snapshot, MappingSnapshot):
            return snapshot
        if isinstance(snapshot, dict):
            return MappingSnapshot.from_dict(snapshot)
        if batch.mapping_snapshot:
            return MappingSnapshot.from_dict(json.loads(batch.mapping_snapshot))
        raise BusinessRuleError(
            ErrorCode.BATCH_STATE_CONFLICT,
            "批次尚未完成预检，没有可用的映射快照，请先执行预检",
            detail={"batch_id": batch.id, "status": batch.status},
        )

    # ══ 内部 ══════════════════════════════════════════════════
    def _load(self, batch_id: str) -> BatchRow:
        batch = self._staging.get(batch_id)
        if batch is None:
            raise BusinessRuleError(
                ErrorCode.BATCH_NOT_FOUND, "批次不存在或已被清理，请刷新列表"
            )
        return batch

    def _path_of(self, batch: BatchRow) -> Path:
        path = self._buffer.path_for(batch.stored_name)
        if not path.is_file():
            raise to_app_error(
                BufferDirError("缓冲区文件已丢失，请重新上传该账单")
            )
        return path

    def _spec_from_row(self, batch: BatchRow) -> MappingSpec | None:
        if not batch.mapped_fields:
            return None
        try:
            return MappingSpec.from_dict(json.loads(batch.mapped_fields))
        except (ValueError, TypeError):
            _logger.warning("批次 %s 的映射字段损坏，已忽略", batch.id)
            return None

    def _batch_dto(self, batch: BatchRow) -> BatchDTO:
        return BatchDTO(
            id=batch.id,
            file_name=batch.file_name,
            file_size=batch.file_size,
            channel=batch.channel_enum,
            status=batch.status_enum,
            total_rows=batch.total_rows,
            new_count=batch.new_count,
            dup_count=batch.dup_count,
            pending_count=batch.pending_count,
            encoding=batch.encoding,
            adapter=batch.adapter,
            fail_reason=batch.fail_reason,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
        )

    def _batch_detail(self, batch: BatchRow) -> BatchDetailDTO:
        base = self._batch_dto(batch)
        spec = self._spec_from_row(batch)
        return BatchDetailDTO(
            **base.model_dump(),
            header_row_no=batch.header_row_no,
            mapped_fields=_mapping_req(spec) if spec is not None else None,
            mapping_snapshot=json.loads(batch.mapping_snapshot) if batch.mapping_snapshot else None,
            parse_meta=_parse_meta(batch),
            file_exists=self._buffer.exists(batch.stored_name),
        )


def _mapping_req(spec: MappingSpec) -> MappingReq:
    payload: dict[str, Any] = {name: spec.column(name) for name in MAPPING_FIELDS}
    payload["direction_map"] = spec.direction_map
    payload["amount_scale"] = spec.amount_scale
    return MappingReq(**payload)


def _parse_meta(batch: BatchRow) -> ParseMetaDTO | None:
    if not batch.parse_meta:
        return None
    try:
        data = json.loads(batch.parse_meta)
    except ValueError:
        return None
    return ParseMetaDTO(
        sheet=data.get("sheet"),
        delimiter=data.get("delimiter"),
        preamble_rows=int(data.get("preamble_rows") or 0),
        header_row_no=int(data.get("header_row_no") or 0),
        empty_rows_skipped=int(data.get("empty_rows_skipped") or 0),
        column_count=int(data.get("column_count") or 0),
        columns=list(data.get("columns") or []),
        issues={str(key): int(value) for key, value in (data.get("issues") or {}).items()},
    )


def _preview_row(row: ParsedRow) -> PreviewRowDTO:
    return PreviewRowDTO(
        row_no=row.row_no,
        occurred_at=row.occurred_at_iso,
        amount_cents=row.amount_cents,
        direction=row.direction,
        counterparty=row.counterparty,
        item=row.item,
        txn_type=row.txn_type,
        payment_method=row.payment_method,
        platform_category=row.platform_category,
        platform_status=row.platform_status,
        fingerprint=row.fingerprint,
        issues=[ParseIssueDTO(**issue.as_dict()) for issue in row.issues],
    )


def _precheck_row(row: ParsedRow, label: DedupRowResult | None) -> PrecheckRowDTO:
    return PrecheckRowDTO(
        row_no=row.row_no,
        label=label.label if label is not None else DedupLabel.PENDING_MANUAL,
        occurred_at=row.occurred_at_iso,
        amount_cents=row.amount_cents,
        direction=row.direction,
        counterparty=row.counterparty,
        item=row.item,
        fingerprint=row.fingerprint,
        issues=[ParseIssueDTO(**issue.as_dict()) for issue in row.issues],
        override=bool(label.override) if label is not None else False,
    )


def _discard_quiet(buffer: BufferFileManager, path: Path) -> None:
    try:
        buffer.delete(path)
    except FileDeleteError:  # pragma: no cover - 记账失败时尽力清理
        _logger.warning("回滚文件失败：%s", path.name)


def _first_row_columns(path: Path) -> list[str]:
    """表头识别失败时，取第一行非空内容当列名展示（只读、尽力而为）。"""
    try:
        with path.open("rb") as handle:
            head = handle.read(4)
        if head == b"PK\x03\x04":
            source: Any = XlsxRowSource(path=path)
        else:
            text, _ = decode_file(path)
            source = CsvRowSource(text=text)
        try:
            for cells in source.iter_rows():
                if not is_blank_row(cells):
                    return ["" if cell is None else str(cell).strip() for cell in cells]
        finally:
            source.close()
    except (InfraError, OSError):
        return []
    return []


__all__ = ["ImportOrchestrator", "PREVIEW_MAX_LIMIT"]
