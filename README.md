# 个人财务分析仪表盘

本地单用户、单账本的财务分析工具。后端 Python 3.11 + FastAPI + SQLite，数据全部留在本机
`data/` 目录，不上传、不外联。

> 当前进度：**C2 解析与缓冲区已完成**（真实账单 689/669 行全解析，上传→解析→映射→预检链路打通；
> 库内 `transaction` 仍为 0 行 —— 入库属 C3）。
> 详细计划见 [`docs/devel/README.md`](docs/devel/README.md)，设计依据见
> [`docs/个人财务分析仪表盘-软件设计文档-v1.0.md`](docs/个人财务分析仪表盘-软件设计文档-v1.0.md)。

---

## 五条命令上手

```bash
# 1. 安装 uv（已安装可跳过）
#    Windows: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
#    macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 同步依赖（自动创建 .venv，自动使用 Python 3.11）
uv sync

# 3. 准备配置（可跳过，跳过则使用系统用户数据目录）
cp app.toml.example app.toml

# 4. 建库 / 升级 schema（可重复执行）
uv run account-dashboard init-db

# 5. 启动
uv run account-dashboard run
```

启动后访问 <http://127.0.0.1:8765/api/v1/health>，应返回：

```json
{"code":"OK","data":{"status":"ok","version":"0.1.0","data_dir":"...","db_ok":true,"backlog":{"cleanup":0,"orphans":0}},"message":""}
```

后端**只绑定 127.0.0.1**，不提供对外监听开关。

---

## 命令

| 命令 | 说明 |
|------|------|
| `uv run account-dashboard run` | 启动服务（配置见 `app.toml`） |
| `uv run account-dashboard init-db` | 建库/升级 schema，幂等 |
| `uv run account-dashboard export-openapi` | 导出 `docs/api/openapi.json` |
| `uv run account-dashboard --version` | 版本 |
| `uv run pytest` | 全部测试 |
| `uv run ruff check src tests` | 静态检查 |
| `uv run mypy src` | 类型检查 |
| `uv run python -m account_dashboard.infra.parsers.check <账单>` | 解析器自检（行数/表头/编码/方向/月份分布） |

---

## 数据目录

默认位置（`data_dir` 留空时）：

- Windows：`%LOCALAPPDATA%\AccountDashboard`
- macOS/Linux：`~/.local/share/account-dashboard`

目录结构：

```
data/
├─ db/ledger.db      # SQLite（WAL）
├─ buffer/           # 上传缓冲区（导入后删除源文件）
├─ backups/          # 备份
└─ logs/app.log      # 应用日志（10MB × 5 轮转）
```

`data/`、`app.toml`、`instance.lock` 均在 `.gitignore` 中，不会入库。

---

## 退出码（启动失败时的可读信号）

| 码 | 含义 | 用户该做什么 |
|----|------|--------------|
| 1 | 配置文件格式错误 | 按提示的行号修正 `app.toml` |
| 2 | 数据目录不可用 | 换一个普通本地文件夹 |
| 3 | 无法创建目录 | 检查权限 |
| 4 | 数据库升级失败 | 从 `data/backups` 恢复 |
| 5 | 端口被占用 / 已有实例 | 改 `port`，或关闭已运行的实例 |

---

## 目录结构

```
src/account_dashboard/
├─ api/           # 接口层：路由（health / staging）、统一响应、错误处理、静态挂载
├─ services/      # 业务层：导入编排、映射、去重预检、状态机
├─ repositories/  # 数据层：连接、UoW、迁移、批次/模板/强制新增仓储
├─ infra/         # 基础设施：路径、日志、文件锁、对账、缓冲区、解析器（parsers/）
├─ models/        # DTO（staging / internal / enums）
└─ migrations/    # V001__init.sql（12 张表）
tests/            # unit / integration
```

分层规则由 `tests/integration/test_layering.py` 静态强制：
`api → services → repositories → infra`，接口层不得直接触达仓储或 `sqlite3`。
