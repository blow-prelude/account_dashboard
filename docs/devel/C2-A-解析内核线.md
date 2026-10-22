# C2-A · 解析内核线（parsers）

> 定位：把「任意渠道导出的账单文件」变成「标准 `ParsedRow` 流」。
> **纯计算，零数据库、零 HTTP、零业务判断** —— 这条线不需要知道 `staging_batch` 长什么样，也不需要知道批次状态机。
> 人日：**3.0** ｜ 并行：与 B 线零文件交集 ｜ 出口：微信 689 / 支付宝 669 全解析
> 验收基线（不改口径）：[`C2-解析内核与导入缓冲区.md`](./C2-解析内核与导入缓冲区.md)

---

## 1. 边界

### 1.1 本线做（In Scope）

| 能力 | 落点 |
|------|------|
| 解析协议与注册表 | `infra/parsers/base.py`、`registry.py` |
| 解析异常族 | `infra/parsers/errors.py` |
| 标准内部模型 | `models/internal.py`（`ParsedRow` / `ParseIssue` / `ParseMeta` / `ParseResult` / `MappingSpec`） |
| 编码探测 | `infra/parsers/encoding.py` |
| 表头探测 | `infra/parsers/header_detect.py` |
| 字段清洗（金额/时间/方向/文本） | `infra/parsers/cleaning.py` |
| 去重指纹 | `infra/parsers/fingerprint.py` |
| 三个适配器 | `wechat_xlsx.py`、`alipay_csv.py`、`generic.py` |
| 样例夹具生成器 | `scripts/make_fixtures.py` + `tests/fixtures/*` |

### 1.2 本线不做（Out of Scope）

- **不建库、不写 `staging_batch`、不碰 SQL**（`tests/integration/test_layering.py` 会拦 `infra → repositories`）。
- 不解析 HTTP 请求、不返回 DTO、不定义 `ErrorCode`。
- 不判断「新/重复/待人工」—— 那是 B 线的预检。
- 不决定「哪一行能入库」—— 本线只标记 `issues`，归宿由 C3 定。

> **可验证的独立性**：本线全部代码只依赖 `pathlib` / `csv` / `openpyxl` / `chardet` / `hashlib` / `pydantic`，加上 `account_dashboard.errors`（中性模块）。删掉 `repositories/` 与 `api/` 整个目录，本线的测试仍应全绿。

---

## 2. D0 契约（两条线共同前置，先于并行开发）

这 5 个文件由 A 线主笔、B 线评审签字，**必须先于任何实现提交**。字段名一经签字即为 FZ-2 的一部分。

### 2.1 `models/internal.py`

```python
from typing import Any, Literal
from pydantic import BaseModel, Field

Direction = Literal["income", "expense", "neutral"]
Channel = Literal["wechat", "alipay", "bank", "other"]
IssueCode = Literal["AMOUNT_PARSE", "TIME_PARSE", "DIRECTION_UNKNOWN", "EMPTY_ROW"]


class ParseIssue(BaseModel):
    """行级问题：不阻断批次，只让该行进入待确认（EX-06/07/21）。"""
    code: IssueCode
    row_no: int                      # 1-based，与 raw.row_no 一致
    field: str | None = None         # "amount" / "occurred_at" / "direction"
    raw: str | None = None           # 原始值（截断 64 字符）


class ParsedRow(BaseModel):
    row_no: int                      # 1-based，数据行序号（不含前言与表头）
    occurred_at: str | None          # ISO 本地时间；解析失败为 None
    amount_cents: int | None         # 整数分；解析失败为 None
    direction: Direction             # 无法判定时为 neutral + issue
    counterparty: str | None
    item: str | None
    txn_type: str | None
    payment_method: str | None
    platform_category: str | None
    platform_status: str | None
    channel: Channel
    fp: str | None                   # 缺时间或金额时为 None（EX-21）
    raw_payload: dict[str, Any]      # 整行原貌：{表头名: 原始值}

    @property
    def is_valid(self) -> bool:
        return self.occurred_at is not None and self.amount_cents is not None


class ParseMeta(BaseModel):
    sheet: str | None = None
    delimiter: str | None = None
    preamble_rows: int = 0
    header_row_no: int = 0           # 0-based
    empty_rows_skipped: int = 0      # 数据区整行空行，必须可见、不得静默丢弃
    issues: dict[str, int] = Field(default_factory=dict)   # {"TIME_PARSE": 1}


class ParseResult(BaseModel):
    rows: list[ParsedRow]
    header_row_no: int
    encoding: str                    # "xlsx" / "gb18030" / "utf-8"
    adapter: str                     # "wechat_xlsx" / "alipay_csv" / "generic"
    columns: int                     # 识别出的列数（含尾随空列）
    meta: ParseMeta
```

