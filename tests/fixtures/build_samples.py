"""生成 C2 的回归样例（**结构 + 统计特征与真实账单一致**，内容已脱敏）。

真实账单不能入库，但解析器回归必须依赖真实结构，因此这里按 C2 §2 的校准事实
逐项复刻，并用断言把它们钉死 —— 生成器自己先验证一遍，避免"样例悄悄漂移"：

| 项 | 微信 xlsx | 支付宝 csv |
|----|-----------|-----------|
| 总行数（含前言） | 707（第 6、16 行在 XML 中缺失） | 693 |
| 表头（1-based） | 18 | 24 |
| 数据行 | 689 | 669 |
| 编码 | xlsx | GB18030 |
| 列数 | 11 | 13（末列空，行尾逗号） |
| 方向分布 | 613 / 72 / 4 | 512 / 155 / 2 |
| 月分布 | 172/114/153/142/108 | 101/136/182/143/107 |
| 同日同额不同对方 | 20 组 | 29 组 |

用法（生成到本目录）：``uv run python tests/fixtures/build_samples.py``
"""

from __future__ import annotations

import csv
import io
import random
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import Workbook

from account_dashboard.infra.parsers.fingerprint import build_fingerprint
from account_dashboard.models.enums import Direction

FIXTURES = Path(__file__).resolve().parent

WECHAT_MONTHS = {6: 172, 7: 114, 8: 153, 9: 142, 10: 108}
WECHAT_DIRECTIONS = {"expense": 613, "income": 72, "neutral": 4}
WECHAT_COLUMNS = [
    "交易时间",
    "交易类型",
    "交易对方",
    "商品",
    "收/支",
    "金额(元)",
    "支付方式",
    "当前状态",
    "交易单号",
    "商户单号",
    "备注",
]
WECHAT_RAW_DIRECTION = {"expense": "支出", "income": "收入", "neutral": "/"}

ALIPAY_MONTHS = {6: 101, 7: 136, 8: 182, 9: 143, 10: 107}
ALIPAY_DIRECTIONS = {"expense": 512, "neutral": 155, "income": 2}
ALIPAY_COLUMNS = [
    "交易时间",
    "交易分类",
    "交易对方",
    "对方账号",
    "商品说明",
    "收/支",
    "金额",
    "收/付款方式",
    "交易状态",
    "交易订单号",
    "商家订单号",
    "备注",
    "",
]
ALIPAY_RAW_DIRECTION = {"expense": "支出", "income": "收入", "neutral": "不计收支"}

COUNTERPARTIES = (
    "美团平台商户",
    "滴滴出行",
    "某某便利店",
    "中国移动",
    "盒马鲜生",
    "某某咖啡",
    "浪漫**店",
    "国家电网",
    "某某药房",
    "肯德基",
)
ITEMS = (
    "扫码支付",
    "外卖订单",
    "话费充值",
    "生鲜果蔬",
    "咖啡饮品",
    "打车费用",
    "水电缴费",
    "药品购买",
    "堂食消费",
)
WECHAT_TXN_TYPES = ("商户消费", "扫二维码付款", "转账", "零钱提现", "微信红包")
WECHAT_STATUS = ("支付成功", "已存入零钱", "已转账", "已收钱", "已全额退款")
ALIPAY_CATEGORIES = ("交通出行", "餐饮美食", "日用百货", "投资理财", "账户存取", "生活服务")
ALIPAY_STATUS = ("交易成功", "支付成功", "退款成功", "交易关闭")
ALIPAY_PAY_METHODS = ("余额宝", "花呗", "银行卡", "余额宝&红包")
EXCEL_EPOCH = datetime(1899, 12, 30)
WECHAT_ROWS = 689
# 真实样例里金额有 228 行是 float（如 8.8）、461 行是 int；此处按同样比例固定下来
FLOAT_AMOUNT_ROWS = frozenset(random.Random(7).sample(range(WECHAT_ROWS), 228))


def build_rows(
    months: dict[int, int],
    directions: dict[str, int],
    seed: int,
    duplicate_groups: int,
) -> list[dict[str, object]]:
    total = sum(months.values())
    labels = (
        ["expense"] * directions["expense"]
        + ["income"] * directions["income"]
        + ["neutral"] * directions.get("neutral", 0)
    )
    assert len(labels) == total, f"方向分布之和 {len(labels)} != 总行数 {total}"
    random.Random(seed).shuffle(labels)

    rows: list[dict[str, object]] = []
    cursor = 0
    for month in sorted(months):
        for index in range(months[month]):
            occurred = datetime(2026, month, 1, 8, 0, 0) + timedelta(minutes=11 * index + index % 7)
            cents = 100 + (index * 137) % 20000
            rows.append(
                {
                    "month": month,
                    "occurred": occurred,
                    "direction": labels[cursor],
                    "amount_cents": cents,
                    "counterparty": COUNTERPARTIES[(index + cursor) % len(COUNTERPARTIES)],
                    "item": ITEMS[(index * 3 + cursor) % len(ITEMS)],
                    "index": cursor,
                }
            )
            cursor += 1

    _apply_duplicate_groups(rows, duplicate_groups, seed)
    _assert_unique_fingerprints(rows)
    return rows


