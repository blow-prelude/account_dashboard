"""去重预检（SDD §7.4 / FR-04，EX-21/22）。

**只读**是硬要求（FR-04 规则 6）：本模块只执行 ``SELECT``，不写 ``transaction`` /
``raw_*`` 一张表；批次上的 ``new/dup/pending_count`` 由上层写（那是预检结果的缓存）。

三分类语义：

* ``dup``  —— 指纹命中库内已有记录；
* ``new``  —— 未命中，或用户对该行「强制新增」（``override_mark`` 留痕）；
* ``pending_manual`` —— 时间/金额解析失败，指纹为 ``None``，**不参与比对**（EX-21）。

> 文件内的重复（同一文件两行指纹相同）不在本模块比对范围内：C2 的实测样例碰撞为 0，
> 跨批次重复才是真问题；而 C3 入库时的二次去重（EX-22）会以库内实际结果为准。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field

from account_dashboard.infra.parsers.models import ParsedRow
from account_dashboard.models.enums import DedupLabel

CHUNK_SIZE = 500


@dataclass(frozen=True, slots=True)
class DedupRowResult:
    row_no: int
    label: DedupLabel
    override: bool = False


@dataclass(frozen=True, slots=True)
class DedupResult:
    rows: list[DedupRowResult] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    missing_fingerprint: int = 0


class DedupChecker:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def find_existing(self, fingerprints: Iterable[str]) -> set[str]:
        """按 500 个一批查库（SQLite 变量上限 999，留足余量）。"""
        unique = list(dict.fromkeys(fingerprints))
        hits: set[str] = set()
        for start in range(0, len(unique), CHUNK_SIZE):
            chunk = unique[start : start + CHUNK_SIZE]
            placeholders = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f'SELECT fp FROM "transaction" WHERE fp IN ({placeholders})',  # noqa: S608
                tuple(chunk),
            ).fetchall()
            hits.update(str(row["fp"]) for row in rows if row["fp"] is not None)
        return hits

    def check(
        self,
        rows: Sequence[ParsedRow],
        overrides: Collection[int] = (),
    ) -> DedupResult:
        override_set = set(overrides)
        existing = self.find_existing(
            row.fingerprint for row in rows if row.fingerprint is not None
        )

        results: list[DedupRowResult] = []
        summary = {"total": 0, "new": 0, "dup": 0, "pending_manual": 0}
        missing = 0

        for row in rows:
            summary["total"] += 1
            if row.fingerprint is None:
                missing += 1
                label = DedupLabel.PENDING_MANUAL
                summary["pending_manual"] += 1
                results.append(DedupRowResult(row_no=row.row_no, label=label))
                continue

            overridden = row.row_no in override_set
            if row.fingerprint in existing and not overridden:
                label = DedupLabel.DUP
                summary["dup"] += 1
            else:
                label = DedupLabel.NEW
                summary["new"] += 1
            results.append(
                DedupRowResult(row_no=row.row_no, label=label, override=overridden)
            )

        return DedupResult(rows=results, summary=summary, missing_fingerprint=missing)
