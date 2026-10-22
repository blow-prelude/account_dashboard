# C3-B · 删除意图、自愈与追溯线（读路径与清理域）

> 定位：把「已提交的数据」之后的**物理世界**收干净 —— 删文件、失败入队、重启补删、孤儿报告；再把「已入库的数据」**读回来**给人看 —— 原始库按月浏览、批次追溯。
> **本线不写 `raw_*`、不写 `transaction`、不开入库事务** —— 所有数据由 Gate 0 的 SQL 夹具或 A 线的 `NullSink` 之外的方式预置。
> 人日：**2.0** ｜ 并行：与 A 线零文件交集 ｜ 出口：`/raw/*` 与 `/maintenance/*` 可用、崩溃后可补删、`trace` 三块齐全
> 验收基线：[`C3-入库原始库与故障自愈.md`](./C3-入库原始库与故障自愈.md) ｜ 合稿：[`C3-合稿与耦合收口.md`](./C3-合稿与耦合收口.md)

---

## 1. 边界

### 1.1 本线做（In Scope）

| 能力 | 落点 |
|------|------|
| 删除意图落地（`DeleteFailureSink` 的真实实现） | `services/cleanup_service.py` |
| 待清理队列 CRUD | `repositories/cleanup_repo.py` |
| 带退避的删除重试 | `infra/buffer_file.py`（新增 `delete_with_retry`，不改既有 `delete`） |
| 启动对账四步（升级 C1 的只读版） | `infra/reconciliation.py`、`main.py`（调用点） |
| `/maintenance/cleanup` 两个端点 | `api/routers/maintenance.py` |
| 孤儿清理端点（前端已实现，C3 补后端） | `api/routers/staging.py`（追加 `POST /orphans/cleanup`） |
| 原始库只读浏览 | `api/routers/raw.py`、`repositories/raw_read_repo.py` |
| 批次追溯 | `repositories/trace_repo.py`、`api/routers/transactions.py`（仅 `trace`） |
| 故障注入 2 | `tests/fault_injection/test_fi_crash_after_commit.py` |

### 1.2 本线不做（Out of Scope）

- **不写 `raw_*` 的 DDL 与 INSERT**（A 线），不写 `transaction` 的 INSERT（A 线）。
- 不实现 `confirm` / `report`（A 线）。
- 不做分类、不做统计（C4）；`/transactions/*` 只开 `trace` 一个子路径。
- 不改 `staging_batch` 的 `status`（除中断重置这一防御动作外）—— 状态迁移一律走 A 线的 `staging_repo`。

> **可验证的独立性**：用 Gate 0 的 `tests/helpers/ingest_state.py` 直接用 SQL 造出「`ingested` + `flag=1` + raw 行 + transaction 行」的状态，本线全部用例在**完全没有 `IngestService`** 的情况下应全绿。

---

## 2. 并行前提：SQL 夹具代替 A 线

A 线要等真实解析器、真实样例、真实事务；本线不需要。Gate 0 提供 `tests/helpers/ingest_state.py`：

```python
def make_ingested_batch(conn, *, batch_id, stored_name, file_name,
                        pending_delete_flag=1, report_json=None) -> None: ...
def seed_raw_rows(conn, month: str, batch_id: str, rows: int, *, start_row_no=1) -> None: ...
def seed_transactions(conn, batch_id: str, rows: int) -> None: ...
```

全部是裸 SQL（`INSERT INTO "transaction" ...`、动态建 `raw_2026_06`），不 import 任何 A 线模块。合稿时 A 线也用它来预置"重复入库"场景。

---

## 3. 任务分解

