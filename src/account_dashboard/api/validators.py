"""入口校验（SDD §4.1.4）：只做「请求形状合法吗」，不碰业务。

放在 ``api`` 层而不是 service：这类校验的语义是「请求本身有问题」，
与「业务规则不允许」分开之后，错误码 1xxx / 2xxx 的边界才不会含糊。
"""

from __future__ import annotations

from pathlib import Path

from account_dashboard.api.errors import EntryValidationError, ErrorCode
from account_dashboard.infra.buffer_file import ALLOWED_EXTENSIONS, MAX_FILE_BYTES
from account_dashboard.infra.raw_naming import RAW_MONTH_RE

ALLOWED_EXT = ALLOWED_EXTENSIONS
ALLOWED_MIME = frozenset(
    {
        "text/csv",
        "application/csv",
        "text/plain",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",  # 浏览器对本地文件常见兜底
        "multipart/form-data",
    }
)
PAGE_SIZE_RANGE = (10, 200)


def validate_upload_meta(file_name: str, content_type: str | None) -> None:
    """扩展名 + MIME；大小与行数的硬限制在落盘/解析环节兜底（流式）。"""
    extension = Path(file_name).suffix.lower()
    if extension not in ALLOWED_EXT:
        raise EntryValidationError(
            ErrorCode.FILE_TYPE_UNSUPPORTED,
            "只支持 CSV 或 Excel(.xlsx) 文件，请重新导出",
            detail={"file_name": file_name, "allowed": sorted(ALLOWED_EXT)},
        )
    normalized = (content_type or "").split(";")[0].strip().lower()
    if normalized and normalized not in ALLOWED_MIME:
        raise EntryValidationError(
            ErrorCode.FILE_TYPE_UNSUPPORTED,
            "只支持 CSV 或 Excel(.xlsx) 文件，请重新导出",
            detail={"content_type": normalized, "allowed": sorted(ALLOWED_MIME)},
        )


def validate_declared_size(declared_size: int) -> None:
    if declared_size > MAX_FILE_BYTES:
        raise EntryValidationError(
            ErrorCode.FILE_TOO_LARGE,
            f"文件超过 {MAX_FILE_BYTES // (1024 * 1024)}MB，请按月份分批导出",
            detail={"max_bytes": MAX_FILE_BYTES},
        )


def validate_page(page: int, page_size: int) -> None:
    low, high = PAGE_SIZE_RANGE
    if page < 1:
        raise EntryValidationError(ErrorCode.INVALID_PAGINATION, "页码必须从 1 开始")
    if not low <= page_size <= high:
        raise EntryValidationError(
            ErrorCode.INVALID_PAGINATION, f"每页条数必须在 {low}~{high} 之间"
        )


def validate_month(month: str) -> str:
    """``/raw/{yyyy_mm}`` 的路径参数：``YYYY_MM``（无 ``raw_`` 前缀，K2）。"""
    if not RAW_MONTH_RE.match(month):
        raise EntryValidationError(
            ErrorCode.INVALID_ENUM_VALUE,
            "月份格式应为 YYYY_MM（如 2026_06）",
            detail={"month": month},
        )
    return month


def validate_limit(limit: int, *, maximum: int) -> int:
    if limit < 1:
        raise EntryValidationError(ErrorCode.INVALID_PAGINATION, "预览条数必须大于 0")
    return min(limit, maximum)
