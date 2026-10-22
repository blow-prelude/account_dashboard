"""真实样例回归（C2 §6.2，**本周期最重要的一条**）。

期望值来自 C2 §2 的校准事实，逐项相等、不允许"差不多"：

* 微信 707 行文件 → 表头第 18 行（0-based 17）→ 689 行数据；
* 支付宝 693 行文件 → 表头第 24 行（0-based 23）→ 669 行数据；
* 两个方向分布、两个月份分布全部逐项相等；
* 文件内指纹碰撞 0；``empty_rows_skipped == 0``。

行数差 1 意味着某行被静默丢弃，后面所有金额统计都会错 —— 所以这里写死数字，
不用 ``>=``、不用 ``approx``。
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from account_dashboard.infra.parsers.check import build_report, main
from account_dashboard.infra.parsers.registry import ParserRegistry

WECHAT_REPORT = [
    "adapter=wechat_xlsx rows=689 header_row_no=17 encoding=xlsx skipped_empty=0",
    "direction={'expense':613,'income':72,'neutral':4}",
    "months={'2026-06':172,'2026-07':114,'2026-08':153,'2026-09':142,'2026-10':108}",
]
ALIPAY_REPORT = [
    "adapter=alipay_csv rows=669 header_row_no=23 encoding=gb18030 columns=13",
    "direction={'expense':512,'income':2,'neutral':155}",
    "months={'2026-06':101,'2026-07':136,'2026-08':182,'2026-09':143,'2026-10':107}",
]


def test_wechat_regression(fixtures_dir: Path) -> None:
    assert build_report(fixtures_dir / "wechat_sample_sanitized.xlsx") == WECHAT_REPORT


def test_alipay_regression(fixtures_dir: Path) -> None:
    assert build_report(fixtures_dir / "alipay_sample_gb18030.csv") == ALIPAY_REPORT


def test_wechat_empty_rows_and_fingerprints(fixtures_dir: Path) -> None:
    result = ParserRegistry().parse(fixtures_dir / "wechat_sample_sanitized.xlsx")
    assert result.stats.empty_rows_skipped == 0, "数据区不许有空行被跳过"
    assert result.total_rows == 689
    fingerprints = [row.fingerprint for row in result.rows]
    assert all(item is not None for item in fingerprints)
    assert len(set(fingerprints)) == len(fingerprints), "文件内指纹碰撞必须为 0"
    assert result.stats.as_dict() == {}, "样例不该产生行级 issue"


def test_alipay_empty_rows_and_fingerprints(fixtures_dir: Path) -> None:
    result = ParserRegistry().parse(fixtures_dir / "alipay_sample_gb18030.csv")
    assert result.stats.empty_rows_skipped == 0
    fingerprints = [row.fingerprint for row in result.rows]
    assert len(set(fingerprints)) == len(fingerprints)
    assert result.meta["column_count"] == 13
    assert result.meta["columns"][-1] == ""

    row = result.rows[0]
    assert row.amount_cents is not None and row.amount_cents > 0
    assert row.occurred_at is not None
    assert str(row.direction) in {"expense", "income", "neutral"}
    assert row.payload["交易订单号"].endswith("\t"), "订单号尾部 Tab 必须原样进 raw_payload"


def test_check_cli_exit_code(fixtures_dir: Path, capsys) -> None:
    code = main([str(fixtures_dir / "alipay_sample_gb18030.csv")])
    assert code == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ALIPAY_REPORT


def test_full_flow_keeps_transaction_empty(
    client: TestClient, upload, fixtures_dir: Path
) -> None:
    """C2 出口自证：走完 上传 → 解析 → 映射 → 预检，业务表仍是 0 行。"""
    batch = upload(fixtures_dir / "wechat_sample_sanitized.xlsx")
    preview = client.get(f"/api/v1/staging/batches/{batch['id']}/preview").json()["data"]
    mapping = dict(preview["detected_fields"], direction_map={}, amount_scale=1)
    client.put(f"/api/v1/staging/batches/{batch['id']}/mapping", json=mapping)
    precheck = client.post(f"/api/v1/staging/batches/{batch['id']}/precheck").json()["data"]

    assert precheck["summary"] == {"total": 689, "new": 689, "dup": 0, "pending_manual": 0}
    health = client.get("/api/v1/health").json()["data"]
    assert health["db_ok"] is True
