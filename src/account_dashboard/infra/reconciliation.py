"""启动对账（C3-B 升级为写动作；SDD §7.6 四步，顺序不可换）。

C1 起这里只做只读清点（``raw_*`` 与入库都还不存在）。C3-B 把它升级为
**带自愈动作**的对账，接口（``ReconciliationReport`` 的前四个字段）保持不变
—— 只允许加字段，不许改字段（FZ-1，``/health.backlog`` 消费前四个）。

四步（顺序即语义，测试用 spy 锁定）：

| 步 | 动作 | 失败处理 |
|----|------|----------|
| ① | 中断批次重置：``ingesting`` → ``prechecked``，命中即 WARN（D-8 保险丝） | 失败仅告警 |
| ② | 补删：``ingested`` + ``flag=1`` 逐条删（**一次尝试**）；成功清零、失败入队 | 单条失败继续 |
| ③ | 不一致检测：``ingested`` + ``flag=0`` + 文件仍存在 → WARN + 入队，**不自动删** | 人工确认 |
| ④ | 孤儿扫描：只报告（EX-13 要求用户确认后才可清理） | 只报告 |

对账**不阻塞启动**（SDD §2.3）：任何一步抛异常只记 WARN 后继续下一步，
任何文件删不掉只影响该文件 —— 阻塞启动反而让用户进不去界面处理。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field

from account_dashboard.infra.buffer_file import PARTIAL_SUFFIXES, BufferFileManager
from account_dashboard.infra.logger import get_logger
from account_dashboard.infra.paths import DataPaths
from account_dashboard.repositories.cleanup_repo import CleanupRepo
from account_dashboard.repositories.database import Database

_logger = get_logger("reconciliation")

# 对账第 ④ 步的"已知集合"排除项：已入库 / 已丢弃批次的文件按说已经没了，
# 还留在缓冲区就是异常，值得报告（用户面的 /staging/orphans 用全量口径，C2 冻结）
_TERMINAL_BATCH_STATUSES = ("ingested", "discarded")

# 第 ③ 步入队用的理由（与第 ② 步的补删失败区分开，运维要靠它判断性质）
_INCONSISTENT_REASON = "对账不一致：已入库且删除意图已完成，但文件仍存在"


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """FZ-1 冻结的前四个字段；其余为 C3-B 新增（只加不改）。"""

    interrupted_batches: int = 0
    pending_deletes: int = 0
    orphans: int = 0
    missing_buffer_dir: bool = False
    # ── C3-B 新增（additive）──
    inconsistent_batches: int = 0
    deleted_files: int = 0
    enqueued_files: int = 0
    orphan_names: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class _StepResult:
    """单步结果：主计数 + 可选文件名清单 + 副计数（② 的成功删除数）。"""

    count: int = 0
    names: tuple[str, ...] = ()
    side: int = 0


def run_startup_reconciliation(database: Database, paths: DataPaths) -> ReconciliationReport:
    """执行四步对账；**任何一步失败都不阻塞启动**（调用方已再包一层兜底）。"""
    buffer = BufferFileManager(paths.buffer_dir)
    repo = CleanupRepo(database.conn)
    missing_dir = not paths.buffer_dir.is_dir()

    # ① 中断批次重置（D-8：恒命中 0 条是正常的，命中即缺陷信号）
    interrupted = _run_step("中断批次重置", lambda: _reset_interrupted(repo))

    # ② 补删（一次尝试；失败直接入队交给用户手动 retry，不在启动时重试 3 次）
    pending = _run_step("补删", lambda: _complete_pending_deletes(repo, buffer), skip=missing_dir)
    # 报告里的「待补删」取自愈**之后**的存量：① ② 跑完还欠着的，才是要人盯的
    pending_deletes = _count_quietly(repo)

    # ③ 不一致检测（只 WARN + 入队，绝不自动删）—— 目录缺失时照样跑：
    # buffer.exists() 对缺失目录恒 False，自然不会误报
    inconsistent = _run_step("不一致检测", lambda: _detect_inconsistent(repo, buffer))

    # ④ 孤儿扫描（只报告）
    orphans = _run_step("孤儿扫描", lambda: _scan_orphans(repo, buffer), skip=missing_dir)

    report = ReconciliationReport(
        interrupted_batches=interrupted.count,
        pending_deletes=pending_deletes,
        orphans=orphans.count,
        missing_buffer_dir=missing_dir,
        inconsistent_batches=inconsistent.count,
        deleted_files=pending.side,
        enqueued_files=pending.count,
        orphan_names=orphans.names,
    )
    _log_summary(report)
    return report


# ── 四步（每个都是可被 spy 替换的模块级函数）─────────────────────
def _reset_interrupted(repo: CleanupRepo) -> int:
    """① ``ingesting`` → ``prechecked``；命中说明有人在事务外改过状态，必须 WARN。"""
    count = repo.reset_interrupted()
    if count:
        _logger.warning("发现 %s 个中断批次，已置回待确认（异常信号：状态在事务外被修改）", count)
    return count


def _complete_pending_deletes(repo: CleanupRepo, buffer: BufferFileManager) -> _StepResult:
    """② 逐条补删；成功清零，失败入队。单条失败不影响下一条。"""
    deleted = 0
    enqueued = 0
    for item in repo.pending_delete_batches():
        path = buffer.path_for(item.stored_name)
        if buffer.delete_with_retry(path, attempts=1):
            repo.clear_pending_delete(item.batch_id)
            deleted += 1
            _logger.info("启动补删成功：批次 %s，文件 %s", item.batch_id, item.stored_name)
        else:
            repo.enqueue(
                batch_id=item.batch_id,
                file_path=str(path),
                reason="启动补删失败：文件被占用或无权限",
            )
            enqueued += 1
            _logger.warning("启动补删失败，已入待清理队列：批次 %s", item.batch_id)
    return _StepResult(count=enqueued, side=deleted)


def _detect_inconsistent(repo: CleanupRepo, buffer: BufferFileManager) -> int:
    """③ 已入库 + flag=0 + 文件仍存在 → WARN + 入队，**不自动删**（人工确认）。"""
    found = 0
    for item in repo.inconsistent_batches():
        if not buffer.exists(item.stored_name):
            continue
        found += 1
        repo.enqueue(
            batch_id=item.batch_id,
            file_path=str(buffer.path_for(item.stored_name)),
            reason=_INCONSISTENT_REASON,
        )
        _logger.warning(
            "对账不一致：批次 %s 已入库且删除意图已完成，但文件 %s 仍存在（不自动删，已入队）",
            item.batch_id,
            item.stored_name,
        )
    return found


def _scan_orphans(repo: CleanupRepo, buffer: BufferFileManager) -> _StepResult:
    """④ 孤儿扫描：只报告，不自动删（EX-13 要求用户确认）。

    已知集合比用户面口径更严：排除已入库 / 已丢弃批次（它们的文件按说已经没了）。
    """
    known = repo.stored_names(exclude=_TERMINAL_BATCH_STATUSES)
    orphans = [
        item for item in buffer.scan_orphans(known) if not item.name.endswith(PARTIAL_SUFFIXES)
    ]
    return _StepResult(count=len(orphans), names=tuple(item.name for item in orphans))


# ── 基础设施 ────────────────────────────────────────────────────
def _run_step(
    name: str,
    step: Callable[[], _StepResult | int],
    *,
    skip: bool = False,
) -> _StepResult:
    """单步隔离：抛异常只记 WARN，绝不影响后续步与启动本身。"""
    if skip:
        _logger.info("对账步骤「%s」已跳过（缓冲区目录缺失）", name)
        return _StepResult()
    try:
        result = step()
    except Exception as exc:  # noqa: BLE001 - 对账不阻塞启动是硬约束
        _logger.warning("对账步骤「%s」失败，已忽略（不影响启动）：%s", name, exc)
        return _StepResult()
    return result if isinstance(result, _StepResult) else _StepResult(count=result)


def _count_quietly(repo: CleanupRepo) -> int:
    try:
        return repo.count_pending_deletes()
    except sqlite3.Error as exc:  # pragma: no cover - 表缺失只可能出现在异常库
        _logger.warning("对账查询失败：%s", exc)
        return 0


def _log_summary(report: ReconciliationReport) -> None:
    if (
        report.interrupted_batches
        or report.pending_deletes
        or report.orphans
        or report.missing_buffer_dir
        or report.inconsistent_batches
    ):
        _logger.warning(
            "启动对账：中断批次=%s 待补删=%s（已删 %s / 入队 %s）不一致=%s 孤儿=%s 缺目录=%s",
            report.interrupted_batches,
            report.pending_deletes,
            report.deleted_files,
            report.enqueued_files,
            report.inconsistent_batches,
            report.orphans,
            report.missing_buffer_dir,
        )
    else:
        _logger.info("启动对账：无异常")
