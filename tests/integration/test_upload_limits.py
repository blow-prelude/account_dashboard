"""C2B.3 上传上限：6MB → 413 E1005；50001 行 → 422 E1006。

两条上限走的是不同层，必须分开验证：

* **字节数**在入口（``validators``）与落盘（``buffer_file``）各拦一次 —— 声明的
  Content-Length 可以撒谎，所以落盘必须按真实写入字节数再判一次；
* **行数**只能在解析后判（跨过 5 万行说明用户该按月拆分导出了）。
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.fakes.fake_parser import FakeParser, make_rows
from tests.integration.conftest import StagingFlow, buffer_files

from account_dashboard.errors import AppError, ErrorCode
from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.limits import MAX_FILE_BYTES, MAX_ROWS


def test_oversized_upload_is_rejected_at_entry(api: TestClient, flow: StagingFlow, paths) -> None:
    oversized = b"a" * (MAX_FILE_BYTES + 1024)

    response = flow.upload(oversized)

    assert response.status_code == 413
    assert response.json()["code"] == ErrorCode.FILE_TOO_LARGE.value
    assert buffer_files(paths) == []
    assert api.get("/api/v1/staging/batches").json()["data"]["meta"]["total"] == 0


def test_stream_size_limit_enforced_even_if_declared_small(tmp_path: Path) -> None:
    """声明 10 字节、实际 6MB：落盘层必须自己拦（客户端可撒谎）。"""
    directory = tmp_path / "buffer"
    directory.mkdir()
    manager = BufferFileManager(directory, min_free_bytes=0)

    with pytest.raises(AppError) as excinfo:
        manager.save_stream(io.BytesIO(b"b" * (MAX_FILE_BYTES + 1)), "big.csv", 10)

    assert excinfo.value.code is ErrorCode.FILE_TOO_LARGE
    assert list(directory.iterdir()) == []


def test_too_many_rows_marks_batch_failed(
    api: TestClient, db, parser: FakeParser, flow: StagingFlow, paths
) -> None:
    parser._rows = make_rows(MAX_ROWS + 1)  # noqa: SLF001 - 用例直接构造超限批次

    response = flow.upload()

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == ErrorCode.ROW_LIMIT_EXCEEDED.value
    assert "按月" in body["message"]

    batch_id = body["data"]["detail"]["batch_id"]
    detail = flow.detail(batch_id)
    assert detail["status"] == "failed"
    assert "50000" in (detail["fail_reason"] or "")
    assert detail["file_exists"] is True, "失败批次必须保留文件供重试"


def test_unsupported_extension(tmp_path: Path) -> None:
    from account_dashboard.api.validators import validate_upload_meta

    with pytest.raises(AppError) as excinfo:
        validate_upload_meta("bill.pdf", "application/pdf", 10)

    assert excinfo.value.code is ErrorCode.FILE_TYPE_UNSUPPORTED
    assert excinfo.value.http_status == 415
