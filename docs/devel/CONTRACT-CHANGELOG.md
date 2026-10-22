# 契约变更记录（CONTRACT-CHANGELOG）

> 规则：**只追加，不修改历史条目**。任何 DTO、端点签名、错误码、表结构、`null` 语义的变化都必须在此登记，否则视为契约漂移缺陷。
> 格式：`日期 | 冻结点 | 变更类型 | 对象 | 说明 | 影响面 | 回归用例`

---

## 1. 变更级别定义

| 级别 | 含义 | 允许的时机 | 下游动作 |
|------|------|-----------|----------|
| **BREAKING** | 字段改名/删除、类型变化、`null` 语义反转、端点路径变化、错误码语义变化 | **仅联调前**，且需评审 | 前端重新生成类型；重跑该冻结点全部回归 |
| **ADDITIVE** | 新增可选字段（有默认值）、新增端点、新增错误码 | 任意时刻 | 前端可暂不消费；重跑契约核对 |
| **INTERNAL** | 实现变化但契约不变（SQL 改写、缓存、日志） | 任意时刻 | 无需动作，但需说明为什么契约不受影响 |

---

## 2. 当前冻结基线

| 冻结点 | 时点 | 对象 | 状态 |
|--------|------|------|------|
| FZ-1 | C1 收口 | `ApiResponse`、`PageMeta`、`Page`、`ErrorCode`（37 值）、退出码 1~5、`/health` | **已冻结 v1（2026-10-22）** |
| FZ-2 | C2 收口 | `BatchDTO`、`BatchDetailDTO`、`ParseMetaDTO`、`MappingReq`、`PrecheckResultDTO`、7 个批次状态 | **已冻结 v1（2026-10-22）** |
| FZ-3 | C3 收口 | `IngestReportDTO`、`RawRecordDTO`、`raw_YYYY_MM` 列定义、`pending_delete_flag`、7×6 状态矩阵 | 待冻结 |
| FZ-4 | C4 收口 | 12 指标 DTO、`base_filter` 语义、`period/anchor` 格式、`null` 语义、三入口同源 | 待冻结 |

> 「待冻结」在对应周期出口检查表通过后改为「已冻结 v1」，并在此追加条目。

---

## 3. 变更流水

### 2026-10-22 · 前端 · INTERNAL · 前端消费面对齐 C2 与三处待澄清

> 本条目**不改变后端契约**，只登记前端已按哪些字段实现、以及联调前必须确认的歧义，避免"代码在用、文档没写"。

- **对象**：`PreviewDTO` / `PreviewRowDTO` / `MappingResultDTO` / `ParseInfoDTO` / `TemplateDTO` / `OrphanFileDTO`
- **前端已按 C2 实际实现消费**：
  - 预览读 `headers` + `rows[].cells`，映射建议读 `suggested_mapping`；`limit` 超 50 由后端截断，前端不再传 200
  - `PUT /mapping` 后把响应 `batch` 作为新状态，`warnings` 逐条提示；模板不依赖该端点的 409
  - 解析失败（4xx + `detail.batch_id`）时前端进入"失败可重试"态，不丢批次上下文
  - 模板保存统一走 `POST /staging/templates`，`policy=abort|overwrite|save_as` 显式落库
  - 孤儿文件读 `size`（不是 `size_bytes`）
- **待 C4/C5 冻结（前端暂按推定字段实现）**：`OverviewDTO`、`KpiDTO`、`SummaryDTO`、`PendingGroupDTO`、`RuleDTO.hit_count`、`CategoryNodeDTO.children[].ref_count`、`SettingsDTO` 键名、`BackupDTO`。推定表见 `docs/frontend/前端实现说明-v1.0.md` §4.2。
- **三处待澄清**：
  1. `category_l1/l2` 在 PRD 附录 B 是「支出 → 餐饮美食」，但 SDD §9.4 的统计 SQL 用 `category_l1` 作为展示大类。前端展示统一取 `slice.l2 || slice.l1`；C4 需确认 `level=1/2` 的分组语义。
  2. `KpiDTO` 缺「储蓄率/日均支出」环比。前端在字段缺失时显示「—」，不自行计算；若 C4 愿意补，建议 `savings_mom`、`daily_avg_cents`、`daily_avg_mom`（ADDITIVE）。
  3. 报表 DTO 无「周期对比」序列。前端用 `/stats/trend` 的 `day/week/month` 分桶画对比柱，不做二次聚合；若 C4 增加 `comparison` 字段，可替换。
