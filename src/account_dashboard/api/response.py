"""统一响应与分页（I6）。

契约：所有路由的 ``response_model`` 均为 ``ApiResponse[X]``，**禁止返回裸对象**。
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

OK_CODE = "OK"


class ApiResponse(BaseModel, Generic[T]):
    code: str = OK_CODE
    data: T | None = None
    message: str = ""


class PageMeta(BaseModel):
    page: int = 1
    page_size: int = 50
    total: int = 0
    total_pages: int = 0

    @classmethod
    def build(cls, page: int, page_size: int, total: int) -> PageMeta:
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        return cls(page=page, page_size=page_size, total=total, total_pages=total_pages)


class Page(BaseModel, Generic[T]):
    items: list[T] = Field(default_factory=list)
    meta: PageMeta = Field(default_factory=PageMeta)


def ok(data: T | None = None, message: str = "") -> ApiResponse[T]:
    return ApiResponse[T](code=OK_CODE, data=data, message=message)


def fail(code: str, message: str, data: T | None = None) -> ApiResponse[T]:
    return ApiResponse[T](code=code, data=data, message=message)
