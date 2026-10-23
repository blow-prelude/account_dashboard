"""DTO 跨模块引用的装配（``models/__init__.py`` 的守卫）。

``BatchDetailDTO.report`` ↔ ``IngestReportDTO`` 是前向引用，由包初始化补齐。
这条用例用**子进程**验证两种 import 顺序都能构造带报告的 DTO —— 顺带防止
后人把 ``models/__init__.py`` 的接线"优化"掉。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_STAGING_FIRST = """
from account_dashboard.models.staging import BatchDetailDTO

dto = BatchDetailDTO(
    id="b1", file_name="f.csv", file_size=1, channel="alipay",
    status="ingested", created_at="2026-10-22T10:00:00", updated_at="2026-10-22T10:00:00",
    report={"batch_id": "b1", "total": 1, "inserted": 1, "skipped_dup": 0,
            "skipped_invalid": 0, "pending": 1, "monthly": {"raw_2026_10": 1},
            "files_deleted": True, "cleanup_pending": False, "cleanup_id": None,
            "finished_at": "2026-10-22T10:00:01"},
)
assert dto.report is not None and dto.report.inserted == 1, dto.report
assert dto.report.monthly == {"raw_2026_10": 1}
print("ok")
"""

_INGEST_FIRST = """
from account_dashboard.models.ingest import IngestReportDTO
from account_dashboard.models.staging import BatchDetailDTO

report = IngestReportDTO(
    batch_id="b1", total=1, inserted=1, skipped_dup=0, skipped_invalid=0,
    pending=1, monthly={"raw_2026_10": 1}, files_deleted=True,
    cleanup_pending=False, cleanup_id=None, finished_at="2026-10-22T10:00:01",
)
dto = BatchDetailDTO(
    id="b1", file_name="f.csv", file_size=1, channel="alipay",
    status="ingested", created_at="2026-10-22T10:00:00", updated_at="2026-10-22T10:00:00",
    report=report,
)
assert dto.report is report
print("ok")
"""


def _run(script: str) -> None:
    result = subprocess.run(  # noqa: S603 - 固定脚本、无外部输入
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_staging_first_import_order() -> None:
    _run(_STAGING_FIRST)


def test_ingest_first_import_order() -> None:
    _run(_INGEST_FIRST)
