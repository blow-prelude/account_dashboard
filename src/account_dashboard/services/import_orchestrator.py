"""导入编排（import-orchestrator，C2-B §4.1~§4.8，SDD §4.2.1）。

「上传 → 解析 → 映射 → 预检 → 丢弃」的唯一编排点。三条纪律：

* **不认识格式**：所有格式知识经 ``ParserRegistry`` / ``ParserAdapter`` 获取，
  本模块不 import ``openpyxl`` / ``csv``；
* **不写 SQL**：所有 SQL 在 ``repositories/*_repo.py``；
* **落盘顺序不可换**：先落文件、再建批次、最后解析（K7）。反过来会留下"批次有、
  文件无"的脏记录，孤儿计数与批次详情互相矛盾。

事务边界：解析在事务外（解析 5MB 文件不该占着写锁），只有状态变更进 ``with uow.begin()``。
每个写操作都先读状态再条件更新，靠 ``BEGIN IMMEDIATE`` 串行化 —— 不存在 TOCTOU。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, BinaryIO

from account_dashboard.errors import (
    AppError,
    BusinessRuleError,
    EntryValidationError,
    ErrorCode,
    FileIOError,
)
from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.infra.clock import now_iso
from account_dashboard.infra.event_log import EventLogger
from account_dashboard.infra.logger import get_logger
from account_dashboard.infra.parsers.base import ParserAdapter
from account_dashboard.infra.parsers.errors import (
    EmptyDocument,
    EncodingDetectFailed,
    HeaderNotRecognized,
    ParseError,
    RowLimitExceeded,
)
from account_dashboard.infra.parsers.registry import ParserRegistry
from account_dashboard.limits import (
    BUFFER_THRESHOLD_MB_DEFAULT,
    MAX_ROWS,
    PREVIEW_DEFAULT_LIMIT,
    PREVIEW_MAX_LIMIT,
)
from account_dashboard.models.internal import MappingSpec, ParsedRow, ParseResult
from account_dashboard.models.staging import (
    BatchDetailDTO,
    BatchDTO,
    BufferUsageDTO,
    EnsureDirDTO,
    MappingReq,
    MappingResultDTO,
    OrphanFileDTO,
    OverrideDTO,
    OverrideRevokeDTO,
    ParseInfoDTO,
    ParseIssueDTO,
    ParseMetaDTO,
    PrecheckResultDTO,
    PrecheckRowDTO,
    PreviewDTO,
    PreviewRowDTO,
    assert_transition,
)
from account_dashboard.repositories.override_repo import OverrideRepo
from account_dashboard.repositories.staging_repo import StagingRepo
from account_dashboard.repositories.transaction_repo import TransactionRepo
from account_dashboard.repositories.unit_of_work import UnitOfWork
from account_dashboard.services.dedup_checker import (
    LABEL_DUP,
    LABEL_NEW,
    LABEL_PENDING,
    DedupChecker,
)
from account_dashboard.services.mapping_service import MappingService

_logger = get_logger("import")

# 模板保存时的名称前缀（save_template=True 走 overwrite，即"把当前映射设为该渠道默认"）
_TEMPLATE_NAME = "默认模板"


def map_parse_error(exc: ParseError, *, batch_id: str | None = None) -> AppError:
    """把 ``infra`` 的解析异常族投影成 1xxx（合稿 K3 / M4）。

    前四类是**批次失败**（``status=failed``，可重试）；金额/时间问题是**行级**
    （``parse_meta.issues``），批次照常成功 —— 这条边界两侧必须一致。
    """
    detail = {"batch_id": batch_id} if batch_id else None
    if isinstance(exc, EncodingDetectFailed):
        return EntryValidationError(
            ErrorCode.ENCODING_UNDETECTABLE,
            "文件编码无法识别，请用 Excel 另存为 CSV(UTF-8) 后重试",
            detail=detail,
        )
    if isinstance(exc, HeaderNotRecognized):
        return EntryValidationError(
            ErrorCode.HEADER_UNRECOGNIZED,
            "无法识别表头，请手动确认各字段对应的列后重新解析",
            detail=detail,
        )
    if isinstance(exc, EmptyDocument):
        return EntryValidationError(
            ErrorCode.EMPTY_FILE,
            "文件里没有数据行，请确认导出的是账单明细而不是汇总页",
            detail=detail,
        )
    if isinstance(exc, RowLimitExceeded):
        return EntryValidationError(
            ErrorCode.ROW_LIMIT_EXCEEDED,
            f"账单超过 {MAX_ROWS} 行，请按月分批导出后再上传",
            detail=detail,
        )
    return EntryValidationError(
        ErrorCode.HEADER_UNRECOGNIZED,
        f"文件解析失败：{exc.message}",
        detail=detail,
    )


def _batch_dto(data: dict[str, Any]) -> BatchDTO:
    return BatchDTO(
        id=str(data["id"]),
        file_name=str(data["file_name"]),
        file_size=int(data["file_size"]),
        channel=data["channel"],
        status=data["status"],
        total_rows=int(data["total_rows"]),
        new_count=int(data["new_count"]),
        dup_count=int(data["dup_count"]),
        pending_count=int(data["pending_count"]),
        encoding=data["encoding"],
        adapter=data["adapter"],
        fail_reason=data["fail_reason"],
        created_at=str(data["created_at"]),
        updated_at=str(data["updated_at"]),
    )


def _parse_meta_dto(data: dict[str, Any] | None) -> ParseMetaDTO | None:
    if not isinstance(data, dict):
        return None
    return ParseMetaDTO(
        sheet=data.get("sheet"),
        delimiter=data.get("delimiter"),
        preamble_rows=int(data.get("preamble_rows", 0) or 0),
        header_row_no=int(data.get("header_row_no", 0) or 0),
        empty_rows_skipped=int(data.get("empty_rows_skipped", 0) or 0),
        issues=dict(data.get("issues") or {}),
        columns=int(data.get("columns", 0) or 0),
    )


def _derive_issues(row: ParsedRow) -> list[ParseIssueDTO]:
    """行级问题只有两种能从 ``ParsedRow`` 反推（A 线不单独回传 issues）。

    ``DIRECTION_UNKNOWN`` 无法反推（方向已被归一成 ``neutral``），只能看
    ``parse_meta.issues`` 的聚合数字 —— 这一点在批次详情里对用户说明。
    """
    issues: list[ParseIssueDTO] = []
    if row.occurred_at is None:
        issues.append(ParseIssueDTO(code="TIME_PARSE", row_no=row.row_no, field="occurred_at"))
    if row.amount_cents is None:
        issues.append(ParseIssueDTO(code="AMOUNT_PARSE", row_no=row.row_no, field="amount"))
    return issues


class ImportOrchestrator:
    def __init__(
        self,
        uow: UnitOfWork,
        buffer: BufferFileManager,
        parsers: ParserRegistry,
        mapping: MappingService,
        events: EventLogger | None = None,
    ) -> None:
        self._uow = uow
        self._buffer = buffer
        self._parsers = parsers
        self._mapping = mapping
        self._events = events or EventLogger()
        conn = uow.conn
        self._staging = StagingRepo(conn)
        self._overrides = OverrideRepo(conn)
        self._dedup = DedupChecker(TransactionRepo(conn))

    # ── 上传 ──────────────────────────────────────────────────
    def create_batch(
        self,
        stream: BinaryIO,
        file_name: str,
        declared_size: int,
        channel_hint: str | None = None,
    ) -> BatchDTO:
        """① 落盘 ② 建批次 ③ 自动解析（顺序见 §4.1，不可换）。"""
        stored = self._buffer.save_stream(stream, file_name, declared_size)

        with self._uow.begin():
            created = self._staging.create(
                file_name=file_name,
                stored_name=stored.stored_name,
                file_size=stored.size,
                channel=channel_hint or "other",
            )
        batch_id = str(created["id"])
        self._events.record("batch.created", {"batch_id": batch_id})

        # 解析失败不删文件（供重试），错误里带 batch_id 供前端直接重试
        info = self.parse_batch(batch_id)
        return info.batch

    # ── 解析 ──────────────────────────────────────────────────
    def parse_batch(self, batch_id: str) -> ParseInfoDTO:
        batch = self._staging.get_or_raise(batch_id)
        assert_transition(str(batch["status"]), "parse")

        try:
            adapter = self._adapter_for(batch)
            result = self._execute_parse(batch, adapter)
        except ParseError as exc:
            self._mark_failed_quietly(batch_id, exc.message)
            raise map_parse_error(exc, batch_id=batch_id) from exc
        except AppError:
            raise
        except Exception as exc:  # 解析器内部异常：同样视为批次失败，保留文件可重试
            _logger.exception("解析批次 %s 时发生未预期异常", batch_id)
            self._mark_failed_quietly(batch_id, f"解析异常：{exc}"[:200])
            raise

        meta = self._meta_payload(result)
        with self._uow.begin():
            updated = self._staging.mark_parsed(
                batch_id,
                encoding=result.encoding,
                adapter=result.adapter,
                header_row_no=result.header_row_no,
                parse_meta=meta,
                total_rows=len(result.rows),
                channel=getattr(adapter, "channel", None),
            )
        self._events.record("batch.parsed", {"batch_id": batch_id, "count": len(result.rows)})
        return ParseInfoDTO(batch=_batch_dto(updated), parse_meta=_parse_meta_dto(meta))

    def replay(self, batch_id: str) -> list[ParsedRow]:
        """用 ``mapped_fields``（C2）或 ``mapping_snapshot``（C3）重放解析。

        给 C3 入库、C4 重算复用；**只读**，不改批次状态。
        """
        batch = self._staging.get_or_raise(batch_id)
        try:
            return self._execute_parse(batch).rows
        except ParseError as exc:
            raise map_parse_error(exc, batch_id=batch_id) from exc

    # ── 预览 ──────────────────────────────────────────────────
    def preview(self, batch_id: str, limit: int | None = None) -> PreviewDTO:
        batch = self._staging.get_or_raise(batch_id)
        wanted = PREVIEW_DEFAULT_LIMIT if limit is None else max(1, int(limit))
        capped = min(wanted, PREVIEW_MAX_LIMIT)

        try:
            result = self._execute_parse(batch)
        except ParseError as exc:
            raise map_parse_error(exc, batch_id=batch_id) from exc

        headers = self._headers_of(result.rows)
        rows = result.rows[:capped]
        return PreviewDTO(
            batch_id=batch_id,
            total_rows=len(result.rows),
            columns=result.columns,
            header_row_no=result.header_row_no,
            headers=headers,
            suggested_mapping=self._spec_for(batch),
            rows=[
                PreviewRowDTO(
                    row_no=row.row_no,
                    occurred_at=row.occurred_at,
                    amount_cents=row.amount_cents,
                    direction=row.direction,
                    counterparty=row.counterparty,
                    item=row.item,
                    cells=[str(row.raw_payload.get(header, "")) for header in headers],
                    issues=_derive_issues(row),
                    valid=row.is_valid,
                )
                for row in rows
            ],
            limit=capped,
            truncated=len(result.rows) > capped,
        )

    # ── 映射 ──────────────────────────────────────────────────
    def apply_mapping(self, batch_id: str, mapping: MappingReq) -> MappingResultDTO:
        batch = self._staging.get_or_raise(batch_id)
        assert_transition(str(batch["status"]), "map")

        columns = int((batch.get("parse_meta") or {}).get("columns", 0) or 0)
        spec, warnings = self._mapping.validate(mapping, columns)

        with self._uow.begin():
            updated = self._staging.mark_mapped(batch_id, mapped_fields=spec.model_dump())

        template = None
        if mapping.save_template:
            # 用户明确要求"存成该渠道默认"，故用 overwrite 而非另存
            template = self._mapping.save_template(
                batch["channel"], _TEMPLATE_NAME, spec, policy="overwrite"
            )
        return MappingResultDTO(batch=_batch_dto(updated), warnings=warnings, template=template)

    # ── 预检 ──────────────────────────────────────────────────
    def run_precheck(self, batch_id: str) -> PrecheckResultDTO:
        batch = self._staging.get_or_raise(batch_id)
        if batch["status"] == "mapped_pending":
            # D-1：预检必须基于已确认的映射
            raise BusinessRuleError(
                ErrorCode.BATCH_STATE_CONFLICT,
                "请先确认字段映射，再进行去重预检",
                detail={"batch_id": batch_id, "status": batch["status"]},
            )
        assert_transition(str(batch["status"]), "precheck")

        rows = self.replay(batch_id)
        labels = self._dedup.label_rows(rows)
        override_rows = self._overrides.row_numbers(batch_id)
        labels = self._dedup.apply_overrides(labels, override_rows)
        summary = self._dedup.summarize(labels)

        with self._uow.begin():
            self._staging.mark_prechecked(
                batch_id,
                new_count=summary[LABEL_NEW],
                dup_count=summary[LABEL_DUP],
                pending_count=summary[LABEL_PENDING],
            )

        return PrecheckResultDTO(
            summary=summary,
            rows=[
                PrecheckRowDTO(
                    row_no=row.row_no,
                    label=labels.get(row.row_no, LABEL_PENDING),  # type: ignore[arg-type]
                    occurred_at=row.occurred_at,
                    amount_cents=row.amount_cents,
                    direction=row.direction,
                    counterparty=row.counterparty,
                    item=row.item,
                    issues=_derive_issues(row),
                    override=row.row_no in override_rows,
                )
                for row in rows
            ],
            snapshot_at=now_iso(),
        )

    # ── 强制新增 ──────────────────────────────────────────────
    def mark_override(self, batch_id: str, row_no: int, reason: str) -> OverrideDTO:
        batch = self._staging.get_or_raise(batch_id)
        if batch["status"] != "prechecked":
            raise BusinessRuleError(
                ErrorCode.BATCH_STATE_CONFLICT,
                "请先完成字段映射与去重预检，再标记强制新增",
                detail={"batch_id": batch_id, "status": batch["status"]},
            )
        total = int(batch["total_rows"])
        if row_no < 1 or row_no > total:
            raise EntryValidationError(
                ErrorCode.INVALID_ENUM_VALUE,
                f"行号必须在 1~{total} 之间（当前 {row_no}）",
                detail={"row_no": row_no, "total_rows": total},
            )

        with self._uow.begin():
            stored = self._overrides.upsert(batch_id, row_no, reason.strip())
        self._events.record("batch.override", {"batch_id": batch_id, "row_no": row_no})
        return OverrideDTO(
            batch_id=batch_id,
            row_no=row_no,
            reason=str(stored["reason"]),
            created_at=str(stored["created_at"]),
        )

    def revoke_override(self, batch_id: str, row_no: int) -> OverrideRevokeDTO:
        self._staging.get_or_raise(batch_id)
        with self._uow.begin():
            removed = self._overrides.delete(batch_id, row_no)
        return OverrideRevokeDTO(removed=removed)

    # ── 丢弃 ──────────────────────────────────────────────────
    def discard(self, batch_id: str) -> BatchDTO:
        """先删文件、后置状态（§4.8）：删不掉就保持原状返回 409，绝不出现"已丢弃但文件还在"。"""
        batch = self._staging.get_or_raise(batch_id)
        assert_transition(str(batch["status"]), "discard")

        self._buffer.delete_with_retry(self._buffer.path_for(str(batch["stored_name"])))
        with self._uow.begin():
            updated = self._staging.mark_discarded(batch_id)
        self._events.record("batch.discarded", {"batch_id": batch_id})
        return _batch_dto(updated)

    # ── 列表与详情 ────────────────────────────────────────────
    def list_batches(
        self, *, status: str | None, page: int, page_size: int, sort: str
    ) -> tuple[list[BatchDTO], int]:
        rows, total = self._staging.list(status=status, page=page, page_size=page_size, sort=sort)
        return [_batch_dto(row) for row in rows], total

    def get_batch_detail(self, batch_id: str) -> BatchDetailDTO:
        batch = self._staging.get_or_raise(batch_id)
        mapped = batch.get("mapped_fields")
        spec: MappingSpec | None = None
        if isinstance(mapped, dict):
            try:
                spec = MappingSpec.model_validate(mapped)
            except ValueError:
                _logger.warning("批次 %s 的 mapped_fields 无法解析", batch_id)

        snapshot = batch.get("mapping_snapshot")
        base = _batch_dto(batch)
        return BatchDetailDTO(
            **base.model_dump(),
            header_row_no=batch["header_row_no"],
            mapped_fields=spec,
            mapping_snapshot=snapshot if isinstance(snapshot, dict) else None,
            parse_meta=_parse_meta_dto(batch.get("parse_meta")),
            report=batch.get("report_json") if isinstance(batch.get("report_json"), dict) else None,
            file_exists=self._buffer.exists(str(batch["stored_name"])),
        )

    def get_batch(self, batch_id: str) -> BatchDTO:
        return _batch_dto(self._staging.get_or_raise(batch_id))

    # ── 缓冲区运维 ────────────────────────────────────────────
    def buffer_usage(self) -> BufferUsageDTO:
        usage = self._buffer.usage()
        threshold = self._buffer_threshold_bytes()
        return BufferUsageDTO(
            file_count=usage.file_count,
            total_bytes=usage.total_bytes,
            threshold=threshold,
            exceeded=usage.total_bytes > threshold,
        )

    def orphans(self) -> list[OrphanFileDTO]:
        return [
            OrphanFileDTO(name=item.name, size=item.size, modified_at=item.modified_at)
            for item in self._buffer.scan_orphans(self._staging.stored_names())
        ]

    def ensure_buffer_dir(self) -> EnsureDirDTO:
        created = self._buffer.ensure_dir()
        return EnsureDirDTO(path=str(self._buffer.buffer_dir), created=created)

    # ── 内部 ──────────────────────────────────────────────────
    def _execute_parse(self, batch: dict[str, Any], adapter: Any | None = None) -> ParseResult:
        stored_name = str(batch["stored_name"])
        if not self._buffer.exists(stored_name):
            raise FileIOError(
                ErrorCode.BUFFER_DIR_MISSING,
                "缓冲区文件已不存在，请重新上传该账单",
                detail={"batch_id": str(batch["id"])},
            )
        chosen = adapter or self._adapter_for(batch)
        result = chosen.parse(self._buffer.path_for(stored_name), self._spec_for(batch))
        if len(result.rows) > MAX_ROWS:
            raise RowLimitExceeded(f"账单共 {len(result.rows)} 行，超过 {MAX_ROWS} 行上限")
        return result

    def _adapter_for(self, batch: dict[str, Any]) -> ParserAdapter:
        name = batch.get("adapter")
        if isinstance(name, str) and name and name in self._parsers:
            return self._parsers.get(name)
        hint = str(batch["channel"]) if batch["channel"] != "other" else None
        return self._parsers.resolve(str(batch["file_name"]), hint)  # type: ignore[arg-type]

    def _spec_for(self, batch: dict[str, Any]) -> MappingSpec | None:
        """重放优先级：``mapping_snapshot``（C3）→ ``mapped_fields``（C2）→ 渠道默认模板。

        注意两者语义不同（§5.2）：``mapping_snapshot`` 是**入库时刻的不可变快照**（I11），
        ``mapped_fields`` 是用户当前的映射（可以改）。C2 只写后者。
        """
        snapshot = batch.get("mapping_snapshot")
        mapped = batch.get("mapped_fields")
        for candidate in (snapshot, mapped):
            if isinstance(candidate, dict):
                try:
                    return MappingSpec.model_validate(candidate)
                except ValueError:
                    _logger.warning("批次 %s 的映射快照损坏，回退到模板", batch.get("id"))
        return self._mapping.get_default_spec(str(batch["channel"]))

    def _mark_failed_quietly(self, batch_id: str, reason: str) -> None:
        """失败留痕；若状态已被并发改动导致流转非法，只记日志，不掩盖原始异常。"""
        try:
            with self._uow.begin():
                self._staging.mark_parse_failed(batch_id, fail_reason=reason)
        except (BusinessRuleError, sqlite3.Error) as exc:
            _logger.warning("批次 %s 标记失败态未生效：%s", batch_id, exc)

    @staticmethod
    def _meta_payload(result: ParseResult) -> dict[str, Any]:
        return {
            "sheet": result.meta.sheet,
            "delimiter": result.meta.delimiter,
            "preamble_rows": result.meta.preamble_rows,
            "header_row_no": result.meta.header_row_no,
            "empty_rows_skipped": result.meta.empty_rows_skipped,
            "issues": result.meta.issues,
            "columns": result.columns,
        }

    @staticmethod
    def _headers_of(rows: list[ParsedRow]) -> list[str]:
        headers: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row.raw_payload:
                if key not in seen:
                    seen.add(key)
                    headers.append(key)
        return headers

    def _buffer_threshold_bytes(self) -> int:
        """阈值来自 ``setting.buffer_size_threshold_mb``（PRD FR-07 规则 4，默认 500MB）。"""
        megabytes = BUFFER_THRESHOLD_MB_DEFAULT
        try:
            row = self._uow.conn.execute(
                "SELECT value FROM setting WHERE key = 'buffer_size_threshold_mb'"
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row is not None:
            try:
                parsed = int(json.loads(str(row[0])))
                if parsed > 0:
                    megabytes = parsed
            except (TypeError, ValueError):
                _logger.warning("缓冲区阈值设置不是整数，使用默认 %dMB", megabytes)
        return megabytes * 1024 * 1024


__all__ = ["ImportOrchestrator", "map_parse_error"]