> `rows` 包含 `is_valid=False` 的行 —— 不能在本线过滤掉，否则 B 线的「待人工核对」计数与报告四数字会对不上。

### 2.2 `infra/parsers/errors.py`

**不带 `ErrorCode`**：`infra` 不得 import `api`，HTTP 语义属于 B 线。

```python
class ParseError(Exception):
    """解析失败的基类；message 面向使用者，中文可执行。"""

class EncodingDetectFailed(ParseError): ...   # → E1002 / 422
class HeaderNotRecognized(ParseError): ...     # → E1003 / 422
class EmptyDocument(ParseError): ...           # → E1004 / 422
class RowLimitExceeded(ParseError): ...        # → E1006 / 422
```

### 2.3 `infra/parsers/base.py`

```python
class ParserAdapter(Protocol):
    name: str            # "wechat_xlsx"
    channel: Channel

    def sniff(self, path: Path) -> bool:
        """只看扩展名/魔数/前几行，不做完整解析。"""

    def parse(self, path: Path, spec: MappingSpec | None = None) -> ParseResult:
        """spec=None → 自动探测表头 + 默认列映射；
        spec 非空 → 按给定列索引解析（C3 重放 / C4 重算依赖这条路径）。"""
```

### 2.4 `MappingSpec`（在 `models/internal.py`）

```python
class MappingSpec(BaseModel):
    occurred_at: int
    amount: int
    direction: int
    counterparty: int | None = None
    item: int | None = None
    txn_type: int | None = None
    payment_method: int | None = None
    platform_category: int | None = None
    platform_status: int | None = None
    direction_map: dict[str, Direction] = {}
    amount_scale: int = 1            # 1=账单单位是「元」(内部×100)；100=已是「分」(不再×100)
```

**`amount_scale` 语义在此定死**（SDD 未展开，两条线必须一致）：它表示「原始数值 → 分」的倍率。
`1` 走常规路径（`Decimal(v) * 100`），`100` 表示文件本身以分为单位（`Decimal(v)` 直接取整）。
只允许 `{1, 100}`，其他值在 B 线的入口校验里报 `E1008`。

### 2.5 `infra/parsers/registry.py`

```python
class ParserRegistry:
    def __init__(self, adapters: Sequence[ParserAdapter] | None = None) -> None
    def register(self, adapter: ParserAdapter) -> None
    def resolve(self, file_name: str, channel_hint: Channel | None = None) -> ParserAdapter
    def get(self, name: str) -> ParserAdapter      # B 线重放时按名字取回同一适配器
```

`resolve` 规则：`channel_hint` 命中 → 用它；否则按扩展名 + `sniff` 顺序匹配；都不中 → `generic`。

---

## 3. 任务分解

| ID | 任务 | 产出文件 | 依赖 | 人日 | 验收断言 |
|----|------|----------|------|------|----------|
| C2A.1 | 协议、异常、内部模型、注册表 | `models/internal.py`、`infra/parsers/{base,errors,registry}.py` | D0 | 0.4 | `ParserRegistry().resolve("x.xlsx")` 命中 wechat；`resolve("unknown.csv")` 落 generic；异常族可按类型捕获 |
| C2A.2 | 编码探测 | `infra/parsers/encoding.py` | C2A.1 | 0.2 | 支付宝样例 → `gb18030` 且中文无乱码；UTF-8 版结果一致；坏字节 → `EncodingDetectFailed` |
| C2A.3 | 表头探测 | `infra/parsers/header_detect.py` | C2A.1 | 0.35 | 微信 `header_row_no=17`(0-based)、支付宝 `23`；前言 +5 行仍可定位；无表头 → `HeaderNotRecognized` |
| C2A.4 | 字段清洗 | `infra/parsers/cleaning.py` | C2A.1 | 0.35 | `8.8→880`、`4.35→435`、`"45.90"→4590`、`"¥1,234.5"→123450`；`46316.82503472222→2026-10-21T19:48:03`；8 种时间格式全过 |
| C2A.5 | 指纹 | `infra/parsers/fingerprint.py` | C2A.4 | 0.2 | 五要素全同 → 同指纹；缺时间/金额 → `None`；两份样例文件内碰撞 **0** |
| C2A.6 | 微信适配器 | `infra/parsers/wechat_xlsx.py` | C2A.2~5 | 0.55 | **689** 行；方向 613/72/4；月份 172/114/153/142/108；11 列；`empty_rows_skipped=0` |
| C2A.7 | 支付宝适配器 | `infra/parsers/alipay_csv.py` | C2A.2~5 | 0.45 | **669** 行；方向 512/155/2；月份 101/136/182/143/107；13 列（末列空）；Tab 全清除 |
| C2A.8 | 通用适配器 + 夹具生成器 | `infra/parsers/generic.py`、`scripts/make_fixtures.py` | C2A.6、C2A.7 | 0.5 | generic 在无模板时靠表头探测 + 手动列映射跑通；生成器产出可入库的脱敏夹具（60 行），结构特征不丢 |

