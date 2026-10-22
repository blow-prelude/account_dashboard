# C2-B · 缓冲区与向导线（staging）

> 定位：把「用户上传的文件」变成「可预检的批次」，把「用户的映射与决策」落库。
> **本线不认识 Excel、不认识 CSV、不算指纹、不判断表头** —— 这些全部通过 D0 契约向 A 线索取。
> 人日：**3.0** ｜ 并行：与 A 线零文件交集 ｜ 出口：15 个端点可用、预检零写入、`transaction` 表仍为 0 行
> 验收基线：[`C2-解析内核与导入缓冲区.md`](./C2-解析内核与导入缓冲区.md)

---

## 1. 边界

### 1.1 本线做（In Scope）

| 能力 | 落点 |
|------|------|
| 缓冲区文件管理 | `infra/buffer_file.py` |
| 批次持久化与状态机 | `repositories/staging_repo.py`、`api/guards.py`（`BatchGuard` 的 C2 部分） |
| 渠道模板 | `repositories/template_repo.py`、`services/mapping_service.py` |
| 强制新增留痕 | `repositories/override_repo.py` |
| 去重预检（只读） | `services/dedup_checker.py`、`repositories/transaction_repo.py`（仅 `find_fp_in`） |
| 编排 | `services/import_orchestrator.py` |
| 15 个端点 | `api/routers/staging.py` |
| DTO | `models/staging.py` |

### 1.2 本线不做（Out of Scope）

- **不解析文件格式**：不 import `openpyxl` / `csv` / `charset`，不写任何列索引映射逻辑。
- 不算指纹：`ParsedRow.fp` 由 A 线给出，本线只读。
- 不实现 `confirm` / `report` / 孤儿清理（C3）。
- 不写 `raw_*`、不建分表、不删已入库文件（C3）。
- 不写统计口径（C4）。

> **可验证的独立性**：把 `infra/parsers/{wechat_xlsx,alipay_csv,generic,cleaning,header_detect}` 全部换成 `tests/fakes/fake_parser.py`，本线的 15 个端点与全部用例仍应全绿。

---

## 2. 并行前提：FakeParser

A 线的真实适配器可能还没好。本线从第一天就用假解析器开发，**注入点只有一处**（`ParserRegistry`）：

```python
# tests/fakes/fake_parser.py（B 线自己维护）
class FakeParser:
    name = "fake"
    channel = "other"

    def __init__(self, rows: list[ParsedRow], *, error: ParseError | None = None) -> None: ...

    def sniff(self, path: Path) -> bool:
        return True

    def parse(self, path: Path, spec: MappingSpec | None = None) -> ParseResult:
        if self._error:
            raise self._error
        return ParseResult(rows=self._rows, header_row_no=0, encoding="fake",
                           adapter="fake", columns=13, meta=ParseMeta())
```

三个失败态各一个构造器：`fake_encoding_error()` / `fake_header_error()` / `fake_empty_document()`。
合稿时把 `FakeParser` 换成 `registry.default_registry()`，不改任何业务代码。

---

## 3. 任务分解

| ID | 任务 | 产出文件 | 依赖 | 人日 | 验收断言 |
|----|------|----------|------|------|----------|
| C2B.1 | 缓冲区文件管理 | `infra/buffer_file.py` | D0 | 0.5 | 流式落盘（峰值 < 8MB）；`.tmp` → `os.replace`；余量 < 200MB → `E4001`(507)；删失败重试 3 次后入队/报错；孤儿扫描忽略 `.tmp` |
| C2B.2 | 批次仓储与状态机 | `repositories/staging_repo.py`、`api/guards.py`、`models/staging.py` | C2B.1 | 0.5 | 7 个状态字面量可写；合法流转放行、非法 → `E2002`；分页 `total` 正确；JSON 字段（`mapped_fields`/`parse_meta`）读写无损 |
| C2B.3 | 上传/解析/预览/丢弃 | `services/import_orchestrator.py`、`api/routers/staging.py`（批次段）、`api/deps.py`（provider） | C2B.2 | 0.6 | 上传后 `status=uploaded` 且文件在缓冲区；解析后 `mapped_pending`；失败批次可重试且不重复建批次；预览不改状态 |
| C2B.4 | 映射与模板 | `services/mapping_service.py`、`repositories/template_repo.py`、`api/routers/staging.py`（mapping 段） | C2B.3 | 0.5 | 三必需列缺失 → `E1007`；保存映射后 `prechecked`；模板三策略 409/降级/另存；同渠道 default 唯一 |
| C2B.5 | 去重预检与强制新增 | `services/dedup_checker.py`、`repositories/override_repo.py`、`repositories/transaction_repo.py`（`find_fp_in`） | C2B.4 | 0.5 | 预检前后 `transaction`/`raw_*` 计数不变；`new/dup/pending_manual` 三态正确；override 翻转且留痕、可撤销 |
| C2B.6 | 缓冲区运维端点与收口 | `api/routers/staging.py`（usage/ensure-dir/orphans）、`api/validators.py` | C2B.3 | 0.4 | 占用统计含阈值；`ensure-dir` 重建成功；孤儿清单不含 `.tmp`；分页越界 → `E1010` |

**合计 3.0 人日。**

---

## 4. 关键实现要点

### 4.1 上传：先落盘，再建批次，最后解析

顺序不可换：

```
① 入口校验（扩展名/MIME/声明大小）      → E1001 / E1005
② 磁盘余量检查（< 200MB）               → E4001 / 507
③ 流式写入 buffer/<uuid>.tmp            → 超 5MB → E1005，删临时文件
④ os.replace → buffer/<uuid>.<ext>      → 保证不出现半个文件
⑤ INSERT staging_batch(status='uploaded')
⑥ 解析（registry.resolve → adapter.parse）
   ├─ 成功 → status='mapped_pending'，写 encoding/adapter/header_row_no/parse_meta/total_rows
   ├─ ParseError → status='failed' + fail_reason（**保留文件**，供重试）
   └─ 行数 > 50000 → E1006（批次记 failed）
```

为什么先落盘再建批次：若先建批次后落盘失败，会留下"批次有、文件无"的脏记录，健康检查的孤儿计数与批次详情会互相矛盾。

`stored_name = f"{uuid4().hex}{ext}"`，原始文件名只进 `file_name` 展示字段，**永不用于拼路径**。

### 4.2 状态机：三处必须一致

`BatchGuard.assert_transition(current, action)` 的表就是 SDD §5.6 的允许操作矩阵。C2 只实现四个动作（`parse` / `map` / `precheck` / `discard`），C3 再补 `confirm`。

| 当前状态 | parse | map | precheck | discard |
|----------|-------|-----|----------|---------|
| `uploaded` | ✅ → mapped_pending / failed | ❌ | ❌ | ✅ → discarded |
| `failed` | ✅ → mapped_pending / failed | ❌ | ❌ | ✅ → discarded |
| `mapped_pending` | ❌ | ✅ → prechecked | ❌ | ✅ → discarded |
| `prechecked` | ✅ → mapped_pending | ✅ → prechecked | ✅ | ✅ → discarded |
| `ingesting` / `ingested` / `discarded` | ❌ | ❌ | ❌ | ❌ |

**裁决 D-1（需两线签字）**：SDD §5.6 图里写「`mapped_pending` → `prechecked`：映射确认 + 预检完成」，但矩阵里 `mapped_pending` 的「预检」是 ❌。本线取**矩阵优先**：

- `PUT /mapping` 成功即视为「映射已确认」，状态置 `prechecked`；
- `POST /precheck` 只允许在 `prechecked` 上调用，可重复（幂等，用于 override 后刷新）；
- 在 `mapped_pending` 上调 precheck → `409 E2002`，文案「请先确认字段映射」。

这样预检结果永远不会基于未确认的映射，且 7×6 矩阵的其余行不需要改。

### 4.3 映射校验：硬三软二（裁决 D-2）

| 字段 | 缺失后果 |
|------|----------|
| `occurred_at` / `amount` / `direction` | **硬阻断** `E1007`，文案指明缺哪一列 |
| `counterparty` / `item` | 允许保存，返回 `warnings: ["缺少交易对方，去重精度会下降"]` |

SDD T02.4 原文是「五核心字段缺失阻断」，但银行 CSV 常常没有「商品」列；硬卡五列会让通用渠道不可用。此处按硬三软二实现，**在 `CONTRACT-CHANGELOG` 记一条 ADDITIVE**，并在合稿文档 K6 处复核。

其余校验：列索引 `-1 ≤ i < columns`；`amount_scale ∈ {1,100}`；`direction_map` 的值必须是三个枚举之一（否则 `E1008`）。

