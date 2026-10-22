# AGENTS.md


## 项目概览

个人财务分析仪表盘：本地单用户、单账本的财务分析工具。Python 3.11 + FastAPI + SQLite（标准库 sqlite3 + 显式事务），包管理用 uv。后端只绑定 127.0.0.1:8765，数据全部留在本机数据目录，禁止任何外传（最高优先级约束）。

## 常用命令

```bash
uv sync                                                       # 安装依赖（自动建 .venv）
uv run account-dashboard init-db                              # 建库/升级 schema（幂等）
uv run account-dashboard run                                  # 启动服务（配置 app.toml，模板见 app.toml.example）
uv run account-dashboard export-openapi                       # 导出 OpenAPI 契约
uv run pytest                                                 # 全部测试
uv run pytest tests/unit/test_fingerprint.py                  # 单文件
uv run pytest tests/unit/test_fingerprint.py::test_名称        # 单个用例
uv run ruff check src tests                                   # lint（line-length 100）
uv run mypy src                                               # 类型检查（disallow_untyped_defs）
uv run python -m account_dashboard.infra.parsers.check <账单>   # 解析器自检
node --experimental-default-type=module scripts/check-frontend.mjs  # 前端自检
```

## 架构分层（一层只负责一类功能）

`src/account_dashboard/` 后端四层，依赖方向严格单向：**api → services → repositories → infra**。

| 层            | 职责                                                                           | 禁止                           |
| ------------- | ------------------------------------------------------------------------------ | ------------------------------ |
| api/          | 路由、请求解析、入口校验、统一响应与错误码、静态挂载                           | 直连仓储或 sqlite3；含业务逻辑 |
| services/     | 全部领域逻辑：导入编排、批次状态机、映射、去重预检；事务边界在此               | 展示决策                       |
| repositories/ | 持久化与事务（UoW、迁移），唯一 SQL 出口                                       | 业务规则                       |
| infra/        | 缓冲区文件、解析器适配器（infra/parsers/）、编码探测、日志、路径守卫、启动对账 | 定义业务规则                   |

辅助：models/（Pydantic DTO）、migrations/（SQL）、config.py、errors.py。

分层由 `tests/integration/test_layering.py` 用 AST 静态强制，调整 import 前先读它的规则。已注册例外（新增例外须同步改该测试）：
- `api/deps.py` 是唯一装配点，可构造 UnitOfWork（FastAPI 依赖注入靠参数默认值实现，routers 里 B008 已豁免）；
- services/ 允许 import `api.errors` / `api.response`（视为契约模块，不在 services 复制一套异常）。

## 模块解耦：依赖接口，不做重复防御

- 层间只经定义良好的接口交互。契约单一事实源：Pydantic 模型 → OpenAPI（export-openapi）→ 前端 TS 类型；契约变更必登记（见下）。
- 信任边界以进程为界：前端输入一律不可信，入口校验（Pydantic + api/validators.py）一次性完成，失败即拒绝；后端内部模块信任已校验数据，不重复校验。
- 业务不变量（状态机守卫、幂等、唯一性）由业务层在操作入口强制一次（如 services/batch_guard.py）。
- 统计计算单一来源：stats_service（C4 建）是唯一口径实现；接口层与前端禁止自行聚合。收支口径以 direction 为唯一准绳，neutral 一律不计收支。

## 三条硬约束（出现第二处即为缺陷）

1. 金额一律整数分（int），禁止 `float * 100`；换算只在 `parse_amount_to_cents` 内用 Decimal。
2. `direction` / `status` 的统计过滤条件只允许写在 stats_service.py。
3. `transaction.status` 只能由 4 个写入点修改：分类引擎、transaction_service（修正）、exclude、recalc_service。

## 契约变更流程

DTO、端点签名、错误码、表结构、null 语义的任何变化 → 必须追加登记 `docs/devel/CONTRACT-CHANGELOG.md`（只追加、不改历史），按 BREAKING / ADDITIVE / INTERNAL 分级执行下游动作。冻结基线（FZ-1~FZ-4）内对象属 BREAKING，需评审。

## 大改动：git worktree 隔离

对现有框架变动较大时（改分层结构、改依赖方向、动冻结契约、换技术组件），**不在主工作区直接改**：
1. 在项目根 `.worktree/` 下建 worktree 实现，如 `git worktree add .worktree/<分支名> -b <分支名>`；
2. 主工作区保持可用；完成后向用户演示，**由用户决定是否合并回 main**，不得自行合并。

## 开发节奏与文档

- 按 `docs/devel/` 的 5 个周期开发（C1 基座 → C2 解析缓冲区 → C3 入库自愈 → C4 分类统计 → C5 管理联调），当前进度见其 README 进度看板（C1、C2 已完成）。
- 开工前读对应周期分册；任务表中的「验收断言」即 DoD，不要自行放宽；收工跑出口检查表。
- 需求与口径权威：`docs/个人财务分析仪表盘-PRD-v2.0.md`（§8.1 架构五原则、§9.2 批次状态机、§10.3 统计口径、§12 异常清单 EX-01~23）；设计细节见软件设计文档 v1.0。
- 前端是 src/account_dashboard/static/ 下的零构建原生 ES Modules SPA（无 npm、无 CDN），由后端挂载到 /，单进程单端口。
