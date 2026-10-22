"""映射校验与渠道模板（C2-B §4.3 / §4.4，裁决 D-2 / EX-20）。

**硬三软二**（D-2，已登记 ``CONTRACT-CHANGELOG``）：

* ``occurred_at`` / ``amount`` / ``direction`` 缺失 → ``E1007``（400），文案指明缺哪一列；
* ``counterparty`` / ``item`` 缺失 → 允许保存，返回 ``warnings``（去重精度会下降）。

为什么不是 SDD T02.4 的"五核心缺失阻断"：银行 CSV 常常没有「商品」列，
硬卡五列会让 ``generic`` 渠道直接不可用 —— 这是 B 线唯一一处"故意偏离 SDD"的地方，
必须在合稿 K6 复核。

模板三策略（``abort`` / ``overwrite`` / ``save_as``）全部在**单个事务**内完成，
因为 ``uq_template_default`` 是部分唯一索引，"先降级后插入"跨事务会撞索引。
"""

from __future__ import annotations

from uuid import uuid4

from account_dashboard.errors import BusinessRuleError, EntryValidationError, ErrorCode
from account_dashboard.models.internal import Channel, MappingSpec
from account_dashboard.models.staging import MappingReq, TemplateDTO
from account_dashboard.repositories.template_repo import TemplateRepo
from account_dashboard.repositories.unit_of_work import UnitOfWork

REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("occurred_at", "交易时间"),
    ("amount", "金额"),
    ("direction", "收/支方向"),
)

SOFT_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("counterparty", "交易对方", "缺少交易对方，去重精度会下降"),
    ("item", "商品说明", "缺少商品说明，分类准确率会下降"),
)

ALLOWED_SCALES = frozenset({1, 100})


class MappingService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow
        self._templates = TemplateRepo(uow.conn)

    # ── 校验 ──────────────────────────────────────────────────
    def validate(self, mapping: MappingReq, columns: int) -> tuple[MappingSpec, list[str]]:
        """返回 ``(spec, warnings)``；不合规直接抛 1xxx。"""
        missing_fields = [
            field for field, _ in REQUIRED_FIELDS if self._is_unmapped(mapping, field)
        ]
        if missing_fields:
            labels = dict(REQUIRED_FIELDS)
            readable = "、".join(f"{labels[field]}（{field}）" for field in missing_fields)
            raise EntryValidationError(
                ErrorCode.MAPPING_INCOMPLETE,
                f"请先为下列必填字段选择对应的列：{readable}",
                detail={"missing": missing_fields},
            )

        self._check_index("occurred_at", mapping.occurred_at, columns)
        self._check_index("amount", mapping.amount, columns)
        self._check_index("direction", mapping.direction, columns)
        for field in (
            "counterparty",
            "item",
            "txn_type",
            "payment_method",
            "platform_category",
            "platform_status",
        ):
            self._check_index(field, getattr(mapping, field), columns)

        if mapping.amount_scale not in ALLOWED_SCALES:
            raise EntryValidationError(
                ErrorCode.INVALID_ENUM_VALUE,
                "金额单位只能是「元」或「分」，请重新选择",
                detail={"amount_scale": mapping.amount_scale},
            )

        warnings = [
            warning for field, _label, warning in SOFT_FIELDS if getattr(mapping, field) is None
        ]
        spec = MappingSpec(
            occurred_at=int(mapping.occurred_at),
            amount=int(mapping.amount),
            direction=int(mapping.direction),
            counterparty=mapping.counterparty,
            item=mapping.item,
            txn_type=mapping.txn_type,
            payment_method=mapping.payment_method,
            platform_category=mapping.platform_category,
            platform_status=mapping.platform_status,
            direction_map=dict(mapping.direction_map),
            amount_scale=mapping.amount_scale,
        )
        return spec, warnings

    @staticmethod
    def _is_unmapped(mapping: MappingReq, field: str) -> bool:
        value = getattr(mapping, field)
        return value is None or int(value) < 0

    @staticmethod
    def _check_index(field: str, value: int | None, columns: int) -> None:
        if value is None:
            return
        if value < -1:
            raise EntryValidationError(
                ErrorCode.INVALID_ENUM_VALUE, f"字段 {field} 的列索引不合法：{value}"
            )
        if columns > 0 and value >= columns:
            raise EntryValidationError(
                ErrorCode.INVALID_ENUM_VALUE,
                f"字段 {field} 指向第 {value + 1} 列，但文件只有 {columns} 列",
                detail={"field": field, "index": value, "columns": columns},
            )

    # ── 模板 ──────────────────────────────────────────────────
    def list_templates(self, channel: Channel | None = None) -> list[TemplateDTO]:
        return [self._to_dto(item) for item in self._templates.list(channel)]

    def get_default_spec(self, channel: Channel | str) -> MappingSpec | None:
        stored = self._templates.get_default(str(channel))
        return stored["spec"] if stored else None

    def save_template(
        self,
        channel: Channel | str,
        name: str,
        spec: MappingSpec,
        policy: str = "abort",
    ) -> TemplateDTO:
        """EX-20 三策略；``abort`` 是同渠道已有默认模板时唯一会失败的分支。"""
        with self._uow.begin():
            repo = TemplateRepo(self._uow.conn)
            existing = repo.get_default(str(channel))

            if policy == "abort" and existing is not None:
                raise BusinessRuleError(
                    ErrorCode.DUPLICATE_TEMPLATE,
                    f"该渠道已有默认模板「{existing['name']}」，请选择覆盖或另存",
                    detail={"channel": str(channel), "existing": existing["name"]},
                )

            unique = repo.unique_name(str(channel), name)
            if policy == "overwrite":
                repo.demote_defaults(str(channel))
                created = repo.create(
                    channel=str(channel),
                    name=unique,
                    spec=spec,
                    is_default=True,
                    template_id=uuid4().hex,
                )
            elif policy == "save_as":
                created = repo.create(
                    channel=str(channel),
                    name=unique,
                    spec=spec,
                    is_default=False,
                    template_id=uuid4().hex,
                )
            else:  # abort 且没有既有 default → 直接成为该渠道默认
                created = repo.create(
                    channel=str(channel),
                    name=unique,
                    spec=spec,
                    is_default=True,
                    template_id=uuid4().hex,
                )
        return self._to_dto(created)

    @staticmethod
    def _to_dto(item: dict[str, object]) -> TemplateDTO:
        return TemplateDTO(
            id=str(item["id"]),
            channel=item["channel"],  # type: ignore[arg-type]
            name=str(item["name"]),
            spec=item["spec"],  # type: ignore[arg-type]
            is_default=bool(item["is_default"]),
            created_at=str(item["created_at"]),
            updated_at=str(item["updated_at"]),
        )


__all__ = ["ALLOWED_SCALES", "MappingService", "REQUIRED_FIELDS", "SOFT_FIELDS"]