### 4.4 模板三策略（EX-20）

| policy | 行为 | 返回 |
|--------|------|------|
| `abort` | 不写 | `409 E2003` |
| `overwrite` | 同事务内旧 default 置 0 → 新记录置 1 | 200 |
| `save_as` | 新记录 `is_default=0`，重名自动加 `(2)` | 200 |

DDL 已有部分唯一索引 `uq_template_default ON channel_template(channel) WHERE is_default=1`，所以"先降级后插入"必须在**同一事务**内，否则中间态会撞唯一索引。

### 4.5 预检：只读，且要能自证

```python
def label_rows(self, rows: Sequence[ParsedRow]) -> dict[int, str]:
    # 1) is_valid=False → "pending_manual"（不参与指纹比对）
    # 2) fp 非空 → 分片 500 查 transaction.fp
    # 3) 命中 → "dup"；未命中 → "new"
```

- 只查 `"transaction"`，**不查 raw**（raw 只在入库事务内产生，C2 阶段必然为空）。
- 分片 500：SQLite 的 `IN` 参数上限是 999（旧版本），500 是安全值。
- 自证零写入：用例里在调用前后各数一次 `transaction` / `raw_*` / `staging_batch.total_rows`，全部相等。

`summary` 四数字：`{"total","new","dup","pending_manual"}`，且 `new + dup + pending_manual == total`。

### 4.6 override 的幂等语义

`POST /overrides {row_no, reason}`：

- 同 `(batch_id, row_no)` 重复调用 → 更新 `reason`，不新增行（主键即幂等键）；
- `row_no` 必须落在 `1..total_rows`，否则 `E1008`；
- `reason` 去空白后非空，最长 200；
- 撤销 = `DELETE`，不存在时返回 `{"removed": false}`（幂等，不报错）。

`precheck` 返回的 label 翻转：`dup → new`，且 `override=true`。

### 4.7 分页与参数校验

`page ≥ 1`、`10 ≤ page_size ≤ 200`，越界 → `E1010`（422）。`sort` 白名单在 C2 只有 `created_at`、`-created_at`。

### 4.8 Windows 上的文件删除

`buffer_file.delete_with_retry(path, attempts=3)`：`PermissionError` → `gc.collect()` + 100/200/300ms 退避。C2 的 `discard` 要求删除成功才置 `discarded`；删不掉 → `409 E4003`、状态不变、提示重试。**C3 会改成"先置状态后入待清理队列"**，边界在此声明清楚。

---

## 5. 对外契约

### 5.1 15 个端点（C2 范围）

| 方法 | 路径 | 任务 |
|------|------|------|
| POST | `/api/v1/staging/batches` | C2B.3 |
| GET | `/api/v1/staging/batches` | C2B.3 |
| GET | `/api/v1/staging/batches/{id}` | C2B.3 |
| POST | `/api/v1/staging/batches/{id}/parse` | C2B.3 |
| GET | `/api/v1/staging/batches/{id}/preview` | C2B.3 |
| POST | `/api/v1/staging/batches/{id}/discard` | C2B.3 |
| PUT | `/api/v1/staging/batches/{id}/mapping` | C2B.4 |
| GET | `/api/v1/staging/templates` | C2B.4 |
| POST | `/api/v1/staging/templates` | C2B.4 |
| POST | `/api/v1/staging/batches/{id}/precheck` | C2B.5 |
| POST | `/api/v1/staging/batches/{id}/overrides` | C2B.5 |
| DELETE | `/api/v1/staging/batches/{id}/overrides/{row_no}` | C2B.5 |
| GET | `/api/v1/staging/usage` | C2B.6 |
| POST | `/api/v1/staging/ensure-dir` | C2B.6 |
| GET | `/api/v1/staging/orphans` | C2B.6 |

留给 C3：`confirm`、`report`、`orphans/cleanup`。

### 5.2 给 C3 / C4 的持久化契约

| 契约 | 语义 | 谁依赖 |
|------|------|--------|
| `ImportOrchestrator.replay(batch_id) -> list[ParsedRow]` | 用 `mapping_snapshot`（C3 写入）或 `mapped_fields`（C2 写入）重放解析 | C3 入库、C4 重算 |
| `DedupChecker.label_rows(rows) -> dict[int,str]` | 入库时二次去重复用（EX-22） | C3 |
| `staging_repo.finish_ingest(...)` | 由 C3 实现（C2 只留签名） | C3 |
| `transaction_repo.find_fp_in(conn, fps)` | 只读指纹查询，C3 会扩展同类方法 | C3 / C4 |

