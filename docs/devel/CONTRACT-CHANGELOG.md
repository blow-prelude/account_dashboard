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
| FZ-2 | C2 收口 | `BatchDTO`、`BatchDetailDTO`、`ParseMetaDTO`、`MappingReq`、`PrecheckResultDTO`、7 个批次状态 | 待冻结 |
| FZ-3 | C3 收口 | `IngestReportDTO`、`RawRecordDTO`、`raw_YYYY_MM` 列定义、`pending_delete_flag`、7×6 状态矩阵 | 待冻结 |
| FZ-4 | C4 收口 | 12 指标 DTO、`base_filter` 语义、`period/anchor` 格式、`null` 语义、三入口同源 | 待冻结 |

> 「待冻结」在对应周期出口检查表通过后改为「已冻结 v1」，并在此追加条目。

---

## 3. 变更流水

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
