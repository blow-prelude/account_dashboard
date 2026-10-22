# C3-A · 入库事务与原始库线（写路径）

> 定位：把「预检通过的批次」在**一个事务里**变成「不可变的原始库 + 可回溯的主数据」，并产出报告四数字。
> **本线是 C3 唯一写 `raw_*` 与 `transaction` 的线**，也是唯一决定"这一行到底入库没有"的线。它不关心文件删不掉怎么办（交给 B 线的 `DeleteFailureSink`），也不提供任何原始库浏览接口。
> 人日：**2.5** ｜ 并行：与 B 线零文件交集 ｜ 出口：支付宝样例 → 5 张 raw 表 **101/136/182/143/107**
> 验收基线（不改口径）：[`C3-入库原始库与故障自愈.md`](./C3-入库原始库与故障自愈.md) ｜ 合稿：[`C3-合稿与耦合收口.md`](./C3-合稿与耦合收口.md)

---

## 1. 边界

### 1.1 本线做（In Scope）

| 能力 | 落点 |
|------|------|
| 幂等闸门（条件 UPDATE + `rowcount`） | `repositories/staging_repo.py` |
| 状态机补 `ingest` / `confirm` 两行 | `services/batch_guard.py` |
| `RawTableManager`（动态分表，只增不改） | `repositories/raw_repo.py` |
| 二次去重 + 双写 + 报告四数字 | `services/ingest_service.py` |
| 主数据写入与 C4 空壳签名 | `repositories/transaction_repo.py` |
| `confirm` / `report` 两个端点 | `api/routers/ingest.py` |
| 故障注入 1 / 3 / 4 | `tests/fault_injection/*` |

### 1.2 本线不做（Out of Scope）

- **不删任何文件**。`unlink` 一次都不许出现在 `ingest_service.py` 里 —— 事务外的删除与失败入队全部经 `DeleteFailureSink` 交给 B 线（K3）。
- 不实现 `cleanup_queue` 的读写、不实现启动对账（B 线）。
- 不提供 `raw` 浏览与 `trace` 端点（B 线）。
- 不做分类、不做统计（C4）：本线写入的 `transaction` 行 `status='pending'`、`category_l1/l2` 为 `NULL`。

> **可验证的独立性**：把 `DeleteFailureSink` 换成 Gate 0 的 `NullSink`，本线全部用例仍应全绿；反之，删掉 `services/cleanup_service.py` 与 `api/routers/{raw,maintenance}.py`，本线也不受影响。

---

## 2. 事务边界（照抄 SDD §7.5，不许改）

```
BEGIN IMMEDIATE
  ├─ UPDATE staging_batch SET status='ingesting', ingest_started_at=?
  │    WHERE id=? AND status='prechecked'          ← 幂等闸门，rowcount==0 → E2002
  ├─ replay(mapping_snapshot) → rows                ← 用快照重放，不重读用户当前映射
  ├─ 二次 find_by_fp(rows)                          ← 预检到入库之间可能有新数据（EX-22）
  ├─ CREATE TABLE IF NOT EXISTS raw_YYYY_MM × N     ← 按行覆盖的月份按需建
  ├─ INSERT INTO raw_YYYY_MM ...  (分批 executemany，500/批)
  ├─ INSERT INTO "transaction" ... (分批 executemany，500/批)
  └─ UPDATE staging_batch SET status='ingested', report_json=?, mapping_snapshot=?,
       committed_at=?, pending_delete_flag=1
COMMIT
  ↓（事务外，绝不能放在事务里）
sink.on_committed(batch_id, file_path)              ← 唯一注入点，B 线实现
```

三条不可协商的理由：

1. **闸门必须在事务内**：若先单独提交 `ingesting` 再开事务，进程崩溃会留下永久 `ingesting` 脏状态；放在同一事务里，`ingesting` 只存在于事务可见期内，崩溃时 SQLite 自动回滚，批次仍是 `prechecked` —— 天然满足 PRD 9.2「收口规则 4」。
2. **删文件必须在事务外**：文件系统不在事务里，删了之后事务回滚会导致"数据没了文件也没了"。先提交再删，最坏结果是"数据在、文件也在"（由 B 线的启动对账补删）。
3. **DDL 必须在事务内**：`CREATE TABLE` 参与事务回滚，所以"注入异常后 raw 表无残留"这条断言才成立；若 DDL 单独执行，故障注入 1 会失败。