`mapping_snapshot` 与 `mapped_fields` 的区别必须写进代码注释：前者是**入库时刻的不可变快照**（I11，只写一次），后者是用户当前的映射（可改）。C2 只写 `mapped_fields`。

---

## 6. 测试与验收

### 6.1 用例

| 用例 | 断言 |
|------|------|
| `test_upload_stream.py` | 5MB 文件峰值内存 < 8MB（`tracemalloc`）；中断后无半文件；`.tmp` 已清理 |
| `test_upload_disk_full.py` | 余量不足 → `E4001` / 507，且不留临时文件 |
| `test_upload_limits.py` | 6MB → `E1005`(413)；50001 行 → `E1006`(422) |
| `test_batch_state_machine.py` | 7 状态 × 4 动作全矩阵；非法流转全 `E2002` |
| `test_parse_retry.py` | 失败批次重试成功；`id` 不变、不新增批次行 |
| `test_mapping_validation.py` | 缺三必需列 → `E1007`；缺对方 → 200 + warning；索引越界 → `E1008` |
| `test_template_policies.py` | abort 409 / overwrite 旧 default 置 0 / save_as 重名加后缀 |
| `test_precheck_readonly.py` | 前后 `transaction`、`raw_*`、`total_rows` 全等（I-PC-01） |
| `test_precheck_labels.py` | 同文件重复上传后第二次预检全 `dup`；缺时间的行 `pending_manual` |
| `test_override_flip.py` | override 后 `dup→new` 且 `override=true`；撤销回到 `dup`；重复标记不新增行 |
| `test_pagination.py` | `page_size=9` / `201` → `E1010`；`total` 与 `total_pages` 正确 |
| `test_preview_limit.py` | 默认 20 行；`limit=1000` 被截到 50 |

### 6.2 出口检查表

- [ ] `SELECT COUNT(*) FROM "transaction"` 为 0（本线不得越界入库）
- [ ] 上传 → 解析 → 映射 → 预检 四步在 FakeParser 下全绿
- [ ] 5MB 文件峰值内存 < 8MB
- [ ] 预检零写入可自证
- [ ] 模板同渠道 default 永远只有 1 条（并发插两次也只 1 条）
- [ ] 非法流转矩阵 28 格全覆盖
- [ ] 分页/枚举/路径参数的错误码与 HTTP 状态符合 §6.5
- [ ] `api` 层无 `sqlite3`、无 `repositories` import（分层测试）
- [ ] 打 tag `c2b-done`

---

## 7. 风险与回退

| 风险 | 表现 | 处理 |
|------|------|------|
| Windows 文件被占用 | `discard` 必然失败 | 删除重试 + `gc.collect()`；仍失败返回 409 并提示（C3 改为队列） |
| 大文件内存 | 5MB 上传 OOM | 1MB 分块 + 峰值断言，禁止 `await file.read()` 整读 |
| 状态机被绕过 | 业务层直接 UPDATE status | 只允许 `staging_repo` 的具名方法改状态，方法内部调 `BatchGuard` |
| 模板唯一索引冲突 | overwrite 并发 | 同事务"先降级后插入"，`busy_timeout` 兜底 |
| 预检变慢 | 5 万行 `IN` 查询 | 分片 500；后续 C4 再看执行计划 |
| DTO 与前端不一致 | 字段名漂移 | FZ-2 已冻结；改字段必须写 `CONTRACT-CHANGELOG` |

**回退**：本线的库层变更全部在 `staging_batch`（C1 已建），不新增表，回退只需回代码；但 `mapped_fields` 的 JSON 结构一旦被 C3 依赖就不能改键名。

---

## 8. 交接物

给 C3：

1. `ImportOrchestrator.replay(batch_id)` 可用（FakeParser 与真解析器都能跑）；
2. `BatchGuard` 已覆盖 4 个动作，C3 只需加 `confirm` 与条件 UPDATE；
3. `staging_batch` 的字段语义表（谁写、何时写、能否改）；
4. `DedupChecker.label_rows` 可直接用于入库二次去重；
5. `cleanup_queue` 的写入在 C3 接管（C2 的 discard 是同步删除）。
