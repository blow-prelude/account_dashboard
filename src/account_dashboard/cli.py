"""命令行入口（``uv run account-dashboard ...``）。

只暴露三条命令，全部面向非技术用户可执行的下一步：
``run`` / ``init-db`` / ``export-openapi``。
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from account_dashboard import __version__
from account_dashboard.api.app_factory import create_app
from account_dashboard.config import ConfigError, load_bootstrap_config
from account_dashboard.main import RuntimeState, StartupError, build_lifespan, startup

DEFAULT_OPENAPI_PATH = Path("docs/api/openapi.json")
GRACEFUL_TIMEOUT_SECONDS = 10


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return _run(args)
    if args.command == "init-db":
        return _init_db(args)
    if args.command == "export-openapi":
        return _export_openapi(args)
    parser.print_help()
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="account-dashboard", description="个人财务分析仪表盘（本地单用户）"
    )
    parser.add_argument("--version", action="version", version=f"account-dashboard {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="启动服务（默认 http://127.0.0.1:8765）")
    run.add_argument("--config", type=Path, default=None, help="app.toml 路径（默认当前目录）")

    init_db = sub.add_parser("init-db", help="建库/升级 schema（可重复执行）")
    init_db.add_argument("--config", type=Path, default=None)
    init_db.add_argument(
        "--force-seed", action="store_true", help="重建种子数据（分类/规则/提示/模板）"
    )

    export = sub.add_parser("export-openapi", help="导出 OpenAPI 契约")
    export.add_argument("--out", type=Path, default=DEFAULT_OPENAPI_PATH)
    export.add_argument("--config", type=Path, default=None)
    return parser


def _run(args: argparse.Namespace) -> int:
    state: RuntimeState | None = None
    try:
        state = startup(config_path=args.config)
    except StartupError as exc:
        print(exc.message, file=sys.stderr)
        return exc.exit_code

    try:
        app = create_app(
            state.config,
            database=state.database,
            paths=state.paths,
            lifespan=build_lifespan(),  # type: ignore[arg-type]
        )
        # 启动已在 CLI 完成；告知 lifespan 不要重复启动（否则会二次抢文件锁）
        app.state._runtime = state
        if state.config.open_browser:
            _open_browser_later(f"http://{state.config.host}:{state.config.port}")
        uvicorn.run(
            app,
            host=state.config.host,
            port=state.config.port,
            log_config=None,
            log_level=state.config.log_level.lower(),
            access_log=True,
            timeout_graceful_shutdown=GRACEFUL_TIMEOUT_SECONDS,
        )
    finally:
        state.shutdown()
    return 0


def _init_db(args: argparse.Namespace) -> int:
    state: RuntimeState | None = None
    try:
        state = startup(config_path=args.config, acquire_lock=False, check_port=False)
    except StartupError as exc:
        print(exc.message, file=sys.stderr)
        return exc.exit_code

    try:
        tables = _user_tables(state)
        print(f"数据库已就绪：{state.paths.db_file}")
        print(f"业务表 {len(tables)} 张：{', '.join(tables)}")
        if args.force_seed:
            print("提示：种子数据（分类/规则/提示/模板）在 C4 提供，本次仅完成建表。")
    finally:
        state.shutdown()
    return 0


def _export_openapi(args: argparse.Namespace) -> int:
    try:
        config = load_bootstrap_config(args.config)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    app = create_app(config)
    spec = app.openapi()
    out: Path = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    out.write_text(text, encoding="utf-8")
    print(f"OpenAPI 已导出：{out}")
    return 0


def _user_tables(state: RuntimeState) -> list[str]:
    rows = state.database.query_all(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'raw_%' ORDER BY name"
    )
    return [str(row["name"]) for row in rows]


def _open_browser_later(url: str) -> None:
    timer = threading.Timer(1.5, lambda: webbrowser.open(url))
    timer.daemon = True
    timer.start()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
