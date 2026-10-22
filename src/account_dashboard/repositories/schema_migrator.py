"""版本化 schema 迁移（A2，SDD §5.5）。

规则：

* 文件名 ``V{n}__{name}.sql``，按版本号升序执行；
* 每个迁移在**单事务**内执行，失败整体回滚；
* 已应用版本的 checksum 必须与磁盘文件一致，否则拒绝启动（退出码 4）——
  已发布的迁移只能新增，不能修改。

``executescript`` 会隐式提交，破坏事务边界，因此这里用一个小分词器把脚本
拆成语句逐条执行。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from account_dashboard.infra.clock import now_iso
from account_dashboard.infra.logger import get_logger
from account_dashboard.repositories.database import Database

_logger = get_logger("migration")

MIGRATION_DIR = Path(__file__).resolve().parent.parent / "migrations"
_FILE_RE = re.compile(r"^V(\d+)__(.+)\.sql$")

_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL,
    checksum    TEXT NOT NULL
)
"""


class MigrationError(Exception):
    """迁移失败。映射为启动退出码 4。"""


class MigrationChecksumError(MigrationError):
    """已应用迁移的内容被修改。"""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    path: Path
    checksum: str


class SchemaMigrator:
    def __init__(self, database: Database, migrations_dir: Path | None = None) -> None:
        self._db = database
        self._dir = migrations_dir or MIGRATION_DIR

    def migrate(self) -> int:
        """执行所有未应用的迁移，返回最终版本号。"""
        migrations = self._discover()
        applied = self._applied()
        self._ensure_table()

        for migration in migrations:
            known = applied.get(migration.version)
            if known is not None:
                if known != migration.checksum:
                    raise MigrationChecksumError(
                        f"迁移文件 {migration.path.name} 已被修改（checksum 不匹配）；"
                        "请恢复原文件或新增更高版本的迁移"
                    )
                continue
            self._apply(migration)
            applied[migration.version] = migration.checksum

        version = max(applied) if applied else 0
        _logger.info("schema 版本 = %s", version)
        return version

    def current_version(self) -> int:
        self._ensure_table()
        row = self._db.query_one("SELECT MAX(version) AS v FROM schema_version")
        return int(row["v"]) if row and row["v"] is not None else 0

    # ── 内部 ──────────────────────────────────────────────────
    def _ensure_table(self) -> None:
        with self._db.transaction() as conn:
            conn.execute(_SCHEMA_VERSION_DDL)

    def _applied(self) -> dict[int, str]:
        try:
            rows = self._db.query_all("SELECT version, checksum FROM schema_version")
        except Exception as exc:  # 表不存在（首次建库）
            _logger.debug("schema_version 尚不存在：%s", exc)
            return {}
        return {int(row["version"]): str(row["checksum"]) for row in rows}

    def _discover(self) -> list[Migration]:
        if not self._dir.is_dir():
            raise MigrationError(f"迁移目录不存在：{self._dir}")

        found: dict[int, Migration] = {}
        for path in sorted(self._dir.glob("V*.sql")):
            match = _FILE_RE.match(path.name)
            if not match:
                continue
            version = int(match.group(1))
            if version in found:
                raise MigrationError(f"迁移版本重复：V{version}")
            found[version] = Migration(
                version=version, path=path, checksum=hashlib.sha256(path.read_bytes()).hexdigest()
            )
        return [found[key] for key in sorted(found)]

    def _apply(self, migration: Migration) -> None:
        statements = split_sql(migration.path.read_text(encoding="utf-8"))
        try:
            with self._db.transaction() as conn:
                for statement in statements:
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_version(version, applied_at, checksum) VALUES (?,?,?)",
                    (migration.version, now_iso(), migration.checksum),
                )
        except MigrationError:
            raise
        except Exception as exc:
            raise MigrationError(f"迁移 {migration.path.name} 执行失败，已回滚：{exc}") from exc
        _logger.info("已应用迁移 %s", migration.path.name)


def split_sql(script: str) -> list[str]:
    """把 SQL 脚本拆成单条语句，跳过行注释/块注释，尊重引号内的分号。"""
    statements: list[str] = []
    buffer: list[str] = []
    index = 0
    length = len(script)
    quote: str | None = None
    in_line_comment = False
    in_block_comment = False

    while index < length:
        char = script[index]
        following = script[index + 1] if index + 1 < length else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
                buffer.append(char)
            index += 1
            continue

        if in_block_comment:
            if char == "*" and following == "/":
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue

        if quote is not None:
            if char == quote:
                if following == quote:
                    buffer.append(char * 2)
                    index += 2
                    continue
                quote = None
            buffer.append(char)
            index += 1
            continue

        if char == "-" and following == "-":
            in_line_comment = True
            index += 2
            continue
        if char == "/" and following == "*":
            in_block_comment = True
            index += 2
            continue
        if char in {"'", '"'}:
            quote = char
            buffer.append(char)
            index += 1
            continue
        if char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            index += 1
            continue

        buffer.append(char)
        index += 1

    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements
