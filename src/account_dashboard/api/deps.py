"""依赖注入（A8）。

服务只接受「接口」参数，测试时可注入临时库与临时目录，不需要 monkeypatch 全局状态。
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from account_dashboard.config import BootstrapConfig
from account_dashboard.infra.paths import DataPaths
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.unit_of_work import UnitOfWork


def get_database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise RuntimeError("数据库尚未初始化：请通过启动流程（startup）创建应用")
    return database


def get_paths(request: Request) -> DataPaths:
    paths = getattr(request.app.state, "paths", None)
    if paths is None:
        raise RuntimeError("数据目录尚未初始化：请通过启动流程（startup）创建应用")
    return paths


def get_config(request: Request) -> BootstrapConfig:
    config = getattr(request.app.state, "config", None)
    if config is None:
        raise RuntimeError("配置尚未装载")
    return config


def get_uow(request: Request) -> Iterator[UnitOfWork]:
    """事务由业务层 ``with uow.begin():`` 自行开启；这里只负责生命周期。"""
    yield UnitOfWork(get_database(request))
