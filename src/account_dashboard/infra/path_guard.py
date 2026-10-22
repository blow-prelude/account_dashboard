"""数据目录合法化（FR-22，SDD §11.4）。

校验顺序按「便宜 → 昂贵」：形状 → 绝对路径 → 长度 → 磁盘根 → UNC → 系统目录
→ 安装目录 → 解析软链后复检 → 可写探测。任何一步失败都抛 :class:`InvalidDataDir`，
由启动流程映射为退出码 2。
"""

from __future__ import annotations

import os
from pathlib import Path

MAX_PATH_LENGTH = 180
_PROBE_PREFIX = ".write-probe-"
_INSTALL_DIR_PARTS = frozenset({"site-packages", "node_modules", ".git"})


class InvalidDataDir(Exception):
    """数据目录不可用；``reason`` 为面向非技术用户的中文说明。"""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def validate_data_dir(raw: str | Path) -> Path:
    """校验并返回规范化后的绝对路径；**不创建任何目录**。"""
    if isinstance(raw, Path):
        text = str(raw)
    elif isinstance(raw, str):
        text = raw.strip()
    else:  # pragma: no cover - 防御性分支
        raise InvalidDataDir("数据目录不能为空")

    if not text:
        raise InvalidDataDir("数据目录不能为空")

    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        raise InvalidDataDir("请填写完整的绝对路径，如 D:/finance/data")
    if len(str(candidate)) > MAX_PATH_LENGTH:
        raise InvalidDataDir("路径太长，请选择层级更浅的目录")

    literal = str(candidate)
    if literal.startswith(("\\\\", "//")):
        raise InvalidDataDir("数据目录必须在本机磁盘，不能使用网络路径")

    resolved = _resolve(candidate)
    if resolved.parent == resolved:
        raise InvalidDataDir("不能直接使用磁盘根目录")

    _reject_system_dirs(resolved)
    _reject_install_dirs(resolved)
    _probe_writable(resolved)
    return resolved


def _resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError as exc:  # symlink 环 / 权限
        raise InvalidDataDir(f"目录路径无法解析：{exc}") from exc


def _system_dirs() -> list[Path]:
    dirs: list[Path] = []
    if os.name == "nt":
        for env_key in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
            value = os.environ.get(env_key)
            if value:
                dirs.append(Path(value))
        system_drive = os.environ.get("SystemDrive", "C:")  # noqa: SIM112 - Windows 实际键名
        dirs.extend(
            [
                Path(f"{system_drive}/System Volume Information"),
                Path(f"{system_drive}/$Recycle.Bin"),
            ]
        )
    else:
        dirs.extend(Path(p) for p in ("/System", "/usr", "/bin", "/sbin", "/etc", "/var"))
        dirs.extend(Path(p) for p in ("/proc", "/sys", "/dev", "/boot"))
    return dirs


def _reject_system_dirs(path: Path) -> None:
    for forbidden in _system_dirs():
        resolved_forbidden = _resolve_quiet(forbidden)
        if resolved_forbidden is None:
            continue
        if _is_same_or_child(path, resolved_forbidden):
            raise InvalidDataDir("该目录属于系统目录，请换一个普通文件夹")


def _reject_install_dirs(path: Path) -> None:
    parts = {part.lower() for part in path.parts}
    if parts & _INSTALL_DIR_PARTS:
        raise InvalidDataDir("不能放在程序安装目录内，升级会覆盖")


def _probe_writable(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise InvalidDataDir("该路径已存在但不是文件夹")
        probe = path / f"{_PROBE_PREFIX}{os.getpid()}"
        try:
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as exc:
            raise InvalidDataDir("该目录不可写入，请检查权限或以管理员身份运行") from exc
        return

    ancestor = path
    while not ancestor.exists():
        parent = ancestor.parent
        if parent == ancestor:  # pragma: no cover - 已排除磁盘根
            break
        ancestor = parent
    if not ancestor.is_dir() or not os.access(ancestor, os.W_OK):
        raise InvalidDataDir("该目录不可写入，请检查权限或以管理员身份运行")


def _resolve_quiet(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:  # pragma: no cover - 系统目录解析失败时跳过
        return None


def _is_same_or_child(path: Path, parent: Path) -> bool:
    try:
        return path == parent or path.is_relative_to(parent)
    except ValueError:  # pragma: no cover - 不同盘符
        return False
