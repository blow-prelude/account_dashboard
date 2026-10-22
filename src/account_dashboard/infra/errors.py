"""基础设施层异常（infra 自己的错误类型，不依赖 ``api.errors``）。

为什么不在 infra 里直接抛 ``AppError``：分层门禁（``tests/integration/test_layering.py``）
禁止 ``infra`` 反向 import ``api``。因此基础设施只声明「错误码字面量 + 中文文案」，
由业务层统一翻译成 :class:`~account_dashboard.api.errors.AppError`（见
``services/error_mapping.py``）。这样错误码仍然只有一份枚举（在 ``api/errors.py``），
不存在两套码表漂移的风险。
"""

from __future__ import annotations

from typing import Any


class InfraError(Exception):
    """基础设施错误的基类：``code`` 必须是 ``ErrorCode`` 的合法字面量。"""

    code: str = "E5001"
    http_status: int | None = None

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.detail = detail
        if code is not None:
            self.code = code
        super().__init__(message)


class FileTypeError(InfraError):
    """E1001：扩展名不受支持。"""

    code = "E1001"


class EncodingDetectionError(InfraError):
    """E1002：无法识别编码。"""

    code = "E1002"


class HeaderUnrecognizedError(InfraError):
    """E1003：表头不可识别。"""

    code = "E1003"


class NoDataRowsError(InfraError):
    """E1004：没有数据行。"""

    code = "E1004"


class FileTooLargeError(InfraError):
    """E1005：文件超过 5MB。"""

    code = "E1005"


class RowLimitError(InfraError):
    """E1006：数据行超过 50000。"""

    code = "E1006"


class DiskFullError(InfraError):
    """E4001：磁盘余量不足（507）。"""

    code = "E4001"


class FileWriteError(InfraError):
    """E4002：写文件失败。"""

    code = "E4002"


class FileDeleteError(InfraError):
    """E4003：删除文件失败（文件被占用等）。"""

    code = "E4003"


class BufferDirError(InfraError):
    """E4004：缓冲区目录不可用。"""

    code = "E4004"