**代码评审硬规则**：`ingest_service.py` 中不得出现 `unlink` / `os.remove` / `Path.unlink`，只允许出现 `self._sink.on_committed(...)`；`test_layering.py` 之外再加一条 grep 门禁（见 §6.3）。

---

## 3. 任务分解

| ID | 任务 | 产出文件 | 依赖 | 人日 | 验收断言 |
|----|------|----------|------|------|----------|
| C3A.1 | 幂等闸门与状态机补 `ingest`/`confirm` | `services/batch_guard.py`、`repositories/staging_repo.py` | Gate 0 | 0.4 | 条件 UPDATE + `rowcount==0` → `E2002`；7×6 矩阵补 2 列共 42 格全覆盖；`ingested`/`discarded`/`failed` 上 `confirm` 全 `E2002` |
| C3A.2 | `RawTableManager`（动态分表，只增不改） | `repositories/raw_repo.py` | Gate 0 | 0.5 | 无数据月份**不建表**；16 列 + 2 索引；`hasattr(mgr,'update_rows')` 为 `False`；表名非法 → `E3002` |
| C3A.3 | confirm 单事务（重放 → 二次去重 → 双写 → 报告） | `services/ingest_service.py`、`repositories/transaction_repo.py`（`insert_many` + C4 空壳签名）、`repositories/staging_repo.py`（`try_enter_ingesting` / `finish_ingest`） | C3A.2 | 0.9 | 跨 5 月样例 → 5 张 raw 表 101/136/182/143/107；注入异常 → raw 与 transaction 均 0 残留、批次回 `prechecked`；四数字自洽 |
| C3A.4 | `confirm` / `report` 端点 | `api/routers/ingest.py`、`api/deps.py`（只增 provider） | C3A.3 | 0.3 | `POST .../confirm` 返回 200 + `IngestReportDTO`；`report?include_skipped=true` 附带 `skipped[]`；重复 `confirm` → 409 `E2002` |
| C3A.5 | 故障注入 1/3/4 + 真实样例验证 | `tests/fault_injection/test_fi_tx_failure.py`、`test_fi_concurrent_confirm.py`、`test_fi_disk_full.py`、`tests/integration/test_ingest_multi_month.py` | C3A.4 | 0.4 | 三条注入全绿；669 行入库 < 1.5s；`monthly` 之和 == `inserted` |

**合计 2.5 人日。**

---

## 4. 关键实现要点

### 4.1 幂等不是"先查后改"

```python
# 反例（TOCTOU：并发两次都查到 prechecked）
if repo.get(batch_id).status == "prechecked":
    repo.update_status(batch_id, "ingesting")

# 正例：条件 UPDATE + rowcount，靠 SQLite 写锁天然串行化
cur = conn.execute(
    "UPDATE staging_batch SET status='ingesting', ingest_started_at=? "
    "WHERE id=? AND status='prechecked'", (now, batch_id))
if cur.rowcount == 0:
    raise BusinessRuleError(
        ErrorCode.BATCH_STATE_CONFLICT,
        "该批次已入库，无需重复提交",
        detail={"batch_id": batch_id},
    )
```

`try_enter_ingesting` 必须在**已开启**的 `BEGIN IMMEDIATE` 内调用（由 `IngestService` 负责开事务），守卫本身不开事务、不提交。

**两个动作的语义分工**（矩阵 7×6 里 `ingest` 与 `confirm` 是两列，别混用）：

| 动作 | 视角 | 允许 | 调用点 |
|------|------|------|--------|
| `CONFIRM` | 用户视角，跳跃式 | `(prechecked) → {ingested}` | 端点 `assert_transition(status, CONFIRM)` |
| `INGEST` | 事务内部，两跳 | `(prechecked) → {ingesting}`、`(ingesting) → {ingested}` | 事务内 `assert_transition(status, INGEST, target=...)` |

其余 5 个状态 × `{INGEST, CONFIRM}` 全部为空 → `E2002`。注意 `ingesting` 在库里查不到（D-8），第二跳只在内存里校验，但它必须存在于矩阵中，否则 `assert_transition(target=INGESTED)` 会误判。

### 4.2 二次去重（EX-22 的真正含义）

预检是"快照"，入库是"当下"。两者之间用户可能：导入另一份重叠账单、手工修正过分类（不影响 `fp`）、撤销过 override。因此入库前必须**重新按 `fp` 查一次**：

