"""跨层内部结构（不出现在 API 契约里）。

``MappingSpec`` 是「列索引 → 标准字段」的内部表示；API 层的 ``MappingReq`` 是它的
请求形态（多了 ``save_template`` 等动作开关）。``MappingSnapshot`` 是 I11 的载体：
预检成功时固化一次，C3 入库与 C4 重算都靠它重放，保证「当时口径」不被后来的模板改动污染。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from account_dashboard.models.enums import Direction

MAPPING_FIELDS: tuple[str, ...] = (
    "occurred_at",
    "amount",
    "direction",
    "counterparty",
    "item",
    "txn_type",
    "payment_method",
    "platform_category",
    "platform_status",
)
CORE_MAPPING_FIELDS: tuple[str, ...] = (
    "occurred_at",
    "amount",
    "direction",
    "counterparty",
    "item",
)
CORE_FIELD_LABELS: dict[str, str] = {
    "occurred_at": "交易时间",
    "amount": "金额",
    "direction": "收/支",
    "counterparty": "交易对方",
    "item": "商品说明",
}
ALLOWED_AMOUNT_SCALES = (1, 100)


@dataclass(frozen=True, slots=True)
class MappingSpec:
    """列映射（-1 / None 表示未映射）。"""

    columns: dict[str, int | None] = field(default_factory=dict)
    direction_map: dict[str, Direction] = field(default_factory=dict)
    amount_scale: int = 1
    template_id: str | None = None

    def column(self, name: str) -> int | None:
        index = self.columns.get(name)
        if index is None or index < 0:
            return None
        return index

    def missing_core(self) -> list[str]:
        return [name for name in CORE_MAPPING_FIELDS if self.column(name) is None]

    def as_column_map(self) -> dict[str, int | None]:
        return {name: self.column(name) for name in MAPPING_FIELDS}

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.as_column_map(),
            "direction_map": {key: str(value) for key, value in self.direction_map.items()},
            "amount_scale": self.amount_scale,
            "template_id": self.template_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MappingSpec:
        raw_columns = data.get("columns") or {}
        columns = {name: _as_optional_int(raw_columns.get(name)) for name in MAPPING_FIELDS}
        raw_direction = data.get("direction_map") or {}
        direction_map = {
            str(key): Direction(value) for key, value in raw_direction.items() if value
        }
        return cls(
            columns=columns,
            direction_map=direction_map,
            amount_scale=int(data.get("amount_scale") or 1),
            template_id=data.get("template_id"),
        )


@dataclass(frozen=True, slots=True)
class MappingSnapshot:
    """预检成功时固化的解析口径（I11）。"""

    adapter: str
    encoding: str
    header_row_no: int
    column_map: dict[str, int | None]
    direction_map: dict[str, str]
    amount_scale: int
    template_id: str | None
    created_at: str
    fp_version: str = "v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "encoding": self.encoding,
            "header_row_no": self.header_row_no,
            "column_map": dict(self.column_map),
            "direction_map": dict(self.direction_map),
            "amount_scale": self.amount_scale,
            "template_id": self.template_id,
            "created_at": self.created_at,
            "fp_version": self.fp_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MappingSnapshot:
        return cls(
            adapter=str(data.get("adapter") or "generic"),
            encoding=str(data.get("encoding") or ""),
            header_row_no=int(data.get("header_row_no") or 0),
            column_map={
                name: _as_optional_int((data.get("column_map") or {}).get(name))
                for name in MAPPING_FIELDS
            },
            direction_map={
                str(key): str(value)
                for key, value in (data.get("direction_map") or {}).items()
            },
            amount_scale=int(data.get("amount_scale") or 1),
            template_id=data.get("template_id"),
            created_at=str(data.get("created_at") or ""),
            fp_version=str(data.get("fp_version") or "v1"),
        )

    def as_mapping_spec(self) -> MappingSpec:
        return MappingSpec(
            columns=dict(self.column_map),
            direction_map={
                key: Direction(value) for key, value in self.direction_map.items()
            },
            amount_scale=self.amount_scale,
            template_id=self.template_id,
        )


def _as_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
