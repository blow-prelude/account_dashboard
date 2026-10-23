"""写路径 CI 门禁（C3-A §2 评审硬规则 / §6.3 两条 grep）。

这些是**架构不变量**，靠人盯不住，必须进 CI：

1. ``UPDATE staging_batch`` 只允许出现在 ``staging_repo.py`` 与
   ``cleanup_repo.py``（后者只准含 ``pending_delete_flag`` / 中断重置）；
2. ``mapping_snapshot`` 的赋值只允许出现在 ``update_precheck`` / ``finish_ingest``
   （置值）与 ``update_after_parse`` / ``reset_precheck``（作废置 NULL）—— D-5：
   入库冻结之后任何人不得再写它；
3. ``ingest_service.py`` 全文无 ``unlink`` / ``os.remove``（删文件只在事务外经
   ``DeleteFailureSink``，I9）；
4. ``RawTableManager`` 无 update / delete 方法（I7，与 U-RT-01 同一断言）；
5. 写路径不得出现 ``* 100``（金额二次换算只允许在 ``parse_amount_to_cents``）。

所有文本门禁都跑在**去掉注释与 docstring 的代码**上：SQL 是字符串字面量必须保留，
而"文档里写着禁止 unlink"不该被当成"代码里有 unlink"。
"""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "account_dashboard"

_STAGING_UPDATE_OWNERS = {
    "repositories/staging_repo.py",
    "repositories/cleanup_repo.py",  # B 线（C3-B）；当前可以不存在
}
_SNAPSHOT_SETTERS = frozenset({"update_precheck", "finish_ingest"})
_SNAPSHOT_NULLERS = frozenset({"update_after_parse", "reset_precheck"})
_WRITE_PATH_FILES = (
    "services/ingest_service.py",
    "repositories/raw_repo.py",
    "repositories/transaction_repo.py",
)


def _sources() -> list[Path]:
    return sorted(path for path in SRC.rglob("*.py") if ".venv" not in path.parts)


def _docstring_spans(tree: ast.Module) -> list[tuple[int, int]]:
    """模块/类/函数级 docstring 的起始位置 ``(line, col)``。"""
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", [])
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            spans.append((value.lineno, value.col_offset))
    return spans


def _code_text(path: Path) -> str:
    """源码去掉注释与 docstring 后的代码文本（SQL 字符串字面量保留）。"""
    source = path.read_text(encoding="utf-8")
    docstrings = set(_docstring_spans(ast.parse(source, filename=str(path))))
    kept: list[tokenize.TokenInfo] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            continue
        if token.type == tokenize.STRING and token.start in docstrings:
            continue
        kept.append(token)
    return tokenize.untokenize(kept)


def test_update_staging_batch_only_in_owners() -> None:
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in _sources()
        if "UPDATE staging_batch" in _code_text(path)
        and path.relative_to(SRC).as_posix() not in _STAGING_UPDATE_OWNERS
    ]
    assert offenders == [], f"staging_batch 的 UPDATE 只能出现在 {sorted(_STAGING_UPDATE_OWNERS)}"


def test_mapping_snapshot_writes_are_scoped() -> None:
    """``mapping_snapshot = ?`` 只在两个冻结/预检写入点；``= NULL`` 只在两个作废点。"""
    for path in _sources():
        code = _code_text(path)
        if "mapping_snapshot = " not in code:
            continue
        relative = path.relative_to(SRC).as_posix()
        assert relative == "repositories/staging_repo.py", (
            f"{relative} 不得写 mapping_snapshot（D-5：I11 只写一次）"
        )
        tree = ast.parse(code, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            segment = ast.get_source_segment(code, node) or ""
            if "mapping_snapshot = ?" in segment:
                assert node.name in _SNAPSHOT_SETTERS, (
                    f"{node.name} 不允许置值 mapping_snapshot（D-5）"
                )
            if "mapping_snapshot = NULL" in segment:
                assert node.name in _SNAPSHOT_NULLERS, (
                    f"{node.name} 不允许作废 mapping_snapshot（D-5）"
                )


def test_ingest_service_never_deletes_files() -> None:
    code = _code_text(SRC / "services" / "ingest_service.py")
    for banned in ("unlink", "os.remove", "os.unlink", "shutil.rmtree"):
        assert banned not in code, f"ingest_service 不得 {banned}（I9：删除只在事务外经 Sink）"


def test_raw_table_manager_has_no_mutation_methods() -> None:
    from account_dashboard.repositories.raw_repo import RawTableManager

    manager = RawTableManager()
    for name in ("update_rows", "delete_rows", "update", "delete"):
        assert hasattr(manager, name) is False


def test_write_path_never_recomputes_amount() -> None:
    for relative in _WRITE_PATH_FILES:
        code = _code_text(SRC / relative)
        for pattern in ("* 100", "*100"):
            assert pattern not in code, (
                f"{relative} 不得出现 {pattern}：金额换算只允许在 parse_amount_to_cents"
            )