```python
dups = transaction_repo.find_fp_in(conn, [r.fp for r in rows if r.fp])
overridden = override_repo.row_nos(conn, batch_id)      # C2 已落表，本线只读
accepted = [r for r in rows if r.is_valid and (r.fp not in dups or r.row_no in overridden)]
```

- `inserted = len(accepted)`、`skipped_dup = 命中 fp 且未 override 的行数`、`skipped_invalid = 非 is_valid 的行数`；
- 自洽断言：`total == inserted + skipped_dup + skipped_invalid`；
- 报告页固定文案「以入库时实际执行结果为准」（EX-22），前端不得拿预检数字当结果。

> `override` 的语义是"用户说这行不是重复"，所以 override 命中时**绕过 fp 判断**。这条在 C2 只影响预检 label，C3 才第一次影响真实写入 —— 必须写用例。

### 4.3 `RawTableManager` 只增不改

```python
class RawTableManager:
    def ensure_table(self, conn, month: str) -> None: ...   # month="2026_06"
    def write_rows(self, conn, month: str, rows) -> int: ... # executemany，返回写入数
    # 故意不提供 update_rows / delete_rows —— I7 靠"没有这个方法"强制，而非靠自觉
```

- 表名必须先过 `infra/raw_naming.table_name()`（Gate 0），非法月份直接抛 `E3002` **RAW_TABLE_ERROR**；这是全项目唯一的 SQL 字符串拼接处，必须在代码注释里标明。
- 月份来源：`occurred_at[:7].replace("-", "_")`，**不信任文件名**。
- 只建"有行要写"的月份：先按 `month` 分组，再对分组键调用 `ensure_table`。样例无 2025-12 数据 → `raw_2025_12` 不存在。
- `raw_payload` 存整行原貌：`json.dumps({列名: 原值}, ensure_ascii=False, sort_keys=True)`，**保留原始字符串**（含 `已退款¥26.40` 这类变体），不做单位换算；换算值另存 `amount_cents`。`sort_keys=True` 保证同一行两次入库字节一致（可重放校验）。

### 4.4 双写的顺序与批大小

```
先 raw 后 transaction，都按 500 行分批 executemany
```

- 顺序不可换：`raw` 是审计链终点，若 `transaction` 先写成功而 `raw` 失败，会出现"有主数据无原始行"的不可解释状态；反过来失败时两者一起回滚，且 `raw` 已写入的部分也在事务内。
- 500 行的理由与 C2 的 `find_fp_in` 一致（SQLite `IN` 上限 999 的同类保守值），且能把 5 万行的峰值内存压住。
- `rows` 用**生成器**消费（`replay` 返回 `list`，本线内部按 500 切片），不要一次性 `list(map(...))` 两份。

### 4.5 报告四数字的口径（前端已按此实现）

| DTO 字段 | 定义 | 自洽性断言 |
|----------|------|-----------|
| `total` | 重放得到的数据行数（含无效行，不含空行） | `total == inserted + skipped_dup + skipped_invalid` |
| `inserted` | 实际写入 `transaction` 的行数 | 等于 raw 总写入行数 |
| `skipped_dup` | 因 `fp` 命中且未 override 被跳过的行数 | — |
| `skipped_invalid` | `is_valid=False` 被跳过的行数（**D-6**） | C3 阶段真实样例为 0，需造夹具验证 > 0 的分支 |
| `pending` | 写入行中 `status='pending'` 的数量 | 本周期 `pending == inserted` |
| `monthly` | `{"raw_2026_06": 101, ...}`，键为**归档表名** | `sum(monthly.values()) == inserted` |
| `files_deleted` | 事务提交后缓冲区文件是否已删除 | 由 `sink` 的返回结果填充（**D-7**） |
| `finished_at` | 提交时刻（DB 列是 `committed_at`，DTO 字段改名） | — |

这四个数字是前端"导入报告页"的唯一数据源，**不可**用预检结果替代。前端 `pages/import.js` 已按 `batch_id / finished_at / files_deleted / total / inserted / skipped_dup / pending / monthly / skipped_invalid` 渲染，字段名不可漂移。

### 4.6 `mapping_snapshot` 的冻结写入（D-5）

C2 的实现是：预检成功时写 `mapping_snapshot`、重解析时置 `NULL`（可变）。C3 在事务内读取该快照并**原样回写**：

