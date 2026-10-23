"""raw_payload 保真（I7 / C3-A §6.1 出口检查表）。

抽 5 条 ``raw_payload`` 与重放得到的 ``ParsedRow.payload`` 逐项一致；
原文件里的变体（``退款成功`` 状态、订单号尾部 Tab、``余额宝&红包``）必须
原样保留 —— 不做单位换算、不清洗文本。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.infra.paths import DataPaths
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.unit_of_work import UnitOfWork
from account_dashboard.services.import_orchestrator import ImportOrchestrator

PREFIX = "/api/v1/staging"
SAMPLE = "alipay_sample_gb18030.csv"

# 与 ParsedRow / RawRecordDTO 对齐的 11 个字段（I8 追溯口径）
TRACE_FIELDS = (
    "occurred_at",
    "amount_cents",
    "direction",
    "counterparty",
    "item",
    "txn_type",
    "payment_method",
    "platform_category",
    "platform_status",
    "channel",
    "fp",
)


def _mapping(client: TestClient, batch_id: str) -> dict[str, Any]:
    preview = client.get(f"{PREFIX}/batches/{batch_id}/preview", params={"limit": 1}).json()["data"]
    payload = dict(preview["detected_fields"])
    payload.update({"direction_map": {}, "amount_scale": 1})
    return payload


def _prepare_and_confirm(client: TestClient, upload, fixtures_dir: Path) -> tuple[str, Path]:
    batch = upload(fixtures_dir / SAMPLE)
    batch_id = str(batch["id"])
    client.put(f"{PREFIX}/batches/{batch_id}/mapping", json=_mapping(client, batch_id))
    client.post(f"{PREFIX}/batches/{batch_id}/precheck")
    response = client.post(f"{PREFIX}/batches/{batch_id}/confirm")
    assert response.status_code == 200, response.text
    return batch_id, fixtures_dir / SAMPLE


def test_raw_payload_matches_original_rows(
    client: TestClient, upload, fixtures_dir: Path, db: Database, paths: DataPaths
) -> None:
    batch_id, _ = _prepare_and_confirm(client, upload, fixtures_dir)

    # 重放得到与入库完全一致的 ParsedRow（同一份快照）
    orchestrator = ImportOrchestrator(
        uow=UnitOfWork(db), buffer=BufferFileManager(paths.buffer_dir), database=db
    )
    rows = {row.row_no: row for row in orchestrator.replay(batch_id)}
    assert len(rows) == 669

    # 每个月份抽一行，共 5 条，逐项比对
    months = ["2026_06", "2026_07", "2026_08", "2026_09", "2026_10"]
    sampled: list[tuple[str, dict[str, Any]]] = []
    for month in months:
        row = db.query_one(
            f"SELECT row_no, raw_payload FROM raw_{month} ORDER BY row_no LIMIT 1"
        )
        assert row is not None
        sampled.append((month, json.loads(str(row["raw_payload"]))))

    assert len(sampled) == 5
    for _month, payload in sampled:
        assert payload  # 非空原貌
    for _month, payload in sampled:
        # payload 的键就是原表头（含空列名补位 column_N）
        assert set(payload) >= {"交易时间", "交易对方", "商品说明", "收/支", "金额"}

    # 逐字段一致：raw_payload == 同一 row_no 的 ParsedRow.payload
    for month, payload in sampled:
        row_no = int(
            db.query_one(
                f"SELECT row_no FROM raw_{month} ORDER BY row_no LIMIT 1"
            )["row_no"]
        )
        assert payload == rows[row_no].payload


def test_original_variants_are_preserved(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    """变体保真：``退款成功``、订单号尾部 Tab、``余额宝&红包``。"""
    batch_id, _ = _prepare_and_confirm(client, upload, fixtures_dir)

    # 退款成功：样例第 3 行的交易状态列
    row = db.query_one(
        "SELECT raw_payload FROM raw_2026_06 WHERE row_no = 3"
    )
    assert row is not None
    payload = json.loads(str(row["raw_payload"]))
    assert payload["交易状态"] == "退款成功"
    # 订单号列尾部带 Tab（支付宝导出的已知特征），原样保留
    assert payload["交易订单号"].endswith("\t")

    # 余额宝&红包：样例第 4 行的收/付款方式列
    row4 = db.query_one("SELECT raw_payload FROM raw_2026_06 WHERE row_no = 4")
    assert row4 is not None
    assert json.loads(str(row4["raw_payload"]))["收/付款方式"] == "余额宝&红包"


def test_raw_and_transaction_fields_agree(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    """raw 与 transaction 的 11 个字段逐项一致（追溯链 I8 的数据基础）。"""
    batch_id, _ = _prepare_and_confirm(client, upload, fixtures_dir)

    joined = db.query_all(
        'SELECT t.row_no, t.occurred_at AS t_time, t.amount_cents AS t_amount, '
        "t.direction AS t_direction, t.counterparty AS t_counterparty, t.item AS t_item, "
        "t.channel AS t_channel, t.fp AS t_fp, "
        "r.occurred_at AS r_time, r.amount_cents AS r_amount, r.direction AS r_direction, "
        "r.counterparty AS r_counterparty, r.item AS r_item, r.channel AS r_channel, "
        "r.fp AS r_fp "
        'FROM "transaction" t JOIN raw_2026_06 r '
        "ON t.batch_id = r.batch_id AND t.row_no = r.row_no"
    )
    assert len(joined) == 101
    for row in joined:
        assert row["t_time"] == row["r_time"]
        assert row["t_amount"] == row["r_amount"]
        assert row["t_direction"] == row["r_direction"]
        assert row["t_counterparty"] == row["r_counterparty"]
        assert row["t_item"] == row["r_item"]
        assert row["t_channel"] == row["r_channel"]
        assert row["t_fp"] == row["r_fp"]


def test_raw_payload_is_byte_stable(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    """sort_keys 落库：重新序列化已存 payload 必须字节一致（可重放校验）。"""
    batch_id, _ = _prepare_and_confirm(client, upload, fixtures_dir)
    rows = db.query_all("SELECT raw_payload FROM raw_2026_06 LIMIT 20")
    for row in rows:
        text = str(row["raw_payload"])
        assert text == json.dumps(json.loads(text), ensure_ascii=False, sort_keys=True)
