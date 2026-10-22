-- ============================================================
-- V001__init.sql   个人财务分析仪表盘 初始 schema
-- 执行方式：SchemaMigrator 在单事务内逐条执行本文件
-- 约定：金额 INTEGER 整数分；时间 TEXT ISO 本地时间（秒级）；
--       布尔 INTEGER 0/1；枚举 TEXT 英文小写字面量
-- ============================================================

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL,
    checksum    TEXT NOT NULL
);

-- ── 缓冲区批次 ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS staging_batch (
    id                TEXT PRIMARY KEY,
    file_name         TEXT NOT NULL,                 -- 用户上传时的原始文件名（仅展示）
    stored_name       TEXT NOT NULL,                 -- 缓冲区内的实际文件名（uuid.ext）
    file_size         INTEGER NOT NULL CHECK (file_size >= 0),
    channel           TEXT NOT NULL DEFAULT 'other'
                      CHECK (channel IN ('wechat','alipay','bank','other')),
    status            TEXT NOT NULL DEFAULT 'uploaded'
                      CHECK (status IN ('uploaded','mapped_pending','prechecked',
                                        'ingesting','ingested','discarded','failed')),
    total_rows        INTEGER NOT NULL DEFAULT 0,
    new_count         INTEGER NOT NULL DEFAULT 0,
    dup_count         INTEGER NOT NULL DEFAULT 0,
    pending_count     INTEGER NOT NULL DEFAULT 0,
    encoding          TEXT,
    adapter           TEXT,
    header_row_no     INTEGER,                       -- 表头在文件中的 0-based 行号
    mapped_fields     TEXT,                          -- JSON: {field: col_index}
    mapping_snapshot  TEXT,                          -- JSON: 入库时快照（I11，只写一次）
    parse_meta        TEXT,                          -- JSON: {sheet, delimiter, preamble_rows, ...}
    report_json       TEXT,                          -- JSON: 导入报告四数字 + 按月分布
    pending_delete_flag INTEGER NOT NULL DEFAULT 0 CHECK (pending_delete_flag IN (0,1)),
    deleted_at        TEXT,
    fail_reason       TEXT,
    ingest_started_at TEXT,
    committed_at      TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_batch_status   ON staging_batch(status);
CREATE INDEX IF NOT EXISTS idx_batch_created  ON staging_batch(created_at DESC);

-- ── 原始库按月分表模板（RawTableManager 动态执行，{YYYY_MM} 由代码替换）──
-- 注意：本段不是迁移脚本内容，仅作文档基准；实际由 ensure_table() 逐月创建。
/*
CREATE TABLE IF NOT EXISTS raw_YYYY_MM (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id     TEXT    NOT NULL,
    row_no       INTEGER NOT NULL,
    occurred_at  TEXT    NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    direction    TEXT    NOT NULL CHECK (direction IN ('income','expense','neutral')),
    counterparty TEXT,
    item         TEXT,
    txn_type     TEXT,
    payment_method TEXT,
    platform_category TEXT,
    platform_status   TEXT,
    channel      TEXT    NOT NULL,
    fp           TEXT,
    raw_payload  TEXT    NOT NULL,
    imported_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_YYYY_MM_time   ON raw_YYYY_MM(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_YYYY_MM_batch  ON raw_YYYY_MM(batch_id, row_no);
*/

-- ── 主数据层 ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS "transaction" (
    id            TEXT PRIMARY KEY,
    occurred_at   TEXT    NOT NULL,
    amount_cents  INTEGER NOT NULL CHECK (amount_cents >= 0),
    direction     TEXT    NOT NULL CHECK (direction IN ('income','expense','neutral')),
    category_l1   TEXT,
    category_l2   TEXT,
    counterparty  TEXT,
    item          TEXT,
    txn_type      TEXT,
    payment_method TEXT,
    channel       TEXT    NOT NULL
                  CHECK (channel IN ('wechat','alipay','bank','other')),
    status        TEXT    NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','confirmed','corrected','excluded')),
    note          TEXT,
    hint_l1       TEXT,
    hint_l2       TEXT,
    batch_id      TEXT    NOT NULL,
    row_no        INTEGER NOT NULL,
    fp            TEXT,
    override_reason TEXT,
    override_at   TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_txn_time        ON "transaction"(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_txn_period      ON "transaction"(occurred_at, direction, status);
CREATE INDEX IF NOT EXISTS idx_txn_category    ON "transaction"(category_l1, category_l2);
CREATE INDEX IF NOT EXISTS idx_txn_status      ON "transaction"(status);
CREATE INDEX IF NOT EXISTS idx_txn_batch       ON "transaction"(batch_id, row_no);
CREATE INDEX IF NOT EXISTS idx_txn_fp          ON "transaction"(fp);
CREATE INDEX IF NOT EXISTS idx_txn_counterparty ON "transaction"(counterparty);

-- ── 元数据 ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS category (
    id         TEXT PRIMARY KEY,
    l1         TEXT NOT NULL,
    l2         TEXT NOT NULL,
    sort       INTEGER NOT NULL DEFAULT 0,
    enabled    INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    is_builtin INTEGER NOT NULL DEFAULT 0 CHECK (is_builtin IN (0,1)),
    created_at TEXT NOT NULL,
    UNIQUE (l1, l2)
);
CREATE INDEX IF NOT EXISTS idx_category_l1 ON category(l1, sort);

CREATE TABLE IF NOT EXISTS rule (
    id          TEXT PRIMARY KEY,
    keyword     TEXT NOT NULL,
    match_field TEXT NOT NULL DEFAULT 'counterparty'
                CHECK (match_field IN ('counterparty','item','txn_type','any')),
    category_l1 TEXT NOT NULL,
    category_l2 TEXT NOT NULL,
    priority    INTEGER NOT NULL DEFAULT 100,
    enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    is_builtin  INTEGER NOT NULL DEFAULT 0 CHECK (is_builtin IN (0,1)),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_rule_kw
    ON rule(lower(keyword), match_field, category_l1, category_l2);
CREATE INDEX IF NOT EXISTS idx_rule_priority ON rule(enabled, priority DESC, created_at DESC);

-- 平台分类 → 自有分类的「提示映射」（只用于 pending 队列的建议，绝不直接写 category_*）
CREATE TABLE IF NOT EXISTS category_hint (
    platform_category TEXT NOT NULL,
    channel           TEXT NOT NULL DEFAULT 'alipay'
                      CHECK (channel IN ('wechat','alipay','bank','other')),
    l1                TEXT NOT NULL,
    l2                TEXT NOT NULL,
    weight            INTEGER NOT NULL DEFAULT 100,
    enabled           INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    PRIMARY KEY (channel, platform_category)
);

CREATE TABLE IF NOT EXISTS setting (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,          -- JSON 编码
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_template (
    id          TEXT PRIMARY KEY,
    channel     TEXT NOT NULL CHECK (channel IN ('wechat','alipay','bank','other')),
    name        TEXT NOT NULL,
    spec_json   TEXT NOT NULL,         -- MappingSpec
    is_default  INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0,1)),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_template_default
    ON channel_template(channel) WHERE is_default = 1;   -- 每渠道至多一个默认（EX-20）
CREATE UNIQUE INDEX IF NOT EXISTS uq_template_name ON channel_template(channel, name);

-- 强制新增留痕（P0-1）
CREATE TABLE IF NOT EXISTS override_mark (
    batch_id   TEXT NOT NULL,
    row_no     INTEGER NOT NULL,
    reason     TEXT NOT NULL,
    note       TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (batch_id, row_no)
);

-- 待清理队列（EX-11）
CREATE TABLE IF NOT EXISTS cleanup_queue (
    id         TEXT PRIMARY KEY,
    batch_id   TEXT,
    file_path  TEXT NOT NULL,
    reason     TEXT NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    status     TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done','abandoned')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cleanup_status ON cleanup_queue(status);

-- 备份日志（FR-20 / EX-19）
CREATE TABLE IF NOT EXISTS backup_log (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN ('db','export_json','export_csv','pre_restore','rollback')),
    file_name     TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL DEFAULT 0,
    checksum      TEXT,
    row_counts    TEXT,                -- JSON: {"transaction": n, "raw": m}
    created_at    TEXT NOT NULL,
    restored_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_backup_created ON backup_log(created_at DESC);

-- 本地事件日志（PRD 10.4，默认关闭）
CREATE TABLE IF NOT EXISTS event_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    kind       TEXT NOT NULL,
    batch_id   TEXT,
    payload    TEXT
);
CREATE INDEX IF NOT EXISTS idx_event_ts ON event_log(ts DESC);