| ID | 任务 | 产出文件 | 依赖 | 人日 | 验收断言 |
|----|------|----------|------|------|----------|
| C3B.1 | 删除意图与待清理队列 | `services/cleanup_service.py`（实现 `DeleteFailureSink`）、`repositories/cleanup_repo.py`、`infra/buffer_file.py`（`delete_with_retry`） | Gate 0 | 0.6 | 删成功 → `flag` 清零 + `deleted_at` 写入 + 不入队；删失败 → 入队且批次仍 `ingested`；重试成功 → 队列置 `done`；`attempts` 递增 |
| C3B.2 | 启动对账四步 | `infra/reconciliation.py`、`main.py` | C3B.1 | 0.5 | 四步顺序不可换；② 补删成功 → `flag=0`；③ 只记 WARN 不自动删；④ 只报告；对账不阻塞启动；故障注入 2 全绿 |
| C3B.3 | 运维端点 | `api/routers/maintenance.py`、`api/routers/staging.py`（`POST /orphans/cleanup`） | C3B.1 | 0.2 | `GET /maintenance/cleanup?status=pending` 返回**数组**（前端按数组消费）；`POST .../retry` 幂等；孤儿清理走文件名白名单 |
| C3B.4 | 原始库只读浏览 | `repositories/raw_read_repo.py`、`api/routers/raw.py` | Gate 0 | 0.4 | `/raw/months` 的 `month` 为 `"2026_06"`（无 `raw_` 前缀）、`count` 与 A 线 `monthly` 逐月相等；`/raw/{ym}/records` 分页；`/raw/records/{id}` 带 `raw_payload` |
| C3B.5 | 批次追溯 | `repositories/trace_repo.py`、`api/routers/transactions.py` | C3B.4 | 0.3 | `trace` 返回四块；随机 5 条主数据可回溯到 raw 行、11 字段一致；`mapping_snapshot` 直接读批次字段（只读） |

**合计 2.0 人日。**

---

## 4. 关键实现要点

### 4.1 `DeleteFailureSink`：A 线唯一咬合点

Gate 0 定义协议，本线提供真实实现：

```python
class DeleteFailureSink(Protocol):
    def on_committed(self, batch_id: str, file_path: str) -> DeleteOutcome: ...

@dataclass(frozen=True)
class DeleteOutcome:
    deleted: bool
    cleanup_id: str | None = None      # deleted=False 时必填
```

`CleanupService.on_committed` 的执行顺序（**在事务外**）：

```
① buffer.delete_with_retry(path, attempts=3)      # PermissionError → gc.collect() + 100/200/300ms 退避
② 成功 → UPDATE staging_batch SET pending_delete_flag=0, deleted_at=? WHERE id=?   （独立小事务）
③ 失败 → INSERT cleanup_queue(...) + UPDATE ... SET last_error=? attempts=attempts+1
         返回 DeleteOutcome(deleted=False, cleanup_id=...)
```

三条硬约束：

- **不能因为删不掉就回滚入库** —— 数据已提交，只能入队；
- `flag` 的清零与本线的入队是**两个独立小事务**，不要合并成一个（合并会让"清零成功但入队失败"的中间态无法解释）；
- `cleanup_queue` 的 `file_path` 存**绝对或相对缓冲区路径的字符串**，`file_name` 不落表（DDL 没有该列）—— 端点返回时用 `LEFT JOIN staging_batch.file_name` 补全，前端已有 `c.file_name || c.file_path` 的兜底。

### 4.2 Windows 上的删除失败（必现问题，EX-11）

```python
def delete_with_retry(self, path: Path, attempts: int = 3, delay: float = 0.1) -> bool:
    for i in range(attempts):
        try:
            path.unlink(); return True
        except FileNotFoundError:
            return True                      # 幂等：已经没了就算成功
        except PermissionError:
            gc.collect(); time.sleep(delay * (i + 1))
        except OSError:
            return False                     # 非占用类错误，重试无意义
    return False
```

`openpyxl` / `csv` 读取后句柄可能未及时释放，`gc.collect()` 是 Windows 上唯一有效的兜底。注意保留 C2 的 `delete()` 原语义（缺失视为成功、失败抛 `E4003`），本线只**新增**方法。

### 4.3 启动对账四步（顺序不可换）

| 步 | 动作 | 失败处理 |
|----|------|----------|
| ① | 中断批次重置：`UPDATE staging_batch SET status='prechecked', fail_reason='服务重启中断' WHERE status='ingesting'`，**命中即 WARN**（视为缺陷信号） | 失败仅告警 |
| ② | 补删：`status='ingested' AND pending_delete_flag=1` 逐条删；成功清零、失败入队 | 单条失败继续下一条，累计报告 |
| ③ | 不一致检测："已入库 + `flag=0` + 文件仍存在" → 记 WARN 并入队，**不自动删** | 人工确认 |
| ④ | 孤儿扫描：已知集合 = 未入库且未丢弃批次的 `stored_name`；半成品（`.part`/`.tmp`）不算 | 只报告，不自动删（EX-13 要求用户确认） |

