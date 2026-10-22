"""引导配置用例（SDD §11.3）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from account_dashboard.config import (
    BootstrapConfig,
    ConfigError,
    default_config_path,
    load_bootstrap_config,
)


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "app.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_file_uses_defaults(tmp_path: Path) -> None:
    config = load_bootstrap_config(tmp_path / "absent.toml")
    assert config == BootstrapConfig(source=None)
    assert config.host == "127.0.0.1"
    assert config.port == 8765
    assert config.log_level == "INFO"


def test_valid_config_parsed(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
[server]
host = "localhost"
port = 9000
open_browser = false
single_instance = false

[paths]
data_dir = "D:/finance"

[logging]
level = "debug"
""",
    )
    config = load_bootstrap_config(path)
    assert config.host == "localhost"
    assert config.port == 9000
    assert config.open_browser is False
    assert config.single_instance is False
    assert config.data_dir == "D:/finance"
    assert config.log_level == "DEBUG"
    assert config.source == path


def test_invalid_host_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[server]\nhost = "0.0.0.0"\n')
    with pytest.raises(ConfigError, match="127.0.0.1"):
        load_bootstrap_config(path)


def test_port_out_of_range_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path, "[server]\nport = 80\n")
    with pytest.raises(ConfigError, match="port"):
        load_bootstrap_config(path)


def test_port_wrong_type_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[server]\nport = "8765"\n')
    with pytest.raises(ConfigError, match="整数"):
        load_bootstrap_config(path)


def test_log_level_invalid_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[logging]\nlevel = "TRACE"\n')
    with pytest.raises(ConfigError, match="logging.level"):
        load_bootstrap_config(path)


def test_syntax_error_reports_line(tmp_path: Path) -> None:
    path = write_config(tmp_path, "[server]\nport = = 1\n")
    with pytest.raises(ConfigError) as excinfo:
        load_bootstrap_config(path)
    assert "第" in str(excinfo.value) and "行" in str(excinfo.value)


def test_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = write_config(tmp_path, "[server]\nport = 9010\n")
    monkeypatch.setenv("ACCOUNT_DASHBOARD_CONFIG", str(custom))
    assert default_config_path() == custom
    assert load_bootstrap_config().port == 9010