**合计 3.0 人日。**

---

## 4. 关键实现要点

### 4.1 `RowSource` 抽象：表头探测不能只认一种数据源

xlsx 与 csv 的行迭代形态不同（`openpyxl` 给 `tuple`，`csv.reader` 给 `list`），但表头打分必须共用一套逻辑：

```python
class RowSource(Protocol):
    columns: int
    def rows(self, limit: int) -> Iterator[tuple[int, list[Any]]]:
        """(row_no_0_based, values)；必须按行号补齐空行，不能跳过。"""
```

**微信第 6、16 行在 XML 里整行缺失**，`openpyxl` 按行号补齐后共 707 行。若你的 `rows()` 用 `enumerate(ws.values)` 直接数，行号会偏移 2，`header_row_no` 就变成 15 —— 这是本线最容易犯的错。正确做法：以 `ws.max_row` 为界、按 1..max_row 取，缺失行返回空 tuple。

### 4.2 表头打分：分母固定 15

```python
CORE = ("occurred_at", "amount", "direction", "counterparty", "item")
SECONDARY = ("txn_type", "payment_method", "platform_category", "platform_status", "note")

score = (命中核心 × 2 + 命中次要 × 1) / 15     # 固定分母
# 过滤：matched_core < 5 直接丢弃
# 排序：score 降序 → 命中多者优先 → 行号小者优先
```

两个反直觉点：

- 用「命中/该行非空列数」会让「只有 5 列且全中」拿满分，与「11 列全中」并列 → 误选。
- 前言里常有「交易时间：2026-06-01」这类文本，可能虚构命中 1~2 个字段 → 要求 5 核心全中可排除。

`normalize_header_cell`：`NFKC`（全角→半角）→ 去 BOM/零宽/Tab/换行 → 折叠空白 → 去尾部冒号 → `lower()`。支付宝末列是空字符串，**保留列索引 12 但不映射**。

### 4.3 金额：唯一允许 `×100` 的地方

```python
def parse_amount_to_cents(v: Any, *, scale: int = 1) -> int:
    # None / "" / "/" → AmountParseError
    # int/float/Decimal → Decimal(str(v))       ← 禁止 float 直接乘
    # str → 去 ¥￥,，空格 Tab 「元」 → Decimal
    # 负数取绝对值（方向由 direction 承载）
    # quantize(Decimal("0.01"), ROUND_HALF_UP)
    # scale == 100（已是分）→ int(d)；否则 int(d * 100)
    # 超过 3 位小数或 > 1e9 分 → AmountParseError
```

写这条规则的原因很具体：`8.8 * 100 == 880.0000000000001`，`int()` 之后是 **879**。一分钱的差错会一路传到统计页。

### 4.4 时间：四条分支，一个基准

| 输入类型 | 处理 |
|----------|------|
| `datetime` | 直接用，微秒截断 |
| `float` / `int` | Excel 序列号：`datetime(1899,12,30) + timedelta(days=serial)` |
| `str` | 依次尝试 `%Y-%m-%d %H:%M:%S`、`%Y/%m/%d %H:%M:%S`、`%Y-%m-%d %H:%M`、`%Y-%m-%d`、`%Y%m%d%H%M%S`、ISO、`%Y年%m月%d日`、带时区后缀（**丢弃时区，不换算**） |
| `None`/其他 | `TimeParseError` |

基准用 `1899-12-30` 而不是 `1899-12-31`，是为了吃掉 Excel 的 1900 闰年 bug。验收值：`46316.82503472222 → 2026-10-21T19:48:03`，必须与 `datetime` 分支**逐秒一致**。

### 4.5 方向映射（渠道级硬编码，可被模板覆盖）