```python
snapshot = orchestrator.resolve_snapshot(batch)     # 不重读用户当前映射
rows = orchestrator.replay(batch_id, snapshot)
...
staging_repo.finish_ingest(conn, ..., mapping_snapshot=json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
```

`finish_ingest` 之后该字段**只读**：任何后续写入都会破坏 I11。为此在合稿阶段加守卫：`staging_repo` 的 `UPDATE ... SET mapping_snapshot` 只允许出现在 `update_precheck`（C2，置值/NULL）与 `finish_ingest`（C3，冻结）两处。

### 4.7 磁盘满（EX-23）的两个阶段

| 阶段 | 表现 | 返回 | 数据 |
|------|------|------|------|
| 建表/写入时 `OSError(ENOSPC)` | SQLite 抛 `sqlite3.OperationalError` | 507 `E4001` | 事务回滚，raw 与 transaction 均无残留 |
| `shutil.disk_usage` 余量不足（预防） | 入库前预检 | 507 `E4001` | 未开事务，批次仍 `prechecked` |

两者都**不得**留下半成品 raw 表 —— 断言方式是检查 `sqlite_master` 里 `raw_%` 的表数量与入库前相等。

---

## 5. 对外契约

### 5.1 端点（本线 2 个）

| 方法 | 路径 | 返回 |
|------|------|------|
| POST | `/api/v1/staging/batches/{id}/confirm` | 200 + `IngestReportDTO`；状态冲突 409 `E2002`；事务失败 500 `E3001`；磁盘满 507 `E4001` |
| GET | `/api/v1/staging/batches/{id}/report?include_skipped=false` | 200 + `IngestReportDetailDTO`（`skipped[]` 仅在 `include_skipped=true` 时填充） |

> **D-7 的关键后果**：`confirm` 在"数据已提交但删文件失败"时返回 **200 + `files_deleted=false`**，不是 409。前端 `pages/import.js` 的 catch 分支对所有非 `E2002` 错误统一提示「（已回滚，可重试）」——若返回 409 `E4003`，用户会被误导去重复导入已入库的数据。SDD §7.5 的"返回 409"在此处按 ADDITIVE 偏离，理由与签字见合稿文档 §5。

### 5.2 给 B 线的交接面（只此三条）

| 契约 | 语义 | B 线用途 |
|------|------|----------|
| `DeleteFailureSink.on_committed(batch_id, file_path) -> DeleteOutcome` | 事务**外**调用，返回是否删除成功 | B 线实现为 `CleanupService`：成功则清零 `pending_delete_flag`，失败则入 `cleanup_queue` |
| `IngestReportDTO.monthly` 键为 `raw_YYYY_MM` | 归档表名 → 行数 | B 线 `/raw/months` 的 `count` 与之逐月相等 |
| `raw` 行的 `(batch_id, row_no)` 唯一且等于 `ParsedRow.row_no` | 追溯主键 | B 线 `/trace` 按此查询（**跳过行不写 raw**，见 D-6） |

### 5.3 给 C4 的空壳签名

`transaction_repo.py` 本线必须留下（只写签名 + `raise NotImplementedError`）：`iter_for_recalc(scope)`、`count_by(...)`、`sum_by_category(...)`、`patch_status(...)`。C4 填实现时不得改签名。

---

## 6. 测试与验收

### 6.1 必写用例

| 用例 | 断言 |
|------|------|
| U-IG-01 | 幂等闸门：非 `prechecked` 状态 `confirm` → 409 `E2002`，且 `status` 不变 |
| U-IG-02 | 并发双提交（两个线程）：恰一个 200，另一个 409；`transaction` 无重复 `fp` |
| U-RT-01 | `RawTableManager` 无 `update_rows` / `delete_rows` 方法（`hasattr` 断言） |
| U-RT-02 | 月份非法（`"2026_6"` / `"raw_;DROP"`）→ `E3002`，不执行任何 SQL |
| U-RT-03 | 只建有数据的月份表；`sqlite_master` 里 `raw_%` 数量 == 样例月数 |
| `test_ingest_multi_month.py` | 支付宝样例 → 5 张表 101/136/182/143/107；`inserted=669`；`monthly` 之和 = 669 |
| `test_ingest_all_dup.py`（EX-09） | 同一文件二次入库 → `inserted=0`、`skipped_dup=669`、批次 `ingested` |
| `test_ingest_skipped_invalid.py`（D-6） | 造 3 行不可解析 → `skipped_invalid=3`、raw 与 transaction 均无这 3 行、`report_json.skipped` 有明细 |
| `test_override_bypass_dup.py` | override 行即使 `fp` 命中也入库，`inserted` 包含它 |
| `test_raw_payload_fidelity.py` | 抽 5 条 `raw_payload`，字段与原文件行逐项一致（含 `已退款¥26.40`） |
| `test_fi_tx_failure.py` | `insert_many` 内部第 2 批抛 `RuntimeError` → 批次回 `prechecked`；raw 与 transaction **均无残留**；500 `E3001`；可立即重试成功 |
| `test_fi_disk_full.py` | `ENOSPC` → 回滚 + 507 `E4001`；`raw_%` 表数量不变 |
| `test_perf_ingest.py` | 669 行入库 < 1.5s（`perf_counter`） |

