"""全局阈值与分片常量（叶子模块，任何层可引用）。

集中在此的原因：同一个数字被 ``infra``（流式落盘）、``services``（编排）、
``api``（入口校验）三处使用。若各写一份常量，改一处漏两处，就会出现
"接口说 5MB、落盘说 6MB" 这类只在边界上才暴露的缺陷。
"""

from __future__ import annotations

# ── 上传与解析 ────────────────────────────────────────────────
MAX_FILE_BYTES = 5 * 1024 * 1024  # 单文件上限 5MB（E1005 / 413）
MAX_ROWS = 50_000  # 单批次行数上限（E1006 / 422）
MIN_DISK_FREE_BYTES = 200 * 1024 * 1024  # 上传前磁盘最低余量（E4001 / 507）
STREAM_CHUNK_BYTES = 1 << 20  # 流式读写块 1MB（内存峰值 ≈ 2 块）

# ── 预检 ─────────────────────────────────────────────────────
FP_QUERY_CHUNK = 500  # SQLite IN 参数安全上限（旧版本 999）
OVERRIDE_REASON_MAX = 200

# ── 预览与分页 ────────────────────────────────────────────────
PREVIEW_DEFAULT_LIMIT = 20
PREVIEW_MAX_LIMIT = 50
PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MIN = 10
PAGE_SIZE_MAX = 200

# ── 缓冲区占用阈值（setting: buffer_size_threshold_mb，PRD FR-07 规则 4）──
BUFFER_THRESHOLD_MB_DEFAULT = 500
BUFFER_THRESHOLD_MB_MIN = 10

__all__ = [
    "BUFFER_THRESHOLD_MB_DEFAULT",
    "BUFFER_THRESHOLD_MB_MIN",
    "FP_QUERY_CHUNK",
    "MAX_FILE_BYTES",
    "MAX_ROWS",
    "MIN_DISK_FREE_BYTES",
    "OVERRIDE_REASON_MAX",
    "PAGE_SIZE_DEFAULT",
    "PAGE_SIZE_MAX",
    "PAGE_SIZE_MIN",
    "PREVIEW_DEFAULT_LIMIT",
    "PREVIEW_MAX_LIMIT",
    "STREAM_CHUNK_BYTES",
]