| 渠道 | 原文 | direction |
|------|------|-----------|
| 微信 | `支出` | expense |
| 微信 | `收入` | income |
| 微信 | `/`（687/689 备注为空） | neutral |
| 支付宝 | `支出` | expense |
| 支付宝 | `收入` | income |
| 支付宝 | `不计收支` | neutral |
| 任意 | 未知值 | neutral + `DIRECTION_UNKNOWN` issue |

`MappingSpec.direction_map` 非空时优先用它（用户在映射页自定义）。

### 4.6 指纹：五要素，缺一即 `None`

`sha256(channel | occurred_at | amount_cents | direction | normalized_counterparty)[:32]`

- `counterparty` 归一：去 `(*)` 掩码 → 去空白 → `lower()`；`None` 与 `""` 等价。
- 时间或金额为 `None` → `fp=None`，该行之后由 B 线标 `pending_manual`（EX-21）。
- 实测：两份样例文件内碰撞均为 **0**，不需要碰撞消解逻辑。

### 4.7 适配器实现细节

**微信 xlsx**

```python
wb = load_workbook(path, read_only=True, data_only=True)
ws = wb["Sheet1"] if "Sheet1" in wb.sheetnames else wb.worksheets[0]
# 时间单元格可能是 datetime 或 float —— 两种都要过 parse_time_to_iso
# 金额是数值（int 461 行 / float 228 行），必须 Decimal(str(v))
# 数据行 = max_row - header_row(1-based) = 707 - 18 = 689
```

**支付宝 csv**

```python
text, encoding = detect_and_decode(path.read_bytes())     # → gb18030
rows = list(csv.reader(io.StringIO(text)))                # 13 列，末列为 ""
# 669/669 行尾部有 Tab：clean_text 必须清掉 \t\r\n\u00a0\u3000
# 数据行 = 693 - 23(前言) - 1(表头) = 669
```

**通用 generic**：无内置列序，只能靠表头探测 + `MappingSpec`；`spec` 为空且五核心不齐 → 抛 `HeaderNotRecognized`，由 B 线引导用户手动映射。

### 4.8 `raw_payload` 的形状

```python
raw_payload = {header_names[i]: raw_values[i] for i in range(columns) if header_names[i]}
```

保留**原始值**（字符串/数值原样），不做单位换算；换算结果只体现在 `amount_cents`。这份 payload 会原样进 `raw_YYYY_MM.raw_payload`，是审计链的终点（I7）。

---

## 5. 对外契约（B 线唯一依赖面）

| 契约 | 签名 | B 线用途 |
|------|------|----------|
| `ParserRegistry.resolve(file_name, channel_hint)` | `-> ParserAdapter` | 上传时选适配器 |
| `ParserAdapter.parse(path, spec=None)` | `-> ParseResult` | 解析 / 重解析 / C3 重放 |
| `ParserAdapter.name` | `str` | 写入 `staging_batch.adapter` |
| `ParseResult.header_row_no` | `int`（0-based） | 写入 `staging_batch.header_row_no` |
| `ParseResult.encoding` | `str` | 写入 `staging_batch.encoding` |
| `ParseResult.meta.empty_rows_skipped` | `int` | 报告页「已跳过空行 N 行」 |
| `ParseResult.meta.issues` | `dict[str,int]` | 批次详情 `parse_meta.issues` |
| `ParsedRow.is_valid` | `bool` | 预检标 `pending_manual` |
| `ParseError` 四个子类 | 异常 | B 线映射为 `E1002/E1003/E1004/E1006` |

**反向约束**：B 线不得 import `infra.parsers` 的具体适配器类（`wechat_xlsx` 等），只能用 `registry` + `base`。否则 C3 加新渠道时 B 线要跟着改。

---

## 6. 测试与验收

### 6.1 夹具（本线负责生成）

| 夹具 | 行数 | 必须保留的特征 |
|------|------|----------------|
| `wechat_sample_sanitized.xlsx` | 60 数据行 | 前言 17 行、表头第 18 行、序列号时间、`8.8` 这类 float 金额、`/` 方向 |
| `alipay_sample_gb18030.csv` | 60 数据行 | GB18030、13 列尾随空列、Tab 尾随、`不计收支` |
| `wechat_serial_float.xlsx` | 3 | 时间无日期样式 → `openpyxl` 返回 `float` |
| `wechat_header_shifted.xlsx` | 3 | 前言 +5 行（表头落到第 23 行） |
| `alipay_utf8.csv` | 3 | 同内容 UTF-8 版 |
| `no_header.csv` | 5 | 无表头 |
| `broken_structure.csv` | 0 | 只有前言 |
| 全量样例（689/669） | — | 放 `tests/fixtures/local/`，**不进 git** |

