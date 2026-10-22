"""统一响应与错误处理器用例（I6）。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from account_dashboard.api.errors import (
    BusinessRuleError,
    EntryValidationError,
    ErrorCode,
    register_exception_handlers,
)


def build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/business")
    def business() -> None:
        raise BusinessRuleError(ErrorCode.BATCH_STATE_CONFLICT, "该批次已入库，无需重复提交")

    @app.get("/entry")
    def entry() -> None:
        raise EntryValidationError(ErrorCode.FILE_TYPE_UNSUPPORTED, "只支持 CSV 或 .xlsx")

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail: db password")

    return app


def test_business_error_shape() -> None:
    client = TestClient(build_app())
    response = client.get("/business")
    assert response.status_code == 409
    body = response.json()
    assert body == {
        "code": "E2002",
        "data": None,
        "message": "该批次已入库，无需重复提交",
    }


def test_entry_error_status_from_code() -> None:
    client = TestClient(build_app())
    response = client.get("/entry")
    assert response.status_code == 415
    assert response.json()["code"] == "E1001"


def test_unhandled_error_hides_traceback() -> None:
    client = TestClient(build_app(), raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "E5001"
    assert "Traceback" not in response.text
    assert "secret internal detail" not in response.text
    assert "data/logs/app.log" in body["message"]


def test_error_code_catalog_size() -> None:
    """37 个错误码与 SDD §4.1.2 对齐；新增必须走契约变更记录。"""
    assert len(ErrorCode) == 37
    for prefix, expected in (("E1", 11), ("E2", 11), ("E3", 5), ("E4", 7), ("E5", 3)):
        assert sum(1 for code in ErrorCode if code.value.startswith(prefix)) == expected