- **影响面**：`src/account_dashboard/static/**`；不涉及 SQL、迁移与后端路由
- **回归**：`node --experimental-default-type=module scripts/check-frontend.mjs`（三入口同源、导入幂等、模板 E2003、重算、备份回退）


### 2026-10-22 · C2-B 实施 · INTERNAL · `errors.py` 中性化（Gate 0 / K10）

- **对象**：`ErrorCode`（37 值）、`DEFAULT_STATUS`、`AppError`、`EntryValidationError`/`BusinessRuleError`/`TransactionError`/`FileIOError`
- **变更前**：定义在 `src/account_dashboard/api/errors.py`
- **变更后**：搬到 `src/account_dashboard/errors.py`（包根叶子模块），`api/errors.py` 只保留四个处理器并 re-export
- **原因**：C2 起 `services` 必须抛 `AppError`（`E1007`/`E2002`/`E2003`…），而分层门禁禁止 `services → api`；不搬就会出现"两套错误风格并存"，C3 更难收
- **契约不变**：37 个码值、HTTP 映射、三段式响应形状、`from account_dashboard.api.errors import ...` 的既有 import 全部照旧
- **影响面**：C2~C5 全部服务层；`api/routers/**` 仍不得 import `repositories`
- **回归**：`tests/integration/test_errors.py`（码值基数 37 与四组分布）、`tests/integration/test_layering.py`（全绿）

### 2026-10-22 · C2-B 实施 · ADDITIVE · FZ-2 的 DTO 首次落地与一处加字段

- **对象**：`ParseMetaDTO.columns`（新增）、`MappingResultDTO` / `PreviewDTO` / `PreviewRowDTO` / `TemplateReq` / `OverrideReq` / `BufferUsageDTO` / `EnsureDirDTO` / `OrphanFileDTO`（首次落地）
- **变更**：
  - `ParseMetaDTO` 增加 `columns: int = 0`（有默认值，additive）。原因：映射校验要判列索引上界，否则每次 `PUT /mapping` 都得重新解析一遍文件
  - `BatchDetailDTO.mapped_fields` 的运行时类型取 `MappingSpec`（比 `MappingReq` 少一个 `save_template`）：存的是"映射本身"，`save_template` 是请求意图而非映射内容
  - `MappingResultDTO{batch, warnings, template?}`：承载 D-2 的 `warnings` 与 `save_template=True` 时回写的模板
  - `PreviewDTO{..., headers, suggested_mapping, rows, limit, truncated}`：`limit` 超上限**截断**到 50 而非报错（只读操作，宽容优于严格）
- **影响面**：前端映射页/预览页的类型生成；C3 只读，不受影响
- **回归**：`test_mapping_validation.py`、`test_preview_limit.py`、`test_staging_endpoints.py`（15 端点集合）

### 2026-10-22 · C2-B 实施 · ADDITIVE · run 依赖新增 `python-multipart`

- **对象**：`pyproject.toml` 的 `dependencies`
- **变更**：新增 `python-multipart>=0.0.9,<0.1`
- **原因**：`POST /staging/batches` 是 `multipart/form-data`；FastAPI 在**注册路由时**即校验该依赖，缺失会让整个 `create_app()` 抛 `RuntimeError`（不是等到上传时才报）
- **影响面**：`uv sync` 后生效；打包产物需带上该依赖
- **回归**：`tests/integration/test_staging_endpoints.py`

### 2026-10-22 · C2 拆分 · ADDITIVE · 批次状态机与映射校验的四处澄清（D-1~D-4）

> 状态：**已裁决，随 C2 实施落地**。四条都源于 SDD 内部冲突或未展开，必须在 A/B 并行开发前定死，否则两条线会各写一套。