`scripts/make_fixtures.py` 必须**确定性输出**（同样输入 → 同样字节），且脱敏只改人名/账号，不改结构。生成器要打印每份夹具的行数与方向分布，作为检查证据。

### 6.2 必写用例

| 用例 | 断言 |
|------|------|
| U-HD-01/02 | 微信 `header_row_no==17`、支付宝 `==23`（0-based），五核心全中 |
| U-HD-03 | `no_header.csv` → `HeaderNotRecognized`；`allow_partial` 返回最佳候选 |
| U-HD-04 | `wechat_header_shifted.xlsx` 仍定位到第 22 行（0-based） |
| U-EN-01/02 | GB18030 无乱码；UTF-8 版结果逐字段相同；坏字节 → `EncodingDetectFailed` |
| U-AM-01/02 | 四个金额样例；`"/"`/`"abc"` → `AmountParseError`，行保留 + issue |
| U-TM-01/02 | 序列号 → `2026-10-21T19:48:03`；8 种格式全过；微秒截断 |
| U-FP-01/02 | 同五要素同指纹；改任一字段不同；缺时间/金额 → `None` |
| U-DM-01 | 微信 `/`、支付宝 `不计收支` → neutral；未知值 → neutral + issue |
| `test_adapter_wechat.py` | 全量 689、方向分布、月分布、列数、`empty_rows_skipped` |
| `test_adapter_alipay.py` | 全量 669、方向分布、月分布、13 列、Tab 已清 |
| `test_replay_with_spec.py` | 同一 `MappingSpec` 解析两次 → `ParsedRow` 列表逐字段相同（C3/C4 的地基） |

### 6.3 出口检查表

- [ ] 微信 689 / 支付宝 669，行数逐项相等（不是"约等于"）
- [ ] 方向分布：613/72/4 与 512/155/2
- [ ] 月分布：172/114/153/142/108 与 101/136/182/143/107
- [ ] `header_row_no`：17 / 23（0-based）
- [ ] `8.8→880`、`46316.82503472222→2026-10-21T19:48:03`
- [ ] 指纹文件内碰撞 0；缺字段 → `None`
- [ ] `parse(spec=...)` 两次结果完全一致
- [ ] 全量 669 行解析 < 300ms（`time.perf_counter` 断言）
- [ ] `tests/unit/` 下无任何 `sqlite3` / `repositories` / `api` import
- [ ] 打 tag `c2a-done`

---

## 7. 风险与回退

| 风险 | 表现 | 处理 |
|------|------|------|
| 表头打分为 0 | 换了导出版本 | **不改适配器绕过**，只补 `ALIASES` 别名或调 `max_scan`（≤60），并新增该版本的夹具 |
| 行号偏移 2 | 用 `enumerate(ws.values)` 迭代 | 改 `RowSource.rows()` 按 `max_row` 补齐；`header_row_no` 断言会立刻抓到 |
| 金额差 1 分 | `float * 100` | 全库搜索 `* 100`，只允许出现在 `parse_amount_to_cents` 且输入是 `Decimal` |
| GB18030 误判 UTF-8 | 严格解码"成功"但乱码 | utf-8 严格解码后再验：无 `\ufffd` 且中文占比合理，否则继续 gb18030 |
| 时区被换算 | 差 8 小时 | 明确不做 UTC 转换（I5）；带时区字符串只丢弃后缀 |
| 别名污染 | `"时间"` 命中前言文本 | 5 核心全中的硬要求 + 同分取最小行号 |

**回退**：本线是纯函数，回退成本极低。但 `models/internal.py` 与 `base.py` 一旦签字就是 B 线的编译期依赖，改字段等于让 B 线返工 —— 因此 D0 评审必须一次到位。

---

## 8. 交接物

给 B 线与 C3：

1. 已签字的 `models/internal.py`、`base.py`、`errors.py`、`registry.py`；
2. `ParserRegistry` 默认注册好三个适配器（`registry.default_registry()`）；
3. `scripts/make_fixtures.py` 可复现生成 6 份夹具；
4. 一份 `docs/devel/parsers-calibration.md`（可选，若样例有新增版本）：记录每个渠道的表头行、列序、方向取值、坑。
