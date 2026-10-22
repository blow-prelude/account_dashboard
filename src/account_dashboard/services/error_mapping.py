"""把基础设施异常翻译成对外错误（唯一翻译点）。

分层门禁禁止 ``infra`` import ``api``，但错误码枚举只有一份（``api/errors.py``）。
于是在业务层做一次翻译：``InfraError.code``（字符串）→ ``ErrorCode`` 枚举 → ``AppError`` 家族。
好处是 infra 可以独立测试，且不存在第二套码表。
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from account_dashboard.api.errors import (
    AppError,
    BusinessRuleError,
    EntryValidationError,
    ErrorCode,
    FileIOError,
    TransactionError,
)
from account_dashboard.infra.errors import InfraError

F = TypeVar("F", bound=Callable[..., Any])

# 错误码前缀 → 语义分类（与 SDD §4.1.2 的分组一致）
_PREFIX_CLASS: dict[str, type[AppError]] = {
    "E1": EntryValidationError,
    "E2": BusinessRuleError,
    "E3": TransactionError,
    "E4": FileIOError,
    "E5": AppError,
}


def to_app_error(exc: InfraError) -> AppError:
    try:
        code = ErrorCode(exc.code)
    except ValueError:  # 未知码：按系统错误兜底，绝不静默
        code = ErrorCode.INTERNAL_ERROR
    error_class = _PREFIX_CLASS.get(exc.code[:2], AppError)
    return error_class(code, exc.message, detail=exc.detail)


def translate_infra(func: F) -> F:
    """同步方法的翻译装饰器。"""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except AppError:
            raise
        except InfraError as exc:
            raise to_app_error(exc) from exc

    return wrapper  # type: ignore[return-value]


def translate_infra_async(func: F) -> F:
    """异步方法的翻译装饰器（``UploadFile.read`` 是协程）。"""

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except AppError:
            raise
        except InfraError as exc:
            raise to_app_error(exc) from exc

    return wrapper  # type: ignore[return-value]
