"""上传与自动解析（I-UP-01，FR-01/02，EX-01/02/04/05）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from account_dashboard.repositories.database import Database

PREFIX = "/api/v1/staging"


def _count_transactions(db: Database) -> int:
    return db.scalar_int('SELECT COUNT(*) FROM "transaction"')


def test_upload_creates_batch_and_auto_parses(
    client: TestClient, upload, fixtures_dir: Path
) -> None:
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv", channel="alipay")
    assert batch["status"] == "mapped_pending"
    assert batch["total_rows"] == 669
    assert batch["encoding"] == "gb18030"
    assert batch["adapter"] == "alipay_csv"
    assert batch["header_row_no"] == 23
    assert batch["channel"] == "alipay"
    assert batch["file_size"] > 0
    assert batch["file_exists"] is True
    assert batch["parse_meta"]["empty_rows_skipped"] == 0
    assert batch["parse_meta"]["preamble_rows"] == 23

    detail = client.get(f"{PREFIX}/batches/{batch['id']}").json()["data"]
    assert detail["parse_meta"]["column_count"] == 13


def test_upload_wechat_xlsx(client: TestClient, upload, fixtures_dir: Path) -> None:
    batch = upload(fixtures_dir / "wechat_sample_sanitized.xlsx")
    assert batch["status"] == "mapped_pending"
    assert batch["total_rows"] == 689
    assert batch["encoding"] == "xlsx"
    assert batch["adapter"] == "wechat_xlsx"
    assert batch["channel"] == "wechat", "渠道由适配器识别后回填（上传时未指定）"
    assert batch["header_row_no"] == 17


def test_upload_persists_across_client(fresh_client, upload, fixtures_dir: Path) -> None:
    """I-UP-01：刷新（新 TestClient，等价于重启进程）后批次仍在。"""
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv")
    with fresh_client() as another:
        body = another.get(f"{PREFIX}/batches/{batch['id']}").json()
        assert body["code"] == "OK"
        assert body["data"]["status"] == "mapped_pending"
        listed = another.get(f"{PREFIX}/batches").json()["data"]
        assert [item["id"] for item in listed["items"]] == [batch["id"]]


def test_unsupported_extension(client: TestClient, tmp_path: Path) -> None:
    target = tmp_path / "账单.txt"
    target.write_text("x", encoding="utf-8")
    with target.open("rb") as handle:
        response = client.post(
            f"{PREFIX}/batches", files={"file": (target.name, handle, "text/plain")}
        )
    assert response.status_code == 415
    body = response.json()
    assert body["code"] == "E1001"
    assert "CSV" in body["message"]


def test_oversize_file_rejected(client: TestClient, tmp_path: Path) -> None:
    target = tmp_path / "big.csv"
    target.write_bytes(b"a,b\n" + b"1,2\n" * 1_500_000)  # ≈6MB
    with target.open("rb") as handle:
        response = client.post(
            f"{PREFIX}/batches", files={"file": (target.name, handle, "text/csv")}
        )
    assert response.status_code == 413
    assert response.json()["code"] == "E1005"


def test_broken_encoding_marks_failed(
    client: TestClient, upload, fixtures_dir: Path, db: Database
) -> None:
    batch = upload(fixtures_dir / "broken_encoding.csv")
    assert batch["status"] == "failed"
    assert batch["fail_reason"] and "编码" in batch["fail_reason"]
    assert _count_transactions(db) == 0


def test_retry_parse_keeps_single_batch(
    client: TestClient, upload, fixtures_dir: Path
) -> None:
    """失败批次可重试，且重试不会重复建批次（C2.3 验收）。"""
    batch = upload(fixtures_dir / "broken_encoding.csv")
    assert batch["status"] == "failed"

    for _ in range(2):
        retry = client.post(f"{PREFIX}/batches/{batch['id']}/parse")
        assert retry.status_code == 422
        assert retry.json()["code"] == "E1002"

    listed = client.get(f"{PREFIX}/batches").json()["data"]["items"]
    assert len(listed) == 1, "重试解析不得重复建批次"
    assert listed[0]["id"] == batch["id"]


def test_reparse_after_success_conflicts(
    client: TestClient, upload, fixtures_dir: Path
) -> None:
    """已解析（mapped_pending）的批次不允许重解析，避免映射被无声清掉。"""
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv")
    response = client.post(f"{PREFIX}/batches/{batch['id']}/parse")
    assert response.status_code == 409
    assert response.json()["code"] == "E2002"


def test_retry_parse_on_failed_returns_e1002(
    client: TestClient, upload, fixtures_dir: Path
) -> None:
    batch = upload(fixtures_dir / "broken_encoding.csv")
    response = client.post(f"{PREFIX}/batches/{batch['id']}/parse")
    assert response.status_code == 422
    assert response.json()["code"] == "E1002"
    detail = client.get(f"{PREFIX}/batches/{batch['id']}").json()["data"]
    assert detail["status"] == "failed"


def test_no_header_marks_failed_with_e1003(
    client: TestClient, upload, fixtures_dir: Path
) -> None:
    batch = upload(fixtures_dir / "no_header.csv")
    assert batch["status"] == "failed"
    detail = client.get(f"{PREFIX}/batches/{batch['id']}")
    assert detail.json()["data"]["status"] == "failed"
    retry = client.post(f"{PREFIX}/batches/{batch['id']}/parse")
    assert retry.status_code == 422
    assert retry.json()["code"] == "E1003"


def test_unknown_batch_returns_e2001(client: TestClient) -> None:
    response = client.get(f"{PREFIX}/batches/not-exists")
    assert response.status_code == 404
    assert response.json()["code"] == "E2001"


def test_list_filters_and_pagination(client: TestClient, upload, fixtures_dir: Path) -> None:
    upload(fixtures_dir / "alipay_sample_gb18030.csv")
    upload(fixtures_dir / "wechat_sample_sanitized.xlsx")

    all_batches = client.get(f"{PREFIX}/batches").json()["data"]
    assert all_batches["meta"]["total"] == 2
    assert len(all_batches["items"]) == 2

    only_wechat = client.get(
        f"{PREFIX}/batches", params={"status": "mapped_pending"}
    ).json()["data"]
    assert only_wechat["meta"]["total"] == 2

    none = client.get(f"{PREFIX}/batches", params={"status": "ingested"}).json()["data"]
    assert none["meta"]["total"] == 0

    bad = client.get(f"{PREFIX}/batches", params={"page_size": 5})
    assert bad.status_code == 422
    assert bad.json()["code"] == "E1010"


def test_invalid_channel_rejected(client: TestClient, upload, fixtures_dir: Path) -> None:
    with (fixtures_dir / "alipay_sample_gb18030.csv").open("rb") as handle:
        response = client.post(
            f"{PREFIX}/batches",
            files={"file": ("a.csv", handle, "text/csv")},
            data={"channel": "unknown"},
        )
    assert response.status_code == 422
    assert response.json()["code"] == "E1008"


@pytest.mark.parametrize("limit", [0, -1])
def test_preview_limit_validation(
    client: TestClient, upload, fixtures_dir: Path, limit: int
) -> None:
    batch = upload(fixtures_dir / "alipay_sample_gb18030.csv")
    response = client.get(f"{PREFIX}/batches/{batch['id']}/preview", params={"limit": limit})
    assert response.status_code == 422
    assert response.json()["code"] == "E1010"
