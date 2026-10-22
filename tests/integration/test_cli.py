"""CLI 用例：三条命令的可执行性与产物稳定性。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from account_dashboard.cli import main


def write_config(tmp_path: Path, port: int = 8799) -> Path:
    path = tmp_path / "app.toml"
    path.write_text(
        f"""
[server]
host = "127.0.0.1"
port = {port}
open_browser = false

[paths]
data_dir = "{(tmp_path / 'data').as_posix()}"

[logging]
level = "WARNING"
""",
        encoding="utf-8",
    )
    return path


def test_init_db_creates_tables(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    assert main(["init-db", "--config", str(config)]) == 0
    assert (tmp_path / "data" / "db" / "ledger.db").is_file()


def test_export_openapi_is_byte_stable(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    first = tmp_path / "o1.json"
    second = tmp_path / "o2.json"
    assert main(["export-openapi", "--config", str(config), "--out", str(first)]) == 0
    assert main(["export-openapi", "--config", str(config), "--out", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes(), "契约导出必须字节稳定"

    spec = json.loads(first.read_text(encoding="utf-8"))
    assert "/api/v1/health" in spec["paths"]
    assert "HealthDTO" in spec["components"]["schemas"]
    schema = spec["paths"]["/api/v1/health"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert schema, "响应必须声明 schema，禁止裸对象"


def test_run_wires_uvicorn_and_releases_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = write_config(tmp_path, port=8799)
    captured: dict[str, object] = {}

    def fake_run(app: object, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr("account_dashboard.cli.uvicorn.run", fake_run)
    assert main(["run", "--config", str(config)]) == 0

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8799
    assert captured["log_config"] is None
    assert not (tmp_path / "data" / "instance.lock").exists(), "退出后必须释放单实例锁"


def test_version_flag_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "account-dashboard" in capsys.readouterr().out


def test_unknown_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage" in capsys.readouterr().out.lower()
