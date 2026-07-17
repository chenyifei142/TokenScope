"""Resolve and safely migrate TokenMeter's runtime data directory."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MIGRATION_STATE_NAME = "migration-state.json"
LAST_MIGRATION_ERROR = ""


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def legacy_data_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "TokenSpider"


def local_fallback_data_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return root / "TokenMeter" / "data"


def _entries(path: Path) -> list[Path]:
    try:
        return [item for item in path.iterdir() if item.name != MIGRATION_STATE_NAME]
    except (FileNotFoundError, NotADirectoryError):
        return []


def _is_writable(path: Path) -> bool:
    probe_parent = path if path.exists() else path.parent
    try:
        probe_parent.mkdir(parents=True, exist_ok=True)
        probe = probe_parent / f".tokenmeter-write-{uuid.uuid4().hex}"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def _validate_copy(path: Path, warnings: list[str]) -> None:
    config_path = path / "config.json"
    if config_path.exists():
        value = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("config.json 必须包含 JSON 对象")

    database_path = path / "usage.db"
    if database_path.exists():
        # 只读 URI 防止迁移校验修改旧数据库或生成 journal/WAL 文件。
        uri = database_path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.execute("PRAGMA schema_version").fetchone()
            result = connection.execute("PRAGMA quick_check").fetchone()
            if not result or result[0] != "ok":
                raise ValueError("usage.db 完整性校验失败")

    widget_path = path / "widget-state.json"
    if widget_path.exists():
        try:
            json.loads(widget_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            # 窗口位置不是业务数据；损坏时保留原文件并允许核心数据继续迁移。
            warnings.append("widget-state.json 无法解析，已原样保留")


def migrate_legacy_data(source: Path, target: Path) -> Path:
    """Copy, validate and atomically publish a legacy data directory."""

    source = source.resolve(strict=False)
    target = target.resolve(strict=False)
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("迁移源目录和目标目录必须相互独立")
    if not source.is_dir() or not _entries(source):
        raise ValueError("旧数据目录不存在或为空")
    if target.exists() and _entries(target):
        raise ValueError("目标数据目录不是空目录")
    if not _is_writable(target):
        raise OSError("目标数据目录不可写")

    temporary = target.with_name(f"{target.name}-migrating-{uuid.uuid4().hex}")
    warnings: list[str] = []
    try:
        shutil.copytree(source, temporary)
        _validate_copy(temporary, warnings)
        state: dict[str, Any] = {
            "version": 1,
            "source": str(source),
            "target": str(target),
            "completed": True,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "source_preserved": True,
        }
        if warnings:
            state["warnings"] = warnings
        (temporary / MIGRATION_STATE_NAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if target.exists():
            # 空占位目录可以安全移除；旧数据源永远不会进入这条路径。
            target.rmdir()
        temporary.replace(target)
        return target
    except Exception:
        # 失败副本不应影响下次启动重试，也绝不能触碰旧目录。
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def resolve_data_dir(
    *,
    explicit_dir: str | os.PathLike[str] | None = None,
    install_dir: Path | None = None,
    legacy_dir: Path | None = None,
    fallback_dir: Path | None = None,
) -> Path:
    """Return the single active data directory without blocking application startup."""

    global LAST_MIGRATION_ERROR
    LAST_MIGRATION_ERROR = ""

    if explicit_dir:
        explicit = Path(os.path.expandvars(os.path.expanduser(str(explicit_dir)))).resolve(
            strict=False
        )
        explicit.mkdir(parents=True, exist_ok=True)
        return explicit

    # Source checkouts contain a Python package named data; only frozen builds use
    # the adjacent directory as writable user storage.
    install_root = install_dir or application_dir()
    installed_target = install_root / "data"
    old = (legacy_dir or legacy_data_dir()).resolve(strict=False)
    fallback = (fallback_dir or local_fallback_data_dir()).resolve(strict=False)

    if install_dir is None and not getattr(sys, "frozen", False):
        # 源码目录中的 data 是 Python 包，开发运行不能把它当作用户数据目录。
        old.mkdir(parents=True, exist_ok=True)
        return old

    if _entries(installed_target):
        return installed_target.resolve(strict=False)

    if _entries(old):
        try:
            return migrate_legacy_data(old, installed_target)
        except Exception as exc:
            LAST_MIGRATION_ERROR = type(exc).__name__
            logging.getLogger("TokenSpider").warning(
                "旧数据迁移失败，将继续使用旧数据目录：%s", LAST_MIGRATION_ERROR
            )
            return old

    if _is_writable(installed_target):
        installed_target.mkdir(parents=True, exist_ok=True)
        return installed_target.resolve(strict=False)

    fallback.mkdir(parents=True, exist_ok=True)
    return fallback
