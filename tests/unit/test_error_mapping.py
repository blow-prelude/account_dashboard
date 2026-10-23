"""``error_mapping`` 的翻译契约（合稿 M1 补充）。

infra 层抛 ``InfraError``（字符串码），业务层边界翻成 ``AppError`` 家族。
C3 合稿把 ``raw_naming`` 的直抛 ``TransactionError`` 收敛回 infra 风格
（``RawTableError``），**码值 E3002 与 HTTP 500 必须原样过海** —— 本文件
就是这条不变量的守卫。
"""

from __future__ import annotations

import pytest

from account_dashboard.api.errors import TransactionError
from account_dashboard.infra.errors import InfraError, RawTableError
from account_dashboard.services.error_mapping import to_app_error, translate_infra


def test_raw_table_error_maps_to_e3002_transaction_error() -> None:
    translated = to_app_error(RawTableError("月份格式不合法", detail={"month": "bad"}))

    assert isinstance(translated, TransactionError)
    assert translated.code.value == "E3002"
    assert translated.http_status == 500
    assert translated.detail == {"month": "bad"}


def test_unknown_code_falls_back_to_internal_error() -> None:
    """未知码按系统错误兜底，绝不静默通过（K10：C3 不得新增码值）。"""
    translated = to_app_error(InfraError("没见过", code="E9999"))

    assert translated.code.value == "E5001"


def test_translate_infra_passes_app_error_through() -> None:
    """已是 AppError 的不再翻译（避免双重包装）。"""

    @translate_infra
    def boom() -> None:
        raise RawTableError("x")

    with pytest.raises(TransactionError) as excinfo:
        boom()
    assert excinfo.value.code.value == "E3002"
