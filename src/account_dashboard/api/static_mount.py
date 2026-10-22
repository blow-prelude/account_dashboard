"""SPA 静态挂载（ADR-06）。

前端产物打进 wheel，由后端在 ``/`` 挂载：单进程单端口、无 CORS。
开发期 ``static/index.html`` 不存在时整体跳过，不影响 API 调试。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from account_dashboard.infra.logger import get_logger

_logger = get_logger("static")

_RESERVED_PREFIXES = ("api", "openapi.json", "docs", "redoc")


def mount_spa(app: FastAPI, static_dir: Path) -> bool:
    """挂载 SPA；返回是否真的挂载了。"""
    index = static_dir / "index.html"
    if not index.is_file():
        _logger.info("未发现前端产物，跳过静态挂载（开发期正常）：%s", static_dir)
        return False

    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    root = static_dir.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        if _is_reserved(full_path):
            raise HTTPException(status_code=404, detail="Not Found")
        if full_path:
            candidate = (static_dir / full_path).resolve()
            if _is_inside(candidate, root) and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index)

    _logger.info("已挂载前端产物：%s", static_dir)
    return True


def _is_reserved(path: str) -> bool:
    normalized = path.lstrip("/")
    for prefix in _RESERVED_PREFIXES:
        if normalized == prefix or normalized.startswith(f"{prefix}/"):
            return True
    return False


def _is_inside(candidate: Path, root: Path) -> bool:
    try:
        return candidate.is_relative_to(root)
    except ValueError:
        return False
