"""依赖注入（A8）。

服务只接受「接口」参数，测试时可注入临时库与临时目录，不需要 monkeypatch 全局状态。
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from account_dashboard.config import BootstrapConfig
from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.infra.paths import DataPaths
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.unit_of_work import UnitOfWork
from account_dashboard.services.cleanup_service import CleanupService
from account_dashboard.services.import_orchestrator import ImportOrchestrator
from account_dashboard.services.raw_browse_service import RawBrowseService
from account_dashboard.services.trace_service import TraceService


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


def get_orchestrator(request: Request) -> Iterator[ImportOrchestrator]:
    """导入编排器的装配点。

    这里是 ``api`` 允许触达 ``repositories`` 的唯一例外（见 ``test_layering``）：
    仓储与会话只在此处构造，业务层拿到的是完整的服务对象。
    """
    database = get_database(request)
    paths = get_paths(request)
    yield ImportOrchestrator(
        uow=UnitOfWork(database),
        buffer=BufferFileManager(paths.buffer_dir),
        database=database,
    )


def get_cleanup_service(request: Request) -> Iterator[CleanupService]:
    """删除意图 / 待清理队列的装配点（C3-B）。

    合稿 M2 时 A 线把 ``DeleteFailureSink`` 的 ``NullSink`` 换成本服务
    —— 那是两条线唯一的咬合点，改动只此一处。
    """
    database = get_database(request)
    paths = get_paths(request)
    yield CleanupService(uow=UnitOfWork(database), buffer=BufferFileManager(paths.buffer_dir))


def get_raw_browse_service(request: Request) -> Iterator[RawBrowseService]:
    """原始库只读浏览的装配点（C3-B）。"""
    yield RawBrowseService(uow=UnitOfWork(get_database(request)))


def get_trace_service(request: Request) -> Iterator[TraceService]:
    """批次追溯的装配点（C3-B）。"""
    yield TraceService(uow=UnitOfWork(get_database(request)))
