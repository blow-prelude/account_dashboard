"""解析异常族（C2-A §2.2，**不带 ErrorCode**）。

``infra`` 不得 import ``api``，HTTP 语义属于 B 线：由
:func:`account_dashboard.services.import_orchestrator.map_parse_error` 把四个子类
投影成 ``E1002 / E1003 / E1004 / E1006``。

例外语义（合稿 M4 的关键判定）：

* 四个子类 = **批次失败**（``status=failed``，可重试）；
* 行级问题（金额/时间解析不出）= ``ParseIssue``，批次照常成功 —— 二者不可混为一谈，
  否则用户会看到"整批失败但文件没问题"。
"""

from __future__ import annotations


class ParseError(Exception):
    """解析失败的基类；``message`` 面向使用者，中文可执行。"""

    def __init__(self, message: str = "") -> None:
        self.message = message or "文件解析失败，请检查文件内容"
        super().__init__(self.message)


class EncodingDetectFailed(ParseError):
    """编码探测失败（→ E1002 / 422）。"""


class HeaderNotRecognized(ParseError):
    """表头无法识别（→ E1003 / 422），文案应引导用户手动映射。"""


class EmptyDocument(ParseError):
    """文件里没有数据行（→ E1004 / 422）。"""


class RowLimitExceeded(ParseError):
    """行数超上限（→ E1006 / 422）。"""


__all__ = [
    "EmptyDocument",
    "EncodingDetectFailed",
    "HeaderNotRecognized",
    "ParseError",
    "RowLimitExceeded",
]
