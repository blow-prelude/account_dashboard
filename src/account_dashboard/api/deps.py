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
from account_dashboard.services.import_orchestrator import ImportOrchestrator
from account_dashboard.services.ingest_ports import DeleteFailureSink, NullSink
from account_dashboard.services.ingest_service import IngestService


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


def get_delete_sink(request: Request) -> DeleteFailureSink:
    """删除意图注入点（K3）。

    A 线开发期用 ``NullSink``（假装删成功）；合稿 M2 换成 B 线的
    ``CleanupService`` 只改这一处，A 线用例零改动。
    """
    return NullSink()


def get_ingest_service(request: Request) -> Iterator[IngestService]:
    """入库服务的装配点（C3-A）。同样只在 deps 构造仓储。"""
    database = get_database(request)
    paths = get_paths(request)
    buffer = BufferFileManager(paths.buffer_dir)
    yield IngestService(
        uow=UnitOfWork(database),
        orchestrator=ImportOrchestrator(uow=UnitOfWork(database), buffer=buffer, database=database),
        sink=get_delete_sink(request),
        buffer=buffer,
        data_dir=paths.data_dir,
    )