def _apply_duplicate_groups(rows: list[dict[str, object]], count: int, seed: int) -> None:
    """构造「同日同额不同对方」组合：时间/金额/方向/商品全同，只差交易对方。"""
    rnd = random.Random(seed + 1)
    used: set[int] = set()
    made = 0
    start = rnd.randrange(0, max(1, len(rows) // 3))
    for offset in range(len(rows)):
        if made >= count:
            break
        left_index = (start + offset) % len(rows)
        if left_index in used:
            continue
        left = rows[left_index]
        for right_index in range(left_index + 1, len(rows)):
            if right_index in used:
                continue
            right = rows[right_index]
            if (
                right["month"] == left["month"]
                and right["direction"] == left["direction"]
                and right["counterparty"] != left["counterparty"]
            ):
                right["occurred"] = left["occurred"]
                right["amount_cents"] = left["amount_cents"]
                right["item"] = left["item"]
                used.update({left_index, right_index})
                made += 1
                break
    assert made == count, f"同日同额组合只构造出 {made} 组，期望 {count} 组"


def _assert_unique_fingerprints(rows: list[dict[str, object]]) -> None:
    seen: set[str] = set()
    for row in rows:
        fingerprint = build_fingerprint(
            occurred_at=row["occurred"],  # type: ignore[arg-type]
            amount_cents=row["amount_cents"],  # type: ignore[arg-type]
            direction=Direction(str(row["direction"])),
            counterparty=str(row["counterparty"]),
            item=str(row["item"]),
        )
        assert fingerprint is not None
        assert fingerprint not in seen, "样例出现了指纹碰撞，跨文件去重会误判"
        seen.add(fingerprint)


# ── 微信 xlsx ───────────────────────────────────────────────
def write_wechat(path: Path, rows: list[dict[str, object]], *, shift: int = 0) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"

    preamble = [
        "微信支付账单明细",
        "微信昵称：[某某]",
        "起始时间：[2026-06-01 00:00:00] 终止时间：[2026-10-21 23:59:59]",
        "导出类型：[全部]",
        "导出时间：[2026-10-21 19:54:21]",
        None,  # 第 6 行：XML 中整行缺失
        "共689笔记录",
        "收入：72笔 共￥12000.00",
        "支出：613笔 共￥45000.00",
        "中性交易：4笔",
        "注：1. 充值/提现/转账/信用卡还款等不计入收支",
        "注：2. 本账单仅供个人对账使用",
        "----------------------微信支付账单明细列表--------------------",
        "以下为交易记录：",
        "序号,交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注",
        None,  # 第 16 行：XML 中整行缺失
        None,  # 第 17 行：空行（前言结束）
    ]
    header_row_no = 18 + shift
    for index, text in enumerate(preamble, start=1):
        actual = index + shift
        if text is not None:
            sheet.cell(row=actual, column=1, value=text)

    for column, title in enumerate(WECHAT_COLUMNS, start=1):
        sheet.cell(row=header_row_no, column=column, value=title)

    for offset, row in enumerate(rows):
        excel_row = header_row_no + 1 + offset
        occurred = row["occurred"]
        assert isinstance(occurred, datetime)
        cents = int(row["amount_cents"])  # type: ignore[arg-type]
        # 时间两种类型混排：float 序列号（无日期样式）与 datetime（带日期样式）
        use_float_time = offset % 3 == 0
        time_cell = sheet.cell(row=excel_row, column=1)
        if use_float_time:
            serial = (occurred - EXCEL_EPOCH).total_seconds() / 86400
            time_cell.value = serial
        else:
            time_cell.value = occurred
            time_cell.number_format = "yyyy-mm-dd hh:mm:ss"

        sheet.cell(row=excel_row, column=2, value=WECHAT_TXN_TYPES[offset % len(WECHAT_TXN_TYPES)])
        sheet.cell(row=excel_row, column=3, value=row["counterparty"])
        sheet.cell(row=excel_row, column=4, value=row["item"])
        sheet.cell(
            row=excel_row,
            column=5,
            value=WECHAT_RAW_DIRECTION[str(row["direction"])],
        )
        amount_cell = sheet.cell(row=excel_row, column=6)
        # 金额两种类型混排：461 行 int + 228 行 float（如 8.8）
        amount_cell.value = float(cents / 100) if offset in FLOAT_AMOUNT_ROWS else cents
        sheet.cell(row=excel_row, column=7, value="零钱" if offset % 5 else "/")
        sheet.cell(row=excel_row, column=8, value=WECHAT_STATUS[offset % len(WECHAT_STATUS)])
        sheet.cell(row=excel_row, column=9, value=f"42000{offset:012d}")
        sheet.cell(row=excel_row, column=10, value=f"10000{offset:012d}")
        sheet.cell(row=excel_row, column=11, value="/")

    workbook.save(path)


# ── 支付宝 csv ──────────────────────────────────────────────
def write_alipay(path: Path, rows: list[dict[str, object]], encoding: str) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")

    preamble: list[list[str]] = [
        ["支付宝交易明细"],
        ["账号：[某某@example.com]"],
        ["起始日期：[2026-06-01 00:00:00] 终止日期：[2026-10-21 23:59:59]"],
        ["导出时间：[2026-10-21 20:01:33]"],
        ["共669笔记录"],
        ["收入：2笔 共￥300.00"],
        ["支出：512笔 共￥28000.00"],
        ["不计收支：155笔"],
        ["说明：1. 交易分类仅作参考"],
        ["说明：2. 金额单位为元"],
        ["交易时间：2026-06-01 至 2026-10-21"],
        [],  # 第 12 行：空行
        ["以下为交易明细"],
        ["导出格式：CSV"],
        ["编码：GB18030"],
        ["仅供参考"],
        ["账号安全提示"],
        ["请勿泄露账单"],
        ["支付宝（中国）网络技术有限公司"],
        ["—— 明细开始 ——"],
        ["说明：金额单位为元"],
        [],  # 第 22 行：空行
        ["导出说明：本文件由支付宝导出"],
    ]
    assert len(preamble) == 23, "前言必须恰好 23 行（表头在第 24 行）"
    for line in preamble:
        writer.writerow(line)

    writer.writerow(ALIPAY_COLUMNS)

    for offset, row in enumerate(rows):
        occurred = row["occurred"]
        assert isinstance(occurred, datetime)
        cents = int(row["amount_cents"])  # type: ignore[arg-type]
        writer.writerow(
            [
                occurred.strftime("%Y-%m-%d %H:%M:%S"),
                ALIPAY_CATEGORIES[offset % len(ALIPAY_CATEGORIES)],
                row["counterparty"],
                f"zh****{offset % 1000:03d}@example.com",
                row["item"],
                ALIPAY_RAW_DIRECTION[str(row["direction"])],
                f"{cents / 100:.2f}",
                ALIPAY_PAY_METHODS[offset % len(ALIPAY_PAY_METHODS)],
                ALIPAY_STATUS[offset % len(ALIPAY_STATUS)],
                f"2026{offset:014d}\t",
                f"T200P{offset:010d}\t",
                "",
                "",
            ]
        )

    text = buffer.getvalue()
    path.write_bytes(text.encode(encoding))


def write_no_header(path: Path) -> None:
    lines = [
        "某某银行流水导出",
        "",
        "日期,摘要,发生额",
        "2026-10-01,消费,-12.30",
        "2026-10-02,退款,5.00",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_broken_encoding(path: Path) -> None:
    """既不是合法 UTF-8、也不是合法 GB18030 的字节序列（U-TM/EX-02 用）。"""
    payload = b"\xff\xff\x81\x30\xff\xfe\x00\x81" * 64
    path.write_bytes(payload)


def main() -> None:
    wechat_rows = build_rows(WECHAT_MONTHS, WECHAT_DIRECTIONS, seed=20261021, duplicate_groups=20)
    alipay_rows = build_rows(ALIPAY_MONTHS, ALIPAY_DIRECTIONS, seed=20261022, duplicate_groups=29)

    write_wechat(FIXTURES / "wechat_sample_sanitized.xlsx", wechat_rows)
    write_wechat(FIXTURES / "wechat_header_shifted.xlsx", wechat_rows, shift=5)
    write_alipay(FIXTURES / "alipay_sample_gb18030.csv", alipay_rows, "gb18030")
    write_alipay(FIXTURES / "alipay_sample_utf8.csv", alipay_rows, "utf-8")
    write_no_header(FIXTURES / "no_header.csv")
    write_broken_encoding(FIXTURES / "broken_encoding.csv")

    print(f"wechat rows={len(wechat_rows)} alipay rows={len(alipay_rows)}")


if __name__ == "__main__":
    main()