**D-8 的后果**：因为幂等闸门在事务内（A 线 §2），`ingesting` 在库里查不到 —— 第 ① 步正常情况恒命中 0 条。它保留为**防御性保险丝**：命中说明有人在事务外改过状态，必须报警而不是静默修复。因此本线的验收断言从「N 个批次被自愈」改为「**崩溃后批次仍为 `prechecked`，重发 `confirm` 成功**」，日志文案保留以便排查。

对账**不阻塞启动**（SDD §2.3）：任何一个文件删不掉都只影响该文件，阻塞启动反而让用户进不去界面处理。

`ReconciliationReport` 的四个字段（`interrupted_batches` / `pending_deletes` / `orphans` / `missing_buffer_dir`）是 FZ-1 的一部分（`/health.backlog` 消费），**只允许加字段，不许改字段**。

### 4.4 孤儿清理的白名单（防误删）

`POST /api/v1/staging/orphans/cleanup {names: [...]}`

```
① 名字必须匹配 ^[0-9a-f]{32}(\.[A-Za-z0-9]{1,8})?$       否则 422 E1008
② 名字必须不在"已知批次集合"（staging_batch.stored_name）内   否则 409 E2002（它可能正被别的批次使用）
③ 解析出的 Path 必须位于缓冲区目录内（resolve() 后 is_relative_to(buffer_dir)）  否则 422 E1011
④ 逐个 delete_with_retry，失败的不从清单里移除
```

返回 `OrphanCleanupDTO{removed: [...], failed: [{name, code}]}`。前端 `pages/buffer.js` 已按 `POST /staging/orphans/cleanup` 实现（该端点未列在 C3 原端点表中，是本线补齐的缺口，见合稿 §9）。

### 4.5 原始库只读浏览：三处口径必须与 A 线一致

| 项 | 口径 | 不一致的后果 |
|----|------|--------------|
| 月份键 | `/raw/months[].month` 为 **`"2026_06"`**（无 `raw_` 前缀） | 前端 `pages/raw.js` 用 `x.month.slice(5)` 取月份、拼 `raw_${ym}` 取表名；多一个前缀就查空表 |
| 表名 | 内部查询用 `infra/raw_naming.table_name(month)` | 自己拼字符串就绕过正则校验 |
| `count` | `SELECT COUNT(*) FROM raw_2026_06` | 与 A 线 `IngestReportDTO.monthly["raw_2026_06"]` 必须逐月相等 |

- 列表查询**显式列名**，绝不用 `SELECT *`（raw 表是动态建的，列序漂移会让 DTO 静默错位）；
- `raw_payload` 只在 `/raw/records/{id}` 详情里返回，列表不带（5 万行时 JSON 会爆）；
- 分页：`10 ≤ page_size ≤ 200`，越界 `E1010`；
- 月份不存在 → 404 `E2001`（批次语义）还是空数组？取**空数组 + `meta.total=0`**：原始库浏览是"按月归档"视图，缺月是常态不是错误。

### 4.6 追溯接口的返回形状（前端已按此实现）

```json
{
  "transaction": {"id","batch_id","row_no","occurred_at","amount_cents","direction",
                  "counterparty","item","channel","status"},
  "batch": {...BatchDTO},
  "raw_record": {...RawRecordDTO},
  "mapping_snapshot": {...}
}
```

- 前端 `pages/raw.js` 的 `trace` 分支读 `t.transaction.{id,batch_id,row_no,occurred_at,amount_cents,counterparty}`、`t.raw_record.row_no`、`t.mapping_snapshot.{occurred_at,amount,amount_scale,direction,counterparty}`；
- `raw_record` 从 `raw_YYYY_MM` 按 `(batch_id, row_no)` 取，月份由 `transaction.occurred_at[:7]` 推出；
- `mapping_snapshot` 直接读 `staging_batch.mapping_snapshot`（I11 只写一次，全程**只读**，本线不得写）；
- 缺块的处理（**不一律报错**）：
  - `transaction` 不存在 → 404 `E2010`；
  - `transaction` 存在但 `batch` 或 `raw_record` 缺失 → **200 + 该块为 `null`** + 记 WARN 日志。这是数据分叉信号，属严重缺陷，应暴露在日志而不是给用户一个 500。
