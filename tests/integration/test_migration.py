"""schema 迁移用例（SDD §5.5）。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from account_dashboard.repositories.database import Database
from account_dashboard.repositories.schema_migrator import (
    MIGRATION_DIR,
    MigrationChecksumError,
    SchemaMigrator,
    split_sql,
)

EXPECTED_TABLES = {
    "schema_version",
    "staging_batch",
    "transaction",
    "category",
    "rule",
    "category_hint",
    "setting",
    "channel_template",
    "override_mark",
    "cleanup_queue",
    "backup_log",
    "event_log",
}


def test_creates_all_tables(tmp_path: Path) -> None:
    db = Database(tmp_path / "ledger.db")
    try:
        version = SchemaMigrator(db).migrate()
        assert version == 1
        tables = {row["name"] for row in db.query_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )}
        assert tables == EXPECTED_TABLES
    finally:
        db.close()


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    db = Database(tmp_path / "ledger.db")
    try:
        SchemaMigrator(db).migrate()
        SchemaMigrator(db).migrate()
        rows = db.query_all("SELECT version, checksum FROM schema_version")
        assert len(rows) == 1
        assert rows[0]["version"] == 1
        assert SchemaMigrator(db).current_version() == 1
    finally:
        db.close()


def test_checksum_mismatch_blocks_startup(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    shutil.copytree(MIGRATION_DIR, migrations)
    db = Database(tmp_path / "ledger.db")
    try:
        SchemaMigrator(db, migrations).migrate()
        target = migrations / "V001__init.sql"
        target.write_text(target.read_text(encoding="utf-8") + "\n-- tampered\n", encoding="utf-8")
        with pytest.raises(MigrationChecksumError):
            SchemaMigrator(db, migrations).migrate()
    finally:
        db.close()


def test_wal_mode_enabled(tmp_path: Path) -> None:
    db = Database(tmp_path / "ledger.db")
    try:
        row = db.query_one("PRAGMA journal_mode")
        assert row is not None and str(row[0]).lower() == "wal"
        assert db.integrity_check() is True
    finally:
        db.close()


def test_indexes_created(tmp_path: Path) -> None:
    db = Database(tmp_path / "ledger.db")
    try:
        SchemaMigrator(db).migrate()
        indexes = {row["name"] for row in db.query_all(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )}
        assert {"idx_batch_status", "idx_txn_period", "idx_txn_fp", "idx_cleanup_status"} <= indexes
    finally:
        db.close()


def test_split_sql_ignores_comments_and_strings() -> None:
    script = """
    -- CREATE TABLE nope (x INT);
    CREATE TABLE a (x TEXT DEFAULT 'a;b');
    /* block ; comment */
    INSERT INTO a VALUES ('it''s; ok');
    """
    statements = split_sql(script)
    assert len(statements) == 2
    assert statements[0].startswith("CREATE TABLE a")
    assert "a;b" in statements[0]
    assert statements[1].startswith("INSERT INTO a")
