"""应用工厂（A7）。

装配顺序固定：异常处理器 → 路由 → 静态挂载。
静态挂载必须最后（它注册的是 ``/{full_path}`` 兜底路由，先注册会吞掉 API）。
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from fastapi import FastAPI

from account_dashboard import __version__
from account_dashboard.api.errors import register_exception_handlers
from account_dashboard.api.response import ApiResponse
from account_dashboard.api.routers import health as health_router
from account_dashboard.api.routers import staging as staging_router
from account_dashboard.api.static_mount import mount_spa
from account_dashboard.config import BootstrapConfig, load_bootstrap_config
from account_dashboard.infra.paths import DataPaths, static_dir
from account_dashboard.models.common import HealthDTO

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_app(
    config: BootstrapConfig | None = None,
    *,
    database: object | None = None,
    paths: DataPaths | None = None,
    lifespan: Lifespan | None = None,
) -> FastAPI:
    """``database`` 只做状态挂载，具体类型由启动流程决定；接口层不依赖仓储实现。"""
    cfg = config or load_bootstrap_config()
    app = FastAPI(
        title="个人财务分析仪表盘",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.config = cfg
    app.state.database = database
    app.state.paths = paths

    register_exception_handlers(app)
    app.include_router(health_router.router)
    app.include_router(staging_router.router)
    app.add_api_route(
        "/health",
        health_router.health,
        methods=["GET"],
        response_model=ApiResponse[HealthDTO],
        include_in_schema=False,
    )
    mount_spa(app, static_dir())
    return app