- **D-6 的后果**：`skipped_invalid` 的行不写 raw 也不写 `transaction`，所以它们不可能出现在追溯链里。追溯缺块的 WARN 只能由"数据损坏"触发，不会由"正常跳过"触发 —— 这条是判断 WARN 是否真缺陷的分界线。

### 4.7 `staging_batch` 的双写方与门禁

本线写 `staging_batch` 的地方只有两处，且都受 grep 门禁约束：

```
cleanup_repo.clear_pending_delete(batch_id)   → UPDATE ... SET pending_delete_flag=0, deleted_at=?
cleanup_repo.reset_interrupted()              → UPDATE ... SET status='prechecked' WHERE status='ingesting'
```

其余任何 `status` 变更走 A 线的 `staging_repo`。门禁：`UPDATE staging_batch` 只允许出现在 `staging_repo.py` 与 `cleanup_repo.py`，且后者只准含 `pending_delete_flag` / `status='ingesting'` 这两个模式。

---

## 5. 对外契约

### 5.1 端点（本线 5 个）

| 方法 | 路径 | 返回 | 备注 |
|------|------|------|------|
| GET | `/api/v1/raw/months` | `[{month:"2026_06", count:101}]` | 数组，按月份降序 |
| GET | `/api/v1/raw/{yyyy_mm}/records` | `Page[RawRecordDTO]` | `{yyyy_mm}` 正则 `^\d{4}_\d{2}$`，否则 422 `E1008` |
| GET | `/api/v1/raw/records/{id}` | `RawRecordDetailDTO`（含 `raw_payload`） | 不存在 → 404 `E2001` |
| GET | `/api/v1/maintenance/cleanup?status=pending` | `list[CleanupItemDTO]` | **数组不是分页对象**（前端 `.map` 直接消费） |
| POST | `/api/v1/maintenance/cleanup/{id}/retry` | `CleanupItemDTO` | 幂等：已 `done` 的重复重试返回当前状态，不报错 |
| POST | `/api/v1/staging/orphans/cleanup` | `OrphanCleanupDTO` | 前端已实现，C3 补后端 |
| GET | `/api/v1/transactions/{id}/trace` | `TraceDTO` | C4 会再开 `/transactions` 的其他子路径 |

### 5.2 给合稿的注入面

| 契约 | 本线提供 | 合稿时 |
|------|----------|--------|
| `CleanupService`（实现 `DeleteFailureSink`） | 真实实现 | `api/deps.py` 里把 A 线的 `NullSink` 换成它（唯一改动点） |
| `run_startup_reconciliation(database, paths)` | 签名不变，内部加写动作 | `main.py` 的调用点不改 |

### 5.3 给 C4 的交接

- `repositories/raw_read_repo.py` 的 `iter_month(month)` 是 C4「从原始库重算」的读源（前端 `pages/raw.js` 的"从原始库重算"按钮已存在）；
- `TraceTransactionDTO` 的字段是 C4 完整 `TransactionDTO` 的**子集**，C4 扩展时必须保留这些字段名。

---

## 6. 测试与验收

### 6.1 必写用例

