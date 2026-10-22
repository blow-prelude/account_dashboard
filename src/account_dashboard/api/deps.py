"""依赖注入（A8 / C2-B C2B.3）。

装配点原则：**Service 只接受「接口」参数**，测试时可注入临时库、临时目录与假解析器，
不需要 monkeypatch 全局状态。这也是合稿 K9 的唯一注入点（``get_parser_registry``）。

本文件是分层规则里唯一允许 ``api → repositories`` 例外的地方（``test_layering.py``），
因为它必须构造 ``UnitOfWork``；路由层仍然不得直接触达仓储或 sqlite。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from account_dashboard.config import BootstrapConfig
from account_dashboard.infra.buffer_file import BufferFileManager
from account_dashboard.infra.parsers.registry import ParserRegistry, default_registry
from account_dashboard.infra.paths import DataPaths
from account_dashboard.limits import MIN_DISK_FREE_BYTES
from account_dashboard.repositories.database import Database
from account_dashboard.repositories.transaction_repo import TransactionRepo
from account_dashboard.repositories.unit_of_work import UnitOfWork
from account_dashboard.services.dedup_checker import DedupChecker
from account_dashboard.services.import_orchestrator import ImportOrchestrator
from account_dashboard.services.mapping_service import MappingService


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


def get_buffer_manager(request: Request) -> BufferFileManager:
    return BufferFileManager(get_paths(request).buffer_dir, MIN_DISK_FREE_BYTES)


def get_parser_registry(request: Request) -> ParserRegistry:
    """合稿 M2 只需把这里从 Fake 换成 ``default_registry()``。

    未显式注入时懒加载一次并缓存到 ``app.state``，避免每个请求都重新探测适配器。
    """
    registry = getattr(request.app.state, "parser_registry", None)
    if not isinstance(registry, ParserRegistry):
        registry = default_registry()
        request.app.state.parser_registry = registry
    return registry


def get_mapping_service(uow: Annotated[UnitOfWork, Depends(get_uow)]) -> MappingService:
    return MappingService(uow)


def get_dedup_checker(uow: Annotated[UnitOfWork, Depends(get_uow)]) -> DedupChecker:
    return DedupChecker(TransactionRepo(uow.conn))


def get_import_orchestrator(
    request: Request,
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> ImportOrchestrator:
    return ImportOrchestrator(
        uow,
        get_buffer_manager(request),
        get_parser_registry(request),
        MappingService(uow),
    )