- **D-1 批次状态机**：`PUT /mapping` 成功即置 `prechecked`（"映射已确认"）；`POST /precheck` 只允许在 `prechecked` 上调用且可重复；在 `mapped_pending` 上调 `precheck` → `409 E2002`。
  - 依据：SDD §5.6 的流程图与允许操作矩阵互相矛盾，取**矩阵优先**。
  - 影响面：`BatchGuard` 的 C2 动作表；C3 的 `confirm` 只能从 `prechecked` 进入 `ingesting`。
  - 回归：B 线 `test_batch_state_machine.py`（7×4 矩阵）、合稿验收 #4。
- **D-2 映射校验从「五核心」改为「硬三软二」**：`occurred_at`/`amount`/`direction` 缺失 → `E1007`(400)；`counterparty`/`item` 缺失 → 200 + `warnings`。
  - 依据：SDD T02.4 写「五核心缺失阻断」，但 `MappingReq` 把这两列定义为可选；银行 CSV 常无「商品」列，硬卡会让 `generic` 渠道不可用。
  - 影响面：`mapping_service.validate`；前端映射页的提示文案。
  - 回归：B 线 `test_mapping_validation.py`。
- **D-4 `MappingSpec.amount_scale` 语义**：定义为「原始数值 → 分」的倍率，取值 `{1, 100}`；`1` 表示账单单位是元（内部 `×100`），`100` 表示账单已是分（不再乘）。
  - 依据：SDD 只给了字段名与默认值 1，未定义行为。
  - 影响面：A 线 `parse_amount_to_cents`、B 线映射校验。
  - 回归：A 线 `test_cleaning_amount.py`（`scale=100` 分支）。
- **D-3（不是契约变更，登记备查）**：时间/金额不可解析的行在 C2 只标记 `is_valid=False` + `pending_manual`，**不写 `transaction`**（该表 `occurred_at NOT NULL`）；C3 入库时按 `skipped_invalid` 计入报告。
  - 影响面：C3 的 `IngestReportDTO` 增加 `skipped_invalid` 字段（届时属 ADDITIVE）。

### 2026-10-22 · C2 · ADDITIVE · FZ-2 缓冲区契约冻结 v1

- **对象**：`BatchDTO`、`BatchDetailDTO`、`ParseMetaDTO`、`ParseIssueDTO`、`PreviewDTO`、`MappingReq`、`MappingResultDTO`、`TemplateReq`/`TemplateDTO`、`PrecheckRowDTO`、`PrecheckResultDTO`、`OverrideDTO`、7 个批次状态字面量、15 个 `/api/v1/staging/*` 端点
- **冻结内容**：
  - `BatchDTO{id, file_name, file_size, channel, status, total_rows, new_count, dup_count, pending_count, encoding, adapter, fail_reason, created_at, updated_at}`
  - `BatchDetailDTO = BatchDTO + {header_row_no, mapped_fields: MappingReq, mapping_snapshot: dict, parse_meta: ParseMetaDTO, file_exists}`
  - `MappingReq` 的 9 个列字段（`-1`/`null` = 未映射）+ `direction_map` + `amount_scale` + 3 个可选模板开关（`save_template` / `template_name` / `template_policy`）
  - `amount_scale` 语义：**`1` = 原始列为元（默认），`100` = 原始列为分**；其他值 → `E1008`
  - `PrecheckRowDTO.label ∈ {new, dup, pending_manual}`；`PrecheckResultDTO.summary` 恒含 `total/new/dup/pending_manual` 四键（缺失也返回 0）
  - 批次状态机：`failed --map--> mapped_pending` 合法（EX-03 手动映射）；`mapped_pending --parse-->` 一律 `E2002`；`ingest`/`confirm` 在 C2 全域非法
