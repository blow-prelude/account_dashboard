"""SPA 静态挂载（ADR-06）。

前端产物打进 wheel，由后端在 ``/`` 挂载：单进程单端口、无 CORS。
开发期 ``static/index.html`` 不存在时整体跳过，不影响 API 调试。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
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

    @app.middleware("http")
    async def spa_fallback(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """404 之后兜底，而不是注册 ``/{full_path}`` 路由。

        路由式兜底会遮蔽**其后注册**的任何路由（测试探针、后续插件），
        因为 Starlette 按注册顺序匹配。放在 404 之后既保留 history fallback，
        又不会吞掉晚注册的接口。``api/openapi/docs`` 前缀不参与兜底。
        """
        response = await call_next(request)
        if response.status_code != 404 or request.method not in ("GET", "HEAD"):
            return response

        path = request.url.path.lstrip("/")
        if _is_reserved(path):
            return response
        if path:
            candidate = (static_dir / path).resolve()
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
