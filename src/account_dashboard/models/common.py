"""通用 DTO。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BacklogDTO(BaseModel):
    """启动/运行期积压：待清理队列与孤儿文件。"""

    cleanup: int = 0
    orphans: int = 0


class HealthDTO(BaseModel):
    """``GET /health`` 的载荷（SDD §6.2.1）。"""

    status: str = "ok"
    version: str
    data_dir: str
    db_ok: bool
    backlog: BacklogDTO = Field(default_factory=BacklogDTO)
