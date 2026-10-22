"""入口校验（C2-B §4.7，SDD §4.1.4）。

顺序与错误码固定（§4.1 的 ①②）：

* 扩展名 / MIME / 声明大小 → ``E1001``(415) / ``E1005``(413) / ``E1004``(422)；
* 分页越界 → ``E1010``(422)；
* 枚举与排序 → ``E1008``(422)。

阈值常量来自 ``account_dashboard.limits``：同一个数字被 infra/services/api 三处使用，
各写一份必然出现"接口说 5MB、落盘说 6MB"的边界缺陷。
"""

from __future__ import annotations

from pathlib import Path

from account_dashboard.errors import EntryValidationError, ErrorCode
from account_dashboard.limits import (
    MAX_FILE_BYTES,
    PAGE_SIZE_MAX,
    PAGE_SIZE_MIN,
    PREVIEW_DEFAULT_LIMIT,
    PREVIEW_MAX_LIMIT,
)
from account_dashboard.models.internal import Channel

ALLOWED_EXT = frozenset({".csv", ".xlsx"})
ALLOWED_MIME = frozenset(
    {
        "text/csv",
        "application/csv",
        "text/plain",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",  # 浏览器对 .csv 常见兜底
    }
)
CHANNELS: tuple[str, ...] = ("wechat", "alipay", "bank", "other")
BATCH_STATUSES: tuple[str, ...] = (
    "uploaded",
    "mapped_pending",
    "prechecked",
    "ingesting",
    "ingested",
    "discarded",
    "failed",
)
BATCH_SORTS = frozenset({"created_at", "-created_at"})


def validate_upload_meta(
    file_name: str, content_type: str | None, declared_size: int | None
) -> None:
    suffix = Path(file_name or "").suffix.lower()
    if suffix not in ALLOWED_EXT:
        raise EntryValidationError(
            ErrorCode.FILE_TYPE_UNSUPPORTED,
            "只支持 CSV 或 xlsx 账单文件，请重新导出",
            detail={"file_name": file_name},
        )
    if content_type and content_type.split(";")[0].strip().lower() not in ALLOWED_MIME:
        raise EntryValidationError(
            ErrorCode.FILE_TYPE_UNSUPPORTED,
            "文件类型不被支持，请确认是 CSV 或 xlsx 账单",
            detail={"content_type": content_type},
        )
    if declared_size is not None:
        if declared_size <= 0:
            raise EntryValidationError(ErrorCode.EMPTY_FILE, "文件是空的，请重新导出账单后再上传")
        if declared_size > MAX_FILE_BYTES:
            raise EntryValidationError(
                ErrorCode.FILE_TOO_LARGE,
                f"文件超过 {MAX_FILE_BYTES // (1024 * 1024)}MB，请按月拆分后再上传",
                detail={"declared_size": declared_size},
            )


def validate_page(page: int, page_size: int) -> None:
    if page < 1:
        raise EntryValidationError(
            ErrorCode.INVALID_PAGINATION, "页码从 1 开始", detail={"page": page}
        )
    if not PAGE_SIZE_MIN <= page_size <= PAGE_SIZE_MAX:
        raise EntryValidationError(
            ErrorCode.INVALID_PAGINATION,
            f"每页条数必须在 {PAGE_SIZE_MIN}~{PAGE_SIZE_MAX} 之间",
            detail={"page_size": page_size},
        )


def validate_sort(sort: str | None, allowed: frozenset[str] = BATCH_SORTS) -> str:
    candidate = (sort or "-created_at").strip()
    if candidate not in allowed:
        raise EntryValidationError(
            ErrorCode.INVALID_ENUM_VALUE,
            "排序只支持 " + " / ".join(sorted(allowed)),
            detail={"sort": candidate},
        )
    return candidate


def validate_status(status: str | None) -> str | None:
    if status is None or status == "":
        return None
    if status not in BATCH_STATUSES:
        raise EntryValidationError(
            ErrorCode.INVALID_ENUM_VALUE,
            "批次状态不合法，请从筛选项中选择",
            detail={"status": status},
        )
    return status


def validate_channel(channel: str | None) -> Channel | None:
    if channel is None or channel == "":
        return None
    if channel not in CHANNELS:
        raise EntryValidationError(
            ErrorCode.INVALID_ENUM_VALUE,
            "渠道只能是微信 / 支付宝 / 银行 / 其他",
            detail={"channel": channel},
        )
    return channel  # type: ignore[return-value]


def clamp_preview_limit(limit: int | None) -> int:
    """``limit`` 只做上限截断（1000 → 50），不报错 —— 预览是只读操作，宽容比严格好。"""
    if limit is None:
        return PREVIEW_DEFAULT_LIMIT
    return max(1, min(int(limit), PREVIEW_MAX_LIMIT))


__all__ = [
    "ALLOWED_EXT",
    "ALLOWED_MIME",
    "BATCH_SORTS",
    "BATCH_STATUSES",
    "CHANNELS",
    "clamp_preview_limit",
    "validate_channel",
    "validate_page",
    "validate_sort",
    "validate_status",
    "validate_upload_meta",
]
