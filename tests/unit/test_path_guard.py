"""数据目录守卫用例（U-PG-01，FR-22）。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from account_dashboard.infra.path_guard import InvalidDataDir, validate_data_dir


def test_empty_path_rejected() -> None:
    with pytest.raises(InvalidDataDir):
        validate_data_dir("   ")


def test_relative_path_rejected() -> None:
    with pytest.raises(InvalidDataDir, match="绝对路径"):
        validate_data_dir("data")


def test_too_long_path_rejected(tmp_path: Path) -> None:
    long_path = tmp_path / ("a" * 200)
    with pytest.raises(InvalidDataDir, match="路径太长"):
        validate_data_dir(long_path)


def test_unc_path_rejected() -> None:
    with pytest.raises(InvalidDataDir, match="网络路径"):
        validate_data_dir(r"\\nas\share\finance")


def test_forward_slash_unc_rejected() -> None:
    with pytest.raises(InvalidDataDir, match="网络路径"):
        validate_data_dir("//nas/share/finance")


@pytest.mark.skipif(os.name != "nt", reason="Windows 专用路径规则")
def test_windows_drive_root_rejected() -> None:
    with pytest.raises(InvalidDataDir, match="磁盘根目录"):
        validate_data_dir("C:/")


@pytest.mark.skipif(os.name != "nt", reason="Windows 专用路径规则")
def test_windows_system_dir_rejected() -> None:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")  # noqa: SIM112
    with pytest.raises(InvalidDataDir, match="系统目录"):
        validate_data_dir(system_root)


@pytest.mark.skipif(os.name == "nt", reason="POSIX 专用路径规则")
def test_posix_root_rejected() -> None:
    with pytest.raises(InvalidDataDir, match="磁盘根目录"):
        validate_data_dir("/")


@pytest.mark.skipif(os.name == "nt", reason="POSIX 专用路径规则")
def test_posix_system_dir_rejected() -> None:
    with pytest.raises(InvalidDataDir, match="系统目录"):
        validate_data_dir("/etc/finance")


def test_site_packages_rejected(tmp_path: Path) -> None:
    target = tmp_path / "site-packages" / "account_dashboard"
    target.mkdir(parents=True)
    with pytest.raises(InvalidDataDir, match="程序安装目录"):
        validate_data_dir(target)


def test_node_modules_rejected(tmp_path: Path) -> None:
    target = tmp_path / "node_modules" / "data"
    target.mkdir(parents=True)
    with pytest.raises(InvalidDataDir, match="程序安装目录"):
        validate_data_dir(target)


def test_git_dir_rejected(tmp_path: Path) -> None:
    target = tmp_path / ".git" / "data"
    target.mkdir(parents=True)
    with pytest.raises(InvalidDataDir, match="程序安装目录"):
        validate_data_dir(target)


def test_file_instead_of_dir_rejected(tmp_path: Path) -> None:
    target = tmp_path / "ledger.db"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(InvalidDataDir, match="不是文件夹"):
        validate_data_dir(target)


def test_existing_dir_accepted(tmp_path: Path) -> None:
    target = tmp_path / "finance"
    target.mkdir()
    assert validate_data_dir(target) == target.resolve()


def test_missing_nested_dir_accepted(tmp_path: Path) -> None:
    target = tmp_path / "finance" / "data" / "v1"
    resolved = validate_data_dir(target)
    assert resolved == target.resolve()
    assert not resolved.exists(), "校验不应创建目录"


def test_probe_file_removed(tmp_path: Path) -> None:
    target = tmp_path / "finance"
    target.mkdir()
    validate_data_dir(target)
    leftover = [p.name for p in target.iterdir() if p.name.startswith(".write-probe-")]
    assert leftover == []


def test_dotdot_is_normalized(tmp_path: Path) -> None:
    target = tmp_path / "finance" / ".." / "finance2"
    (tmp_path / "finance2").mkdir()
    assert validate_data_dir(str(target)) == (tmp_path / "finance2").resolve()
