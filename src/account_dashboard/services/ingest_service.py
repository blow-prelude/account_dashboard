"""确认入库单事务（SDD §7.5，C3-A 的唯一写路径）。

事务边界（照抄 SDD §7.5，不许改）::

    BEGIN IMMEDIATE
      ├─ UPDATE staging_batch SET status='ingesting', ingest_started_at=?
      │    WHERE id=? AND status='prechecked'          ← 幂等闸门，rowcount==0 → E2002
      ├─ replay(mapping_snapshot) → rows                ← 用快照重放，不重读用户当前映射
      ├─ 二次 find_fp_in(rows)                          ← 预检到入库之间可能有新数据（EX-22）
      ├─ CREATE TABLE IF NOT EXISTS raw_YYYY_MM × N     ← 按行覆盖的月份按需建
      ├─ INSERT INTO raw_YYYY_MM ...  (分批 executemany，500/批)
      ├─ INSERT INTO "transaction" ... (分批 executemany，500/批)
      └─ UPDATE staging_batch SET status='ingested', report_json=?, mapping_snapshot=?,
           committed_at=?, pending_delete_flag=1
    COMMIT
      ↓（事务外，绝不能放在事务里）
    sink.on_committed(batch_id, file_path)              ← 唯一注入点，B 线实现

三条不可协商的理由：

1. **闸门必须在事务内**：崩溃时 SQLite 自动回滚，批次仍是 ``prechecked``
   （PRD 9.2 收口规则 4 / D-8），不会留下永久 ``ingesting`` 脏状态；
2. **删文件必须在事务外**：文件系统不在事务里，先提交再删，最坏结果是
   "数据在、文件也在"（由 B 线的启动对账补删）；
3. **DDL 必须在事务内**：``CREATE TABLE`` 参与回滚，"注入异常后 raw 表无残留"
   这条断言才成立。

本模块**禁止出现** ``unlink`` / ``os.remove``（grep 门禁见
``tests/integration/test_write_path_gates.py``）：事务外的删除只经
``sink.on_committed`` 一个出口。
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from account_dashboard.api.errors import (
    AppError,
    BusinessRuleError,
    ErrorCode,
    FileIOError,
    TransactionError,
)
from account_dashboard.infra.buffer_file import MIN_DISK_FREE_BYTES, BufferFileManager
from account_dashboard.infra.clock import now_iso
from account_dashboard.infra.event_log import EventLogger
from account_dashboard.infra.logger import get_logger
from account_dashboard.infra.parsers.models import ParsedRow
from account_dashboard.infra.raw_naming import month_key, table_name
from account_dashboard.models.enums import BatchAction, BatchStatus, Direction
from account_dashboard.models.ingest import (
    IngestReportDetailDTO,
    IngestReportDTO,
    SkippedRowDTO,
    truncate_raw,
)
from account_dashboard.repositories.override_repo import OverrideRepo, OverrideRow
from account_dashboard.repositories.raw_repo import RawRow, RawTableManager, dump_raw_payload
from account_dashboard.repositories.staging_repo import BatchRow, StagingRepo
from account_dashboard.repositories.transaction_repo import (
    BatchHook,
    TransactionInsert,
    TransactionRepo,
)
from account_dashboard.repositories.unit_of_work import UnitOfWork
from account_dashboard.services import batch_guard
from account_dashboard.services.error_mapping import translate_infra
from account_dashboard.services.import_orchestrator import ImportOrchestrator
from account_dashboard.services.ingest_ports import DeleteFailureSink

_logger = get_logger("ingest")

FreeSpaceProbe = Callable[[], int]


@dataclass(frozen=True, slots=True)
class _Classification:
    """二次去重的结果（EX-22：以入库时库内的实际状态为准）。"""

    accepted: list[ParsedRow]
    overrides: dict[int, OverrideRow]
    skipped: list[SkippedRowDTO]
    skipped_dup: int
    skipped_invalid: int


class IngestService:
    """``confirm`` / ``report`` 两个动作的全部业务逻辑（端点层只做投影）。"""

    def __init__(
        self,
        *,
        uow: UnitOfWork,
        orchestrator: ImportOrchestrator,
        sink: DeleteFailureSink,
        buffer: BufferFileManager,
        data_dir: Path | None = None,
        free_space_probe: FreeSpaceProbe | None = None,
        min_free_bytes: int = MIN_DISK_FREE_BYTES,
        insert_batch_hook: BatchHook | None = None,
        events: EventLogger | None = None,
    ) -> None:
        self._uow = uow
        self._orchestrator = orchestrator
        self._sink = sink
        self._buffer = buffer
        self._data_dir = data_dir
        self._free_space_probe = free_space_probe
        self._min_free_bytes = min_free_bytes
        # 故障注入 1 的注入点：None 时生产路径零开销
        self._insert_batch_hook = insert_batch_hook
        self._events = events or EventLogger()
        conn = uow.conn
        self._staging = StagingRepo(conn)
        self._txn = TransactionRepo(conn)
        self._raw = RawTableManager()
        self._overrides = OverrideRepo(conn)

    # ══ 确认入库 ══════════════════════════════════════════════
    @translate_infra
    def confirm(self, batch_id: str) -> IngestReportDTO:
        batch = self._load(batch_id)
        # 第一道判断（用户视角）：non-prechecked → E2002，且不写任何东西
        batch_guard.assert_transition(batch.status_enum, BatchAction.CONFIRM)
        # 磁盘预检在事务外：宁可不开事务，也不开一半再回滚（§4.7 阶段二）
        self._ensure_free_space()
        snapshot = self._orchestrator.resolve_snapshot(batch)

        try:
            with self._uow.begin():
                # 幂等闸门（真正的并发防线）：rowcount==0 → E2002
                if self._staging.try_enter_ingesting(batch_id) == 0:
                    raise BusinessRuleError(
                        ErrorCode.BATCH_STATE_CONFLICT,
                        "该批次已入库，无需重复提交",
                        detail={"batch_id": batch_id},
                    )
                rows = self._orchestrator.replay(batch_id, snapshot)
                outcome = self._classify(rows, batch_id)
                monthly = self._write_accepted(batch, outcome)
                # 第二跳（事务内部，内存校验）：ingesting → ingested 必须存在于矩阵
                batch_guard.assert_transition(
                    BatchStatus.INGESTING, BatchAction.INGEST, target=BatchStatus.INGESTED
                )
                committed_at = now_iso()
                report_json = json.dumps(
                    self._report_payload(
                        total=len(rows),
                        outcome=outcome,
                        monthly=monthly,
                        finished_at=committed_at,
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                )
                # D-5：把"用来入库的那份"快照原样回写，此后该字段只读
                self._staging.finish_ingest(
                    batch_id,
                    report_json=report_json,
                    mapping_snapshot=json.dumps(
                        snapshot.to_dict(), ensure_ascii=False, sort_keys=True
                    ),
                    committed_at=committed_at,
                )
        except sqlite3.OperationalError as exc:
            raise _translate_operational(exc, batch_id) from exc
        except sqlite3.Error as exc:
            raise TransactionError(
                ErrorCode.INGEST_TX_FAILED,
                "入库失败，数据已回滚，请重试",
                detail={"batch_id": batch_id, "error": str(exc)},
            ) from exc
        except AppError:
            raise
        except Exception as exc:  # noqa: BLE001 - 事务内任何意外都必须回滚并转为 E3001
            _logger.exception("批次 %s 入库失败", batch_id)
            raise TransactionError(
                ErrorCode.INGEST_TX_FAILED,
                "入库过程中发生错误，数据已回滚，请重试",
                detail={"batch_id": batch_id, "error": str(exc)},
            ) from exc

        # ── 事务外：删除意图（I9，唯一注入点） ──────────────────
        delete_outcome = self._sink.on_committed(
            batch_id, str(self._buffer.path_for(batch.stored_name))
        )
        self._events.record(
            "batch.ingested",
            {
                "batch_id": batch_id,
                "count": len(rows),
                "inserted": len(outcome.accepted),
                "skipped_dup": outcome.skipped_dup,
                "pending": len(outcome.accepted),
            },
        )
        return IngestReportDTO(
            batch_id=batch_id,
            total=len(rows),
            inserted=len(outcome.accepted),
            skipped_dup=outcome.skipped_dup,
            skipped_invalid=outcome.skipped_invalid,
            # C3 写入行恒为 pending；C4 分类后这个数字才会小于 inserted
            pending=len(outcome.accepted),
            monthly=monthly,
            files_deleted=delete_outcome.deleted,
            cleanup_pending=not delete_outcome.deleted,
            cleanup_id=delete_outcome.cleanup_id,
            finished_at=committed_at,
        )

    # ══ 导入报告 ══════════════════════════════════════════════
    def report(self, batch_id: str, *, include_skipped: bool = False) -> IngestReportDetailDTO:
        """读 ``report_json`` 还原报告；``skipped[]`` 仅 ``include_skipped=true`` 时填充。"""
        batch = self._load(batch_id)
        if not batch.report_json:
            raise BusinessRuleError(
                ErrorCode.BATCH_STATE_CONFLICT,
                "批次尚未入库，没有导入报告",
                detail={"batch_id": batch_id, "status": batch.status},
            )
        base = IngestReportDTO.from_stored(
            batch.report_json,
            pending_delete_flag=batch.pending_delete_flag,
            committed_at=batch.committed_at,
        )
        if base is None:  # pragma: no cover - 上面已判空
            raise BusinessRuleError(
                ErrorCode.BATCH_STATE_CONFLICT,
                "批次尚未入库，没有导入报告",
                detail={"batch_id": batch_id, "status": batch.status},
            )
        skipped: list[SkippedRowDTO] = []
        if include_skipped:
            data = json.loads(batch.report_json)
            skipped = [SkippedRowDTO(**item) for item in data.get("skipped") or []]
        return IngestReportDetailDTO(**base.model_dump(), skipped=skipped)

    # ══ 内部 ══════════════════════════════════════════════════
    def _load(self, batch_id: str) -> BatchRow:
        batch = self._staging.get(batch_id)
        if batch is None:
            raise BusinessRuleError(
                ErrorCode.BATCH_NOT_FOUND, "批次不存在或已被清理，请刷新列表"
            )
        return batch

    def _classify(self, rows: list[ParsedRow], batch_id: str) -> _Classification:
        """二次去重（EX-22 的真正含义：预检是快照，入库是当下）。

        * ``fp`` 命中且用户**没有**标 override → ``skipped_dup``；
        * override 的语义是"用户说这行不是重复"，命中时**绕过 fp 判断**（P0-1）；
        * 时间/金额不可解析 → ``skipped_invalid``，既不写 raw 也不写 transaction
          （D-6：文件会被删，报告是这批行唯一的留痕）。
        """
        dups = self._txn.find_fp_in([row.fingerprint for row in rows if row.fingerprint])
        overrides = self._overrides.list_by_batch(batch_id)
        accepted: list[ParsedRow] = []
        skipped: list[SkippedRowDTO] = []
        skipped_dup = 0
        skipped_invalid = 0
        for row in rows:
            if not row.is_valid:
                skipped_invalid += 1
                skipped.append(_invalid_detail(row))
                continue
            if row.fingerprint in dups and row.row_no not in overrides:
                skipped_dup += 1
                skipped.append(SkippedRowDTO(row_no=row.row_no, reason="DUP"))
                continue
            accepted.append(row)
        return _Classification(
            accepted=accepted,
            overrides=overrides,
            skipped=skipped,
            skipped_dup=skipped_dup,
            skipped_invalid=skipped_invalid,
        )

    def _write_accepted(self, batch: BatchRow, outcome: _Classification) -> dict[str, int]:
        """双写：先 raw 后 transaction，都按 500 行分批（顺序不可换，见模块文档）。"""
        if not outcome.accepted:
            # EX-09：全重复批次不建任何表，但仍走完流程置 ingested（批次要归档）
            return {}
        conn = self._uow.conn
        imported_at = now_iso()
        channel = str(batch.channel_enum)
        groups: dict[str, list[RawRow]] = {}
        for row in outcome.accepted:
            occurred_at, amount_cents, direction = _write_values(row)
            month = month_key(occurred_at)
            groups.setdefault(month, []).append(
                RawRow(
                    batch_id=batch.id,
                    row_no=row.row_no,
                    occurred_at=occurred_at,
                    amount_cents=amount_cents,
                    direction=direction,
                    counterparty=row.counterparty,
                    item=row.item,
                    txn_type=row.txn_type,
                    payment_method=row.payment_method,
                    platform_category=row.platform_category,
                    platform_status=row.platform_status,
                    channel=channel,
                    fp=row.fingerprint,
                    raw_payload=dump_raw_payload(row.payload),
                    imported_at=imported_at,
                )
            )
        monthly: dict[str, int] = {}
        for month, raw_rows in groups.items():
            self._raw.ensure_table(conn, month)
            monthly[table_name(month)] = self._raw.write_rows(conn, month, raw_rows)
        # transaction 侧用生成器惰性构造：不把 accepted 二次物化成第二个 list
        self._txn.insert_many(
            self._iter_transactions(batch, outcome, channel=channel),
            batch_hook=self._insert_batch_hook,
        )
        return monthly

    def _iter_transactions(
        self, batch: BatchRow, outcome: _Classification, *, channel: str
    ) -> Iterator[TransactionInsert]:
        for row in outcome.accepted:
            occurred_at, amount_cents, direction = _write_values(row)
            override = outcome.overrides.get(row.row_no)
            yield TransactionInsert(
                occurred_at=occurred_at,
                amount_cents=amount_cents,
                direction=str(direction),
                batch_id=batch.id,
                row_no=row.row_no,
                counterparty=row.counterparty,
                item=row.item,
                txn_type=row.txn_type,
                payment_method=row.payment_method,
                channel=channel,
                fp=row.fingerprint,
                override_reason=override.reason if override is not None else None,
                override_at=override.created_at if override is not None else None,
            )

    @staticmethod
    def _report_payload(
        *, total: int, outcome: _Classification, monthly: dict[str, int], finished_at: str
    ) -> dict[str, Any]:
        """``report_json`` 的完整结构（D-6 的 ``skipped[]`` 明细进这里）。

        不存 ``files_deleted`` / ``cleanup_*``：那两个字段的唯一事实源是
        ``pending_delete_flag``（B 线维护），存副本只会漂移。读取时由
        ``IngestReportDTO.from_stored`` 从旗标推导。
        """
        return {
            "total": total,
            "inserted": len(outcome.accepted),
            "skipped_dup": outcome.skipped_dup,
            "skipped_invalid": outcome.skipped_invalid,
            "pending": len(outcome.accepted),
            "monthly": monthly,
            "finished_at": finished_at,
            "skipped": [item.model_dump() for item in outcome.skipped],
        }

    def _ensure_free_space(self) -> None:
        free = self._free_bytes()
        if free is None:
            return
        if free < self._min_free_bytes:
            raise FileIOError(
                ErrorCode.DISK_FULL,
                "磁盘空间不足，未开始入库，请清理磁盘后重试",
                detail={"free_bytes": free, "min_free_bytes": self._min_free_bytes},
            )

    def _free_bytes(self) -> int | None:
        if self._free_space_probe is not None:
            return self._free_space_probe()
        if self._data_dir is None:
            return None
        try:
            return shutil.disk_usage(self._data_dir).free
        except OSError:  # pragma: no cover - 目录被移走等极端情况
            _logger.warning("磁盘余量探测失败：%s", self._data_dir)
            return None


def _write_values(row: ParsedRow) -> tuple[str, int, Direction]:
    """入库三要素（时间 / 金额 / 方向）。``is_valid`` 已保证三者非空，这里是
    mypy 可见的窄化点，也是"不可解析行绝不写库"的最后一道防线。"""
    occurred_at = row.occurred_at_iso
    amount_cents = row.amount_cents
    direction = row.direction
    if occurred_at is None or amount_cents is None or direction is None:
        raise TransactionError(
            ErrorCode.RAW_TABLE_ERROR,
            "交易时间、金额或方向缺失，无法入库",
            detail={"row_no": row.row_no},
        )
    return occurred_at, amount_cents, direction


def _invalid_detail(row: ParsedRow) -> SkippedRowDTO:
    """不可解析行的留痕：原因取**实际缺失的字段**，附原始值（截断 64 字符）。"""
    if row.occurred_at is None:
        reason, field = "TIME_PARSE", "occurred_at"
    else:
        reason, field = "AMOUNT_PARSE", "amount"
    issue = next((item for item in row.issues if str(item.code) == reason), None)
    return SkippedRowDTO(
        row_no=row.row_no,
        reason=reason,
        field=field,
        raw=truncate_raw(issue.raw_value) if issue is not None else None,
    )


def _translate_operational(exc: sqlite3.OperationalError, batch_id: str) -> AppError:
    """``sqlite3.OperationalError`` 分级：磁盘满 → 507；锁冲突 → 409；其余 → 500。"""
    text = str(exc).casefold()
    if "full" in text or "disk" in text:
        return FileIOError(
            ErrorCode.DISK_FULL,
            "磁盘空间不足，入库已回滚，请清理磁盘后重试",
            detail={"batch_id": batch_id, "error": str(exc)},
        )
    if "locked" in text or "busy" in text:
        return TransactionError(
            ErrorCode.DB_BUSY,
            "数据库正忙，请稍后重试",
            detail={"batch_id": batch_id, "error": str(exc)},
        )
    return TransactionError(
        ErrorCode.INGEST_TX_FAILED,
        "入库失败，数据已回滚，请重试",
        detail={"batch_id": batch_id, "error": str(exc)},
    )


__all__ = ["IngestService"]