| 用例 | 断言 |
|------|------|
| `test_delete_intent.py` | 删成功 → `flag=0` + `deleted_at` 有值 + 队列 0 行；删失败 → 队列 +1、批次仍 `ingested`、报告 `files_deleted=false` |
| `test_cleanup_retry.py`（EX-11） | 模拟删失败 → 入队 → 解除占用 → `retry` 成功 → `status='done'` + `flag=0`；重复 retry 幂等 |
| `test_delete_with_retry_windows.py` | `PermissionError` 连续 2 次后第 3 次成功；`FileNotFoundError` 视为成功；`OSError` 不重试 |
| `test_reconcile_order.py` | 四步按 ①②③④ 执行（用 spy 记录调用序）；任一步抛异常不影响后续步 |
| `test_reconcile_orphan.py`（EX-13） | 缓冲区放一个无批次文件 → 出现在孤儿清单，**文件仍在** |
| `test_fi_crash_after_commit.py` | `ingested`+`flag=1`+文件在 → 重启对账 → 文件被删、`flag=0`、日志有补删记录 |
| `test_reconcile_not_blocking.py` | 对账里 3 个文件全删失败 → 服务仍启动成功、`/health` 200（可能 `degraded`） |
| `test_raw_months.py` | `month` 无 `raw_` 前缀；`count` 与预置行数相等；无数据的月份不出现 |
| `test_raw_records_pagination.py` | `page_size=9`/`201` → `E1010`；`meta.total` 正确；列表项不含 `raw_payload` |
| `test_trace_back.py`（I8） | 随机 5 条 `transaction`，`batch_id+row_no` 能在 raw 找到且 11 字段一致 |
| `test_trace_missing_blocks.py` | 删掉 raw 表后 trace → 200 + `raw_record=null` + WARN 日志；`transaction` 不存在 → 404 `E2010` |
| `test_orphan_whitelist.py` | 名字含 `../` → `E1011`；名字在某批次的 `stored_name` 内 → `E2002`；合法名字 → 删除成功 |

### 6.2 出口检查表

- [ ] `GET /maintenance/cleanup` 返回数组，前端 `pages/buffer.js` 可直接消费
- [ ] 提交后 `flag=1` → 删成功清零；删失败入队且批次仍 `ingested`
- [ ] 重启补删成功；`attempts` 递增、`last_error` 有值
- [ ] 孤儿清理三重白名单（名字格式 / 不在已知批次 / 在缓冲区目录内）全部生效
- [ ] `/raw/months` 的 `month` 为 `2026_06`；`count` 与 A 线 `monthly` 逐月相等
- [ ] 随机 5 条主数据可回溯到 raw 行，11 字段一致；`trace` 四块齐全
- [ ] 对账不阻塞启动（3 个文件全删失败仍能起服务）
- [ ] 本线代码全文无 `INSERT INTO "transaction"`、无 `CREATE TABLE raw_`
- [ ] 打 tag `c3b-done`

---

## 7. 风险与回退

| 风险 | 表现 | 处理 |
|------|------|------|
| 对账误删用户文件 | 孤儿清单被"一键清理"误点 | 三重白名单 + 前端二次确认；④ 步只报告 |
| `pending_delete_flag` 被本线误用 | 有人用它标记"待删除主数据" | 只有本线的 `clear_pending_delete` 能置 0；DDL 注释写死语义 |
| 对账拖慢启动 | 上千个待删文件逐个重试 3 次 × 300ms | 启动对账只做**一次**删除尝试（不重试 3 次），失败直接入队交给用户手动 retry |
| 缓冲区目录被移走 | ④ 步 `iterdir` 抛异常 | `scan_orphans` 已处理目录缺失；`missing_buffer_dir=True` 时跳过 ②④ |
| `raw` 表不存在就查 | 月份无数据 | 先查 `sqlite_master` 确认表存在，不存在返回空；**不要依赖异常** |
| 追溯变慢 | `raw` 表无 `(batch_id,row_no)` 索引 | 索引由 A 线建（`idx_raw_YYYY_MM_batch`）；合稿 M4 断言该索引存在 |

**回退**：本线的库变更集中在 `cleanup_queue`（C1 已建表）与 `staging_batch` 的两个字段，不新增表。最坏情况是"文件没删、队列里堆了几条"，数据本身不受影响 —— 这是本线相对 A 线的最大优势：**可回退**。

---

## 8. 交接物

给合稿与 C4：

1. `CleanupService` 实现了 `DeleteFailureSink`，可被 `api/deps.py` 一行替换；
2. `run_startup_reconciliation` 升级为写动作，签名不变，`main.py` 无需改；
3. `raw_read_repo.iter_month(month)` 可供 C4「从原始库重算」复用；
4. `tests/helpers/ingest_state.py` 的用法示例（合稿时 A 线也用）；
5. 故障注入 2 已进入 CI。
