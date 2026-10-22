"""映射校验与渠道模板（SDD §7.3 / §8.11 / EX-20）。

两条硬规则：

1. **五核心字段缺一不可**（``occurred_at`` / ``amount`` / ``direction`` /
   ``counterparty`` / ``item``）—— 缺任一 ⇒ ``E1007``，因为后续指纹、去重、统计
   都依赖它们（FR-03 规则 5）。
2. **同渠道至多一个默认模板** —— 由 DDL 的部分唯一索引兜底，应用层负责
   「先降级后插入」的顺序，避免瞬时唯一冲突。
"""

from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

from account_dashboard.api.errors import BusinessRuleError, EntryValidationError, ErrorCode
from account_dashboard.models.enums import Channel
from account_dashboard.models.internal import (
    ALLOWED_AMOUNT_SCALES,
    CORE_FIELD_LABELS,
    CORE_MAPPING_FIELDS,
    MAPPING_FIELDS,
    MappingSpec,
)
from account_dashboard.models.staging import MappingReq, TemplateDTO, TemplateReq
from account_dashboard.repositories.template_repo import TemplateRepo, TemplateRow

TEMPLATE_NAME_SUFFIX_LIMIT = 50


class MappingService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._repo = TemplateRepo(conn)

    # ── 模板 ──────────────────────────────────────────────────
    def list_templates(self, channel: Channel | None = None) -> list[TemplateDTO]:
        return [_to_dto(record) for record in self._repo.list(channel)]

    def save_template(self, req: TemplateReq) -> TemplateDTO:
        """三策略：abort → 409；overwrite → 旧默认降级；save_as → 名称自动加 (2)。

        调用方负责事务边界（与批次映射更新同事务，避免"模板写成功但批次没更新"）。
        """
        self.validate(req.spec, column_count=None)
        spec_json = json.dumps(_spec_payload(req.spec), ensure_ascii=False)
        existing_default = self._repo.get_default(req.channel)

        if req.policy == "abort":
            if existing_default is not None:
                raise BusinessRuleError(
                    ErrorCode.DUPLICATE_TEMPLATE,
                    f"该渠道已有默认模板『{existing_default.name}』，是否覆盖？也可另存为新模板",
                    detail={
                        "existing_id": existing_default.id,
                        "existing_name": existing_default.name,
                        "can_overwrite": True,
                        "options": ["overwrite", "save_as"],
                    },
                )
            same_name = self._repo.find_by_name(req.channel, req.name)
            if same_name is not None:
                raise BusinessRuleError(
                    ErrorCode.DUPLICATE_TEMPLATE,
                    f"模板名『{req.name}』已存在，请改名或选择覆盖",
                    detail={"existing_id": same_name.id, "options": ["overwrite", "save_as"]},
                )
            record = self._repo.insert(
                template_id=uuid4().hex,
                channel=req.channel,
                name=req.name,
                spec_json=spec_json,
                is_default=True,
            )
            return _to_dto(record)

        if req.policy == "overwrite":
            if existing_default is not None:
                self._repo.demote_default(req.channel)
            same_name = self._repo.find_by_name(req.channel, req.name)
            if same_name is not None:
                record = self._repo.update_spec(
                    same_name.id, spec_json=spec_json, is_default=True
                )
                return _to_dto(record)
            record = self._repo.insert(
                template_id=uuid4().hex,
                channel=req.channel,
                name=req.name,
                spec_json=spec_json,
                is_default=True,
            )
            return _to_dto(record)

        # save_as：保留旧默认，新模板另起名字（没有默认时才成为默认）
        name = self._unique_name(req.channel, req.name)
        record = self._repo.insert(
            template_id=uuid4().hex,
            channel=req.channel,
            name=name,
            spec_json=spec_json,
            is_default=existing_default is None,
        )
        return _to_dto(record)

    def _unique_name(self, channel: Channel, base: str) -> str:
        if self._repo.find_by_name(channel, base) is None:
            return base
        for index in range(2, TEMPLATE_NAME_SUFFIX_LIMIT):
            candidate = f"{base}({index})"
            if self._repo.find_by_name(channel, candidate) is None:
                return candidate
        raise BusinessRuleError(
            ErrorCode.DUPLICATE_TEMPLATE,
            f"模板『{base}』的同名变体过多，请手动指定模板名",
        )

    def resolve_template_spec(self, template_id: str) -> MappingSpec | None:
        record = self._repo.get(template_id)
        if record is None:
            return None
        spec = MappingReq.model_validate_json(record.spec_json)
        return self.to_spec(spec, template_id=record.id)

    # ── 映射校验 ──────────────────────────────────────────────
    def validate(self, req: MappingReq, *, column_count: int | None) -> None:
        """五核心 → 金额单位 → 列索引范围。顺序固定，错误码才不会飘。"""
        missing = [
            CORE_FIELD_LABELS[name]
            for name in CORE_MAPPING_FIELDS
            if _index_of(req, name) is None
        ]
        if missing:
            raise EntryValidationError(
                ErrorCode.MAPPING_INCOMPLETE,
                "请先指定这些列的含义：" + "、".join(missing),
                detail={"missing_fields": missing},
            )

        if req.amount_scale not in ALLOWED_AMOUNT_SCALES:
            raise EntryValidationError(
                ErrorCode.INVALID_ENUM_VALUE,
                f"金额单位只支持 {' / '.join(str(item) for item in ALLOWED_AMOUNT_SCALES)}",
                detail={"amount_scale": req.amount_scale},
            )

        if column_count is not None:
            for name in MAPPING_FIELDS:
                index = _index_of(req, name)
                if index is not None and index >= column_count:
                    raise EntryValidationError(
                        ErrorCode.INVALID_ENUM_VALUE,
                        f"「{CORE_FIELD_LABELS.get(name, name)}」的列序号 {index} 超出文件列数"
                        f"（共 {column_count} 列），请重新选择",
                        detail={"field": name, "index": index, "column_count": column_count},
                    )

    def to_spec(self, req: MappingReq, *, template_id: str | None = None) -> MappingSpec:
        columns = {name: _index_of(req, name) for name in MAPPING_FIELDS}
        return MappingSpec(
            columns=columns,
            direction_map=dict(req.direction_map),
            amount_scale=req.amount_scale,
            template_id=template_id,
        )


def _index_of(req: MappingReq, name: str) -> int | None:
    value = getattr(req, name)
    if value is None:
        return None
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    return index if index >= 0 else None


def _spec_payload(req: MappingReq) -> dict[str, object]:
    return req.model_dump(
        mode="json", exclude={"save_template", "template_policy", "template_name"}
    )


def _to_dto(record: TemplateRow) -> TemplateDTO:
    spec = MappingReq.model_validate_json(record.spec_json)
    return TemplateDTO(
        id=record.id,
        channel=Channel(record.channel),
        name=record.name,
        spec=spec,
        is_default=record.is_default,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
