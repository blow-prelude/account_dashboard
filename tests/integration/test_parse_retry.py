"""C2B.3 失败批次可重试：``id`` 不变、不新增批次行、文件保留。

失败态的四类（编码/表头/空文件/超行数）都必须是"批次 failed + 文件还在"，
否则用户重试时无文件可解析 —— 这是 EX-02/03/04 的核心要求。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.fakes.fake_parser import (
    FakeParser,
    fake_empty_document,
    fake_encoding_error,
    fake_header_error,
    make_rows,
)
from tests.integration.conftest import StagingFlow, count_rows

from account_dashboard.errors import ErrorCode


@pytest.mark.parametrize(
    ("build_parser", "expected_code"),
    [
        (fake_encoding_error, ErrorCode.ENCODING_UNDETECTABLE),
        (fake_header_error, ErrorCode.HEADER_UNRECOGNIZED),
        (fake_empty_document, ErrorCode.EMPTY_FILE),
    ],
)
def test_parse_failure_keeps_batch_and_file(
    api: TestClient,
    flow: StagingFlow,
    parser: FakeParser,
    build_parser,
    expected_code,
) -> None:
    parser.error = build_parser().error

    response = flow.upload()

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == expected_code.value

    batch_id = body["data"]["detail"]["batch_id"]
    detail = flow.detail(batch_id)
    assert detail["status"] == "failed"
    assert detail["fail_reason"]
    assert detail["file_exists"] is True

    listing = api.get("/api/v1/staging/batches").json()["data"]
    assert listing["meta"]["total"] == 1, "失败也只应有一个批次"


def test_retry_succeeds_without_creating_new_batch(
    api: TestClient,
    parser: FakeParser,
    flow: StagingFlow,
) -> None:
    parser.error = fake_encoding_error().error
    failed = flow.upload()
    assert failed.status_code == 422
    batch_id = failed.json()["data"]["detail"]["batch_id"]

    # 修好解析器后重试同一批次
    parser.error = None
    response = api.post(f"/api/v1/staging/batches/{batch_id}/parse")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["batch"]["id"] == batch_id
    assert body["batch"]["status"] == "mapped_pending"
    assert body["batch"]["total_rows"] == 5
    assert body["batch"]["fail_reason"] is None

    listing = api.get("/api/v1/staging/batches").json()["data"]
    assert listing["meta"]["total"] == 1, "重试不得新增批次行"


def test_retry_failure_updates_reason_only(
    api: TestClient, parser: FakeParser, flow: StagingFlow
) -> None:
    parser.error = fake_header_error().error
    batch_id = flow.upload().json()["data"]["detail"]["batch_id"]

    parser.error = fake_empty_document().error
    response = api.post(f"/api/v1/staging/batches/{batch_id}/parse")

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.EMPTY_FILE.value
    detail = flow.detail(batch_id)
    assert detail["status"] == "failed"
    assert "没有数据行" in detail["fail_reason"]


def test_retry_does_not_touch_transaction_table(
    api: TestClient, db, parser: FakeParser, flow: StagingFlow
) -> None:
    parser.error = fake_encoding_error().error
    batch_id = flow.upload().json()["data"]["detail"]["batch_id"]
    parser.error = None
    api.post(f"/api/v1/staging/batches/{batch_id}/parse")

    assert count_rows(db, "transaction") == 0
    assert parser.parse_calls, "重试必须真的重新解析"


def test_preview_after_retry_is_readonly(
    api: TestClient, parser: FakeParser, flow: StagingFlow
) -> None:
    parser.error = fake_encoding_error().error
    batch_id = flow.upload().json()["data"]["detail"]["batch_id"]
    parser.error = None
    api.post(f"/api/v1/staging/batches/{batch_id}/parse")

    before = flow.detail(batch_id)["status"]
    api.get(f"/api/v1/staging/batches/{batch_id}/preview")
    assert flow.detail(batch_id)["status"] == before


def test_parse_uses_registered_adapter_by_name(
    api: TestClient, parser: FakeParser, flow: StagingFlow
) -> None:
    """重放时按 ``staging_batch.adapter`` 取回同一适配器（C2-A §2.5 的 ``get``）。"""
    batch = flow.upload_ok()
    detail = flow.detail(batch["id"])

    assert detail["adapter"] == FakeParser.name
    assert detail["encoding"] == "fake"
    assert detail["total_rows"] == len(make_rows(5))