- **新增（不影响既有字段）**：`ParseResultDTO`/`ParseInfoDTO`、`PreviewRowDTO`、`OrphanFileDTO`、`BufferUsageDTO`、`EnsureDirDTO`、`DiscardReq`、`RemovedDTO`
- **未加入**：`BatchDetailDTO.report` —— 留给 C3 的 `IngestReportDTO` 以新增可选字段加入（现在占位会导致 C3 改类型 = BREAKING）
- **影响面**：C3 入库/重放、C4 重算、前端导入向导（1 个上传 + 1 个列表 + 13 个动作端点）
- **回归用例**：`tests/unit/test_batch_state_machine.py`（7×6 全矩阵）、`tests/integration/test_staging_{upload,mapping,precheck,buffer}.py`、`tests/integration/test_real_samples.py`
- **实施备注**：错误码仍只有 `api/errors.py` 一处枚举；infra 抛 `InfraError`（字符串码），由 `services/error_mapping.py` 翻译，分层门禁未放宽到整层

### 2026-10-22 · C2 · INTERNAL · 分层门禁与半成品后缀口径统一

- **对象**：`tests/integration/test_layering.py`、`infra/buffer_file.PARTIAL_SUFFIXES`
- **变更前**：`services` 一律禁止 import `api`；`health` / `reconciliation` / `staging/orphans` 各自 `endswith(".tmp")`
- **变更后**：`services` 允许 import `api.errors` / `api.response`（SDD §4.3 要求业务层抛 `AppError` 族），仍禁 `api.routers`/`deps`/`app_factory`；三处半成品判断共用 `PARTIAL_SUFFIXES = (".part", ".tmp")`
- **原因**：C2 的 15 个端点全部在业务层判定业务规则并抛错误族；若禁止 import `api.errors`，只能在 services 复制一套异常，错误码必然漂移。半成品后缀若不统一，上传中断留下的 `.part` 会被孤儿扫描误报
- **影响面**：无 API 变化；`/health.backlog.orphans` 与 `/staging/orphans` 口径一致
- **回归**：`test_layer_import_rules`、`test_orphans_listed_and_partials_ignored`

### 2026-10-23 · C2 · INTERNAL · A/B 双线合稿（以解析内核线 `main-e07d61db` 为主）

- **对象**：15 个 `/api/v1/staging/*` 端点、错误码体系、阈值常量、测试夹具
- **变更前**：C2 曾并行存在两套实现 —— A 线（解析内核：真实适配器 + 689/669 真实样例）与 B 线（缓冲区与向导：`FakeParser` 驱动的 15 端点）。二者在 `infra/parsers/*`、`models/{internal,staging}`、`repositories/*`、`services/*` 上正面冲突
- **变更后（合稿定案）**：
  - **代码取 A 线**：解析内核、仓储、编排、状态机（`services/batch_guard.py`）全部用 A 线版本。B 线的 `api/guards.py`（状态机门面）与 `tests/fakes/fake_parser.py` 因契约不兼容且零引用，删除
  - **错误码保留 B 线的中性化**：`ErrorCode` / `AppError` 族仍在包根 `account_dashboard/errors.py`，`api/errors.py` 只做处理器 + re-export；A 线的 `infra/errors.py`（`InfraError` 字符串码）由 `services/error_mapping.py` 翻译。**两条机制不冲突**：infra 不 import api，services 经白名单 import `api.errors`，分层门禁全绿
  - **阈值单一来源**：删除 `account_dashboard/limits.py`。`MAX_FILE_BYTES` / `MIN_DISK_FREE_BYTES` / `CHUNK_SIZE` 归 `infra/buffer_file.py`，`MAX_ROWS` 归 `infra/parsers/base.py`，`PAGE_SIZE_RANGE` 归 `api/validators.py`，`FP_QUERY_CHUNK` 归使用点 `repositories/transaction_repo.py`。避免"接口说 5MB、落盘说 6MB"的边界漂移
  - **夹具改用真实样例**：B 线的 `tests/integration/conftest.py`（`StagingFlow`）删除，统一用 A 线的 `tests/conftest.py`（`client` / `upload` / `fixtures_dir`）
