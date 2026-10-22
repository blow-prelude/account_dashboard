"""解析器自检命令（C2 §6.2 的真实样例回归入口）。

用法::

    uv run python -m account_dashboard.parsers.check tests/fixtures/wechat_sample_sanitized.xlsx
    uv run python -m account_dashboard.parsers.check tests/fixtures/alipay_sample_gb18030.csv

输出是**逐项可比对**的固定格式（不是"差不多"）：行数、表头行号、编码、方向分布、月份分布。
任何一个数字不等都要停下来查，因为行数差 1 意味着某行被静默丢弃，后续金额统计会全错。
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from account_dashboard.infra.errors import InfraError
from account_dashboard.infra.parsers.registry import ParserRegistry
from account_dashboard.models.enums import Direction

DIRECTION_ORDER = (Direction.EXPENSE, Direction.INCOME, Direction.NEUTRAL)


def build_report(path: Path, registry: ParserRegistry | None = None) -> list[str]:
    result = (registry or ParserRegistry()).parse(path)
    direction_counts = Counter(str(row.direction) for row in result.rows)
    month_counts = Counter(
        row.occurred_at.strftime("%Y-%m") for row in result.rows if row.occurred_at is not None
    )

    head = (
        f"adapter={result.adapter} rows={result.total_rows} "
        f"header_row_no={result.header.row_index} encoding={result.encoding}"
    )
    if result.meta.get("delimiter"):
        head += f" columns={result.meta.get('column_count', 0)}"
    else:
        head += f" skipped_empty={result.stats.empty_rows_skipped}"

    directions = "{" + ",".join(
        f"'{item}':{direction_counts.get(str(item), 0)}" for item in DIRECTION_ORDER
    ) + "}"
    months = "{" + ",".join(f"'{key}':{month_counts[key]}" for key in sorted(month_counts)) + "}"
    return [head, f"direction={directions}", f"months={months}"]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("用法：python -m account_dashboard.parsers.check <账单文件>", file=sys.stderr)
        return 2
    exit_code = 0
    for raw in args:
        path = Path(raw)
        try:
            lines = build_report(path)
        except InfraError as exc:
            print(f"{path.name}: {exc.code} {exc.message}", file=sys.stderr)
            exit_code = 1
            continue
        print("\n".join(lines))
    return exit_code


if __name__ == "__main__":  # pragma: no cover - 命令行入口
    raise SystemExit(main())
