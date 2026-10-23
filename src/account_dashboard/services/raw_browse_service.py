"""原始库只读浏览（C3-B §4.5；给 C4 的交接面在此）。

路由只做参数校验与包装，"按月归档"的读口径在本服务：

* ``/raw/months`` 的 ``month`` 是 ``"2026_06"``（无 ``raw_`` 前缀）；
* 缺月返回空数组 + ``meta.total=0``（按月归档视图里缺月是常态，不是错误）；
* ``raw_payload`` 只在详情里返回，列表不带。

C4 的「从原始库重算」复用 ``RawReadRepo.iter_month`` 同源的读路径
（``raw_read_repo.page`` 按批迭代即可，本服务不包一层递归游标）。
"""

from __future__ import annotations

import json

from account_dashboard.api.response import Page, PageMeta
from account_dashboard.infra.logger import get_logger
from account_dashboard.models.ingest import (
    RawMonthDTO,
    RawRecordDetailDTO,
    RawRecordDTO,
)
from account_dashboard.repositories.raw_read_repo import RawReadRepo, to_record_dto
from account_dashboard.repositories.unit_of_work import UnitOfWork

_logger = get_logger("raw_browse")


class RawBrowseService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow
        self._repo = RawReadRepo(uow.conn)

    def months(self) -> list[RawMonthDTO]:
        """有数据的月份（降序）；``count`` 与 A 线报告 ``monthly`` 逐月相等。"""
        return [
            RawMonthDTO(month=month, count=self._repo.count(month))
            for month in self._repo.existing_months()
        ]

    def records(self, month: str, page: int, page_size: int) -> Page[RawRecordDTO]:
        rows, total = self._repo.page(month, page, page_size)
        return Page(
            items=[to_record_dto(row) for row in rows],
            meta=PageMeta.build(page, page_size, total),
        )

    def detail(self, record_id: int) -> RawRecordDetailDTO | None:
        row = self._repo.detail(record_id)
        if row is None:
            return None
        payload = _parse_payload(row.raw_payload)
        base = to_record_dto(row)
        return RawRecordDetailDTO(**base.model_dump(), raw_payload=payload)


def _parse_payload(text: str | None) -> dict[str, object]:
    """``raw_payload`` 是入库时原样冻结的 JSON（I7）；损坏时给空 dict 而不是 500。"""
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        _logger.warning("raw_payload 不是合法 JSON，已按空处理")
        return {}
    return parsed if isinstance(parsed, dict) else {}