> 故障注入 1 的注入点必须在 `insert_many` **内部按批计数**，不能 mock 整个 repo —— 否则测的是 mock 不是事务。

### 6.2 出口检查表

- [ ] 跨 5 月样例 → 5 张 raw 表，行数逐月相等（101/136/182/143/107）
- [ ] 注入异常后 `SELECT COUNT(*) FROM raw_2026_06` 与 `transaction` 均为 0，且 `raw_%` 表数量不变
- [ ] 并发确认：一个 200、一个 409，`transaction` 无重复 `fp`
- [ ] `raw_payload` 抽样 5 条与原文件行逐项一致
- [ ] `RawTableManager` 无 `update` / `delete` 方法；`hasattr` 断言进 CI
- [ ] 无数据月份不建表
- [ ] `total == inserted + skipped_dup + skipped_invalid`；`sum(monthly.values()) == inserted`
- [ ] `ingest_service.py` 全文无 `unlink` / `os.remove`
- [ ] `SELECT DISTINCT status FROM "transaction"` 只返回 `pending`
- [ ] 打 tag `c3a-done`

### 6.3 新增 CI 门禁（两条 grep）

```
1) UPDATE staging_batch  只允许出现在 repositories/staging_repo.py 与 repositories/cleanup_repo.py
   （后者只允许含 pending_delete_flag / 中断重置，见合稿 §7）
2) mapping_snapshot =    只允许出现在 staging_repo.update_precheck 与 staging_repo.finish_ingest
```

---

## 7. 风险与回退

| 风险 | 表现 | 处理 |
|------|------|------|
| 事务内做文件 IO | 删文件耗时长，写锁被长期占用 | `ingest_service.py` 禁止出现 `unlink`（grep 门禁） |
| 表名拼接被注入 | 月份参数含非法字符 | 强制走 `infra/raw_naming.table_name()`，不通过 → `E3002` |
| `pending_delete_flag` 语义漂移 | 有人用它表示"待删除主数据" | 只有 `finish_ingest` 能置 1，只有 B 线能置 0；DDL 注释写死"仅表示缓冲区物理文件的删除意图" |
| 大批量 executemany 内存高 | 5 万行爆内存 | 500 行分批；禁止把 `rows` 二次物化成两个 list |
| 金额/时间被二次换算 | 入库时又 `×100` | 本线**只**搬运 `ParsedRow.amount_cents`，出现 `* 100` 即为缺陷（全库只允许在 `parse_amount_to_cents`） |
| 空批次入库 | `inserted=0` 也建了表 | `accepted` 为空时跳过 `ensure_table`，但仍置 `ingested`（EX-09 要求批次归档） |

**回退**：本线一旦写入真实数据，`raw_*` 与 `transaction` 就不可逆。开发期**必须使用临时 `data_dir`**（`tmp_path` fixture），禁止在真实数据目录上调试。代码回退只需还原本线 6 个文件，但已入库数据只能靠 C5 的备份能力恢复。

---

## 8. 交接物

给 B 线与 C4：

1. `IngestService.confirm(batch_id)` 可用，`DeleteFailureSink` 注入点稳定（`NullSink` 可替换）；
2. `raw_YYYY_MM` 16 列 + 2 索引与 SDD §5.2 模板逐列一致；
3. `report_json` 的完整结构（含 D-6 的 `skipped[]`），B 线的 `/raw/months` 与 `/trace` 都要与它对得上；
4. `transaction_repo` 的 C4 空壳签名已就位；
5. 故障注入 1/3/4 已进入 CI（C4/C5 每次提交都会跑）。
