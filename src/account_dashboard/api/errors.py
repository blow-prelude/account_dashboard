"""错误码与全局异常处理器（SDD §4.1.2 / §6.5 / §12）。

错误码是**契约**：37 个值与 SDD 一一对应，新增必须走 ``CONTRACT-CHANGELOG``。
``message`` 面向非技术用户，中文、可执行（告诉用户下一步做什么）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from account_dashboard.api.response import ApiResponse, fail
from account_dashboard.infra.logger import get_logger

_logger = get_logger("api")


class ErrorCode(StrEnum):
    # ── 1xxx 入口校验 ──────────────────────────────────────
    FILE_TYPE_UNSUPPORTED = "E1001"
    ENCODING_UNDETECTABLE = "E1002"
    HEADER_UNRECOGNIZED = "E1003"
    EMPTY_FILE = "E1004"
    FILE_TOO_LARGE = "E1005"
    ROW_LIMIT_EXCEEDED = "E1006"
    MAPPING_INCOMPLETE = "E1007"
    INVALID_ENUM_VALUE = "E1008"
    INVALID_PERIOD = "E1009"
    INVALID_PAGINATION = "E1010"
    INVALID_DATA_DIR = "E1011"
    # ── 2xxx 业务规则 ──────────────────────────────────────
    BATCH_NOT_FOUND = "E2001"
    BATCH_STATE_CONFLICT = "E2002"
    DUPLICATE_TEMPLATE = "E2003"
    FINGERPRINT_INCOMPLETE = "E2004"
    CATEGORY_IN_USE = "E2005"
    CATEGORY_NOT_FOUND = "E2006"
    RULE_INVALID = "E2007"
    SETTING_INVALID = "E2008"
    FIELD_NOT_EDITABLE = "E2009"
    TRANSACTION_NOT_FOUND = "E2010"
    RECALC_NO_SCOPE = "E2011"
    # ── 3xxx 数据/事务 ─────────────────────────────────────
    INGEST_TX_FAILED = "E3001"
    RAW_TABLE_ERROR = "E3002"
    DB_BUSY = "E3003"
    DB_CORRUPT = "E3004"
    MIGRATION_FAILED = "E3005"
    # ── 4xxx 文件 IO ──────────────────────────────────────
    DISK_FULL = "E4001"
    FILE_WRITE_FAILED = "E4002"
    FILE_DELETE_FAILED = "E4003"
    BUFFER_DIR_MISSING = "E4004"
    BACKUP_INVALID = "E4005"
    BACKUP_RESTORE_FAILED = "E4006"
    BACKUP_ROLLBACK_FAILED = "E4007"
    # ── 5xxx 系统 ─────────────────────────────────────────
    INTERNAL_ERROR = "E5001"
    DATA_DIR_UNWRITABLE = "E5002"
    PORT_IN_USE = "E5003"


DEFAULT_STATUS: dict[ErrorCode, int] = {
    ErrorCode.FILE_TYPE_UNSUPPORTED: 415,
    ErrorCode.ENCODING_UNDETECTABLE: 422,
    ErrorCode.HEADER_UNRECOGNIZED: 422,
    ErrorCode.EMPTY_FILE: 422,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.ROW_LIMIT_EXCEEDED: 422,
    ErrorCode.MAPPING_INCOMPLETE: 400,
    ErrorCode.INVALID_ENUM_VALUE: 422,
    ErrorCode.INVALID_PERIOD: 422,
    ErrorCode.INVALID_PAGINATION: 422,
    ErrorCode.INVALID_DATA_DIR: 422,
    ErrorCode.BATCH_NOT_FOUND: 404,
    ErrorCode.BATCH_STATE_CONFLICT: 409,
    ErrorCode.DUPLICATE_TEMPLATE: 409,
    ErrorCode.FINGERPRINT_INCOMPLETE: 422,
    ErrorCode.CATEGORY_IN_USE: 409,
    ErrorCode.CATEGORY_NOT_FOUND: 404,
    ErrorCode.RULE_INVALID: 400,
    ErrorCode.SETTING_INVALID: 400,
    ErrorCode.FIELD_NOT_EDITABLE: 422,
    ErrorCode.TRANSACTION_NOT_FOUND: 404,
    ErrorCode.RECALC_NO_SCOPE: 422,
    ErrorCode.INGEST_TX_FAILED: 500,
    ErrorCode.RAW_TABLE_ERROR: 500,
    ErrorCode.DB_BUSY: 409,
    ErrorCode.DB_CORRUPT: 500,
    ErrorCode.MIGRATION_FAILED: 500,
    ErrorCode.DISK_FULL: 507,
    ErrorCode.FILE_WRITE_FAILED: 500,
    ErrorCode.FILE_DELETE_FAILED: 409,
    ErrorCode.BUFFER_DIR_MISSING: 500,
    ErrorCode.BACKUP_INVALID: 422,
    ErrorCode.BACKUP_RESTORE_FAILED: 500,
    ErrorCode.BACKUP_ROLLBACK_FAILED: 500,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.DATA_DIR_UNWRITABLE: 500,
    ErrorCode.PORT_IN_USE: 500,
}


class AppError(Exception):
    """业务可预期错误；``detail`` 只用于排障，不直接展示给用户。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        http_status: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.http_status = http_status or DEFAULT_STATUS[code]
        self.message = message
        self.detail = detail
        super().__init__(message)


class EntryValidationError(AppError):
    """1xxx：入口校验失败。"""


class BusinessRuleError(AppError):
    """2xxx：业务规则冲突。"""


class TransactionError(AppError):
    """3xxx：数据/事务失败。"""


class FileIOError(AppError):
    """4xxx：文件读写失败。"""


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unhandled)


def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    payload = fail(
        code=exc.code.value,
        message=exc.message,
        data={"detail": exc.detail} if exc.detail else None,
    )
    return JSONResponse(status_code=exc.http_status, content=payload.model_dump())


def _handle_validation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = exc.errors()
    code = ErrorCode.INVALID_ENUM_VALUE
    if any("page" in [str(part) for part in error.get("loc", ())] for error in errors):
        code = ErrorCode.INVALID_PAGINATION
    payload = fail(
        code=code.value,
        message="请求参数不合法，请检查后重试",
        data={
            "errors": [
                {
                    "loc": "/".join(str(part) for part in error.get("loc", ())),
                    "msg": str(error.get("msg", "")),
                    "type": str(error.get("type", "")),
                }
                for error in errors
            ]
        },
    )
    return JSONResponse(status_code=422, content=payload.model_dump())


def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    """框架层 404/405 也保持三段式结构，避免前端出现两套错误格式。"""
    assert isinstance(exc, StarletteHTTPException)
    status = exc.status_code
    code = ErrorCode.INTERNAL_ERROR if status >= 500 else ErrorCode.INVALID_ENUM_VALUE
    message = "接口不存在，请检查地址" if status == 404 else str(exc.detail)
    payload: ApiResponse[Any] = fail(code=code.value, message=message)
    return JSONResponse(status_code=status, content=payload.model_dump())


def _handle_unhandled(request: Request, exc: Exception) -> JSONResponse:
    _logger.exception("未处理异常 %s %s", request.method, request.url.path)
    payload: ApiResponse[Any] = fail(
        code=ErrorCode.INTERNAL_ERROR.value,
        message="服务内部错误，详情见 data/logs/app.log",
    )
    return JSONResponse(status_code=500, content=payload.model_dump())
