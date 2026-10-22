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
