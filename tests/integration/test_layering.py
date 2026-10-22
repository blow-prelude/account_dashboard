"""分层约束的静态检查（SDD §2.2）。

规则：

* ``api/routers/**`` 不得 import ``repositories`` 或 ``sqlite3``；
* ``infra/**`` 不得 import ``services`` 或 ``api``；
* ``repositories/**`` 不得 import ``services`` 或 ``api``；
* ``services/**`` 不得 import ``api`` 的**运行时装配**（routers / deps / app_factory）。

``api/deps.py`` 是唯一例外：它必须构造 ``UnitOfWork``，属于装配点而非业务调用。

``services`` 允许 import ``api.errors`` / ``api.response``：SDD §4.3 明确要求业务层
抛出 ``EntryValidationError`` / ``BusinessRuleError`` 等错误族，统一响应也是业务层
组装的返回值。把这两个文件视为「契约模块」而非「接口层实现」，比在 services 里
复制一套异常更不容易漂移（C2 引入，见 C2 分册 §9）。
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "account_dashboard"

LAYER_RULES: dict[str, set[str]] = {
    # 接口层只能调业务层，不得直接触达仓储或 sqlite
    "api": {"repositories"},
    "infra": {"services", "api"},
    "repositories": {"services", "api"},
    "services": {"api"},
}

# 允许的跨层 import（精确到模块，不是整层放开）
ALLOWED_EXCEPTIONS = {
    "api/deps.py": {"repositories"},
}

ALLOWED_CONTRACT_MODULES: dict[str, set[str]] = {
    "services": {"account_dashboard.api.errors", "account_dashboard.api.response"},
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    package = "account_dashboard"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module:
                modules.add(f"{package}.{node.module}")
            elif node.module:
                modules.add(node.module)
            else:
                for alias in node.names:
                    modules.add(f"{package}.{alias.name}")
    return modules


def test_layer_import_rules() -> None:
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        relative = path.relative_to(SRC).as_posix()
        layer = relative.split("/")[0]
        forbidden = LAYER_RULES.get(layer)
        if not forbidden:
            continue
        allowed = ALLOWED_EXCEPTIONS.get(relative, set())
        contract_modules = ALLOWED_CONTRACT_MODULES.get(layer, set())
        for module in _imports(path):
            if module in contract_modules:
                continue
            for banned in forbidden - allowed:
                if module == f"account_dashboard.{banned}" or module.startswith(
                    f"account_dashboard.{banned}."
                ):
                    violations.append(f"{relative} → {module}")
    assert violations == [], f"分层违规：{violations}"


def test_routers_do_not_touch_sqlite() -> None:
    violations = [
        path.name
        for path in (SRC / "api" / "routers").rglob("*.py")
        if "sqlite3" in _imports(path)
    ]
    assert violations == [], f"路由层不得直接使用 sqlite3：{violations}"


def test_no_business_logic_in_infrastructure() -> None:
    """基础设施不得反向依赖业务层（防止 C2 起把 service 塞进 parser）。"""
    violations: list[str] = []
    for path in (SRC / "infra").rglob("*.py"):
        for module in _imports(path):
            if module.startswith("account_dashboard.services"):
                violations.append(f"{path.name} → {module}")
    assert violations == []
