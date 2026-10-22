"""错误码与可预期异常（**中性叶子模块**，见 C2 合稿 §3.2 / K10）。

为什么单独放在包根而不是 ``api/errors.py``：

* C2 起 ``services`` 必须抛 ``AppError``（``E1007``/``E2002``/``E2003``…），而分层门禁
  禁止 ``services → api``；
* 错误码本身是**领域词汇**（"批次状态冲突"），不属于 HTTP 层，HTTP 状态只是它的
  一个投影（:data:`DEFAULT_STATUS`）；
* 该模块不 import 任何 ``account_dashboard.*`` 子模块，任何层都可以安全引用。

错误码是**契约**：37 个值与 SDD §4.1.2 / §6.5 一一对应，新增必须走 ``CONTRACT-CHANGELOG``。
``message`` 面向非技术用户，中文、可执行（告诉用户下一步做什么）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


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


__all__ = [
    "DEFAULT_STATUS",
    "AppError",
    "BusinessRuleError",
    "EntryValidationError",
    "ErrorCode",
    "FileIOError",
    "TransactionError",
]