- **补测（B 线独有、A 线未覆盖，已移植为 `tests/integration/test_staging_contract.py`）**：
  - 15 端点清单精确匹配 + C3 端点（`confirm` / `report` / `orphans/cleanup`）缺席断言
  - 三段式信封形状（成功 `code="OK"` / 失败 `E2001`）
  - 分页边界矩阵：`page_size ∈ {9, 201}`、`page ∈ {0, -3}` → `E1010`；越界页返回空列表而非报错；枚举参数走 `E1008`
  - 删除失败（`E4003`）端点级行为：批次**照常置 `discarded`**，失败路径写入 `cleanup_queue`（C3 重试），不回滚状态
- **原因**：双线并行导致同一契约两份实现，合稿是唯一出路；以 A 线为主是因为它已含真实样例回归（689/669），B 线只有假解析器
- **影响面**：无 API 变化；FZ-2 冻结的 DTO 与 15 端点路径一字未动
- **回归**：291 条收集 / 289 passed / 2 skipped；`ruff check src tests` 全过；`mypy src` 无问题

### 2026-10-22 · C1 · ADDITIVE · FZ-1 基座契约冻结 v1

- **对象**：`ApiResponse[T]{code,data,message}`、`PageMeta{page,page_size,total,total_pages}`、`Page[T]{items,meta}`、`ErrorCode`（37 值）、启动退出码 1~5、`GET /api/v1/health`
- **冻结内容**：
  - 成功响应 `code` 恒为 `"OK"`；失败响应 `code` 为 `ErrorCode` 的**值**（如 `E1001`），HTTP 状态按 SDD §6.5 映射
  - `HealthDTO{status,version,data_dir,db_ok,backlog{cleanup,orphans}}`；`status` 为 `ok|degraded`
  - 别名 `GET /health`（启动探测用，不进 OpenAPI）
  - 框架层 404/405 也返回三段式（`code=E1008` / `E5001`），前端只需一套解析
- **影响面**：C2~C5 全部端点；前端错误处理
- **回归用例**：`tests/integration/test_errors.py`（含错误码基数 37 与分组 11/11/5/7/3）、`tests/integration/test_health.py`、`tests/integration/test_startup.py`（退出码 1~5）
- **实施备注**：`api` 层不直接依赖 `repositories`，探活逻辑下沉到 `services/health_service.py`；分层由 `test_layering.py` 静态强制

### 2026-10-22 · 初始化 · INTERNAL · 全套契约

- **对象**：C1~C5 计划文档定义的初始契约集
- **说明**：本文件随《后端开发周期总览 v1.0》建立，尚无实际代码变更；基线为 SDD §6 的端点清单与 DTO 定义。
- **影响面**：无（尚未实现）
- **回归用例**：无

---

## 4. 登记模板（复制使用）

```markdown
### YYYY-MM-DD · C{N} · {BREAKING|ADDITIVE|INTERNAL} · {对象名}

- **对象**：`IngestReportDTO.skipped_dup`（示例）
- **变更前**：`int`，语义为"因指纹重复跳过的行数"
- **变更后**：`int`，语义改为"因指纹重复**或**状态冲突跳过的行数"
- **原因**：联调发现全量重复时状态冲突未计入，报告与预检差 1
- **影响面**：前端报告页文案；`test_ingest_all_dup.py`
- **回归**：`I-IN-02`、`test_stats_consistency.py`、联调验收项 #15
- **批准**：{评审人}
```

---

## 5. 已知的"不许改"清单

以下项一旦冻结，改动成本远高于收益，明确列为**禁止变更**（要改只能发大版本）：

| 项 | 原因 |
|----|------|
| 金额单位（整数分） | 全库、全 API、全前端都按分；改一次等于重写 |
| 时间格式（ISO 本地时间，无时区） | I5；改则历史数据需全量迁移 |
| `direction` 三值（income/expense/neutral） | I1；统计唯一准绳 |
| `status` 四值（pending/confirmed/corrected/excluded） | I2/I3；口径与重算语义绑定 |
| 批次状态 7 值（含字面量） | §5.6 状态机；改则历史批次无法解释 |
| `raw_YYYY_MM` 物理分表 | ADR-03；改为单表需全量数据迁移 |
| `pending_delete_flag` 语义 | I9；误用会导致误删用户文件 |
| `base_filter` 三条条件 | 口径唯一性；少一条即统计错误 |
