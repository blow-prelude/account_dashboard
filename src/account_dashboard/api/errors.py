"""HTTP 异常处理器（**只做投影**：领域错误码 → HTTP 状态 + 三段式响应）。

C2 起 ``ErrorCode`` / ``AppError`` 及其子类搬到 ``account_dashboard.errors``（中性叶子模块，
见 C2 合稿 §3.2 / K10），否则 ``services`` 想抛 ``E1007`` 就必须 import ``api``，
会被 ``tests/integration/test_layering.py`` 的分层门禁拦下。

本模块保留三件事：

1. 四个异常处理器（``AppError`` / 参数校验 / 框架 HTTPException / 兜底 500）；
2. 从 ``account_dashboard.errors`` 原样 re-export，保证 C1 的既有 import 不返工；
3. 参数校验错误到错误码的映射（分页参数 → ``E1010``，其余 → ``E1008``）。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from account_dashboard.api.response import ApiResponse, fail
from account_dashboard.errors import (
    DEFAULT_STATUS,
    AppError,
    BusinessRuleError,
    EntryValidationError,
    ErrorCode,
    FileIOError,
    TransactionError,
)
from account_dashboard.infra.logger import get_logger

_logger = get_logger("api")

__all__ = [
    "DEFAULT_STATUS",
    "AppError",
    "BusinessRuleError",
    "EntryValidationError",
    "ErrorCode",
    "FileIOError",
    "TransactionError",
    "register_exception_handlers",
]

# 分页参数出错时用 E1010，其余参数（枚举/路径/边界）统一 E1008。
_PAGINATION_LOCS = frozenset({"page", "page_size"})


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
    if any(str(part) in _PAGINATION_LOCS for error in errors for part in error.get("loc", ())):
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
