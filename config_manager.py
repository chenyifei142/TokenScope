"""Runtime configuration, Windows credential storage, and logging."""

from __future__ import annotations

import ast
import ctypes
import json
import logging
import os
import shutil
import sys
from ctypes import wintypes
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app_identity import APP_STORAGE_NAME, SINGLE_INSTANCE_MUTEX

APP_NAME = APP_STORAGE_NAME


SECRET_KEYS = (
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_AUTH",
    "DEEPSEEK_COOKIE",
    "MIMO_COOKIE",
    "MIMO_API_PLATFORM_PH",
    "MIMO_API_KEY",
)
OFFICIAL_HOSTS = {
    "platform.deepseek.com",
    "api.deepseek.com",
    "platform.xiaomimimo.com",
}
DEFAULT_CONFIG: dict[str, Any] = {
    "DEEPSEEK_API_KEY": "",
    "DEEPSEEK_AUTH": "",
    "DEEPSEEK_COOKIE": "",
    "DEEPSEEK_BASE": "https://platform.deepseek.com",
    "MIMO_COOKIE": "",
    "MIMO_API_PLATFORM_PH": "",
    "MIMO_API_KEY": "",
    "MIMO_BASE": "https://platform.xiaomimimo.com",
    "REFRESH_INTERVAL": 60_000,
    "WIDGET_COMPACT_SIZE": 88,
    "WIDGET_EXPANDED_SIZE": (820, 564),
    "BG_COLOR": "#071427",
    "ACCENT_COLOR": "#2f6fe4",
    "TEXT_COLOR": "#edf4ff",
    "ACTIVE_PROVIDER": "deepseek",
    "EDGE_HIDE_ENABLED": True,
    "PANEL_AUTO_COLLAPSE_ON_DEACTIVATE": True,
    "UI_THEME": "dark",
    "UPDATE_AUTO_CHECK_ENABLED": True,
    "UPDATE_CHANNEL": "stable",
    "UPDATE_SKIPPED_VERSION": "",
    "MINUTE_USAGE_CHART_TYPE": "bar",
    "MINUTE_USAGE_INTERVAL_MINUTES": 5,
    "MINUTE_USAGE_RETENTION_DAYS": 3,
}
FIELD_META: dict[str, dict[str, Any]] = {
    **{key: {"kind": "text", "secret": key in SECRET_KEYS} for key in DEFAULT_CONFIG},
    "REFRESH_INTERVAL": {"kind": "int", "min": 5_000},
    "WIDGET_COMPACT_SIZE": {"kind": "int", "min": 88, "max": 124},
    "WIDGET_EXPANDED_SIZE": {"kind": "tuple_int"},
    "BG_COLOR": {"kind": "color"},
    "ACCENT_COLOR": {"kind": "color"},
    "TEXT_COLOR": {"kind": "color"},
    "EDGE_HIDE_ENABLED": {"kind": "bool"},
    "PANEL_AUTO_COLLAPSE_ON_DEACTIVATE": {"kind": "bool"},
    "UI_THEME": {"kind": "choice", "choices": ("system", "light", "dark")},
    "UPDATE_AUTO_CHECK_ENABLED": {"kind": "bool"},
    "MINUTE_USAGE_CHART_TYPE": {"kind": "choice", "choices": ("bar", "line")},
    "MINUTE_USAGE_INTERVAL_MINUTES": {"kind": "int", "min": 1, "max": 60},
    "MINUTE_USAGE_RETENTION_DAYS": {"kind": "int", "min": 1, "max": 365},
}


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


DEFAULT_CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
LOCATION_PATH = DEFAULT_CONFIG_DIR / "location.json"
_LOCATION_VERSION = 1


def _normalize_data_dir(value: str | os.PathLike[str]) -> Path:
    raw_value = os.path.expandvars(os.path.expanduser(str(value).strip()))
    if not raw_value:
        raise ValueError("应用数据目录不能为空")
    if raw_value.startswith("\\\\"):
        raise ValueError("应用数据目录不支持网络共享路径")
    path = Path(raw_value)
    if not path.is_absolute():
        raise ValueError("应用数据目录必须使用绝对路径")
    return path.resolve(strict=False)


def _load_location_state() -> dict[str, Any]:
    try:
        values = json.loads(LOCATION_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return values if isinstance(values, dict) else {}


def _write_location_state(values: dict[str, Any]) -> None:
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"version": _LOCATION_VERSION, **values}
    temp_path = LOCATION_PATH.with_suffix(".json.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temp_path.replace(LOCATION_PATH)


def _another_instance_running() -> bool:
    if sys.platform != "win32":
        return False
    synchronize = 0x00100000
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    handle = kernel32.OpenMutexW(synchronize, False, SINGLE_INSTANCE_MUTEX)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def _validate_separate_dirs(source: Path, target: Path) -> None:
    source = source.resolve(strict=False)
    target = target.resolve(strict=False)
    if source == target:
        return
    if source in target.parents or target in source.parents:
        raise ValueError("新旧应用数据目录不能互相包含")


def _data_entries(
    path: Path, *, exclude_migration_backups: bool = False
) -> list[Path]:
    if not path.exists():
        return []
    location_path = LOCATION_PATH.resolve(strict=False)
    return [
        item
        for item in path.iterdir()
        if item.resolve(strict=False) != location_path
        and (
            not exclude_migration_backups
            or not item.name.startswith("migration-backup-")
        )
    ]


def validate_data_dir_target(value: str | os.PathLike[str]) -> Path:
    target = _normalize_data_dir(value)
    current = CONFIG_DIR.resolve(strict=False)
    _validate_separate_dirs(current, target)
    if target == current:
        return target
    target.mkdir(parents=True, exist_ok=True)
    probe_path = target / ".tokenscope-write-test"
    try:
        probe_path.write_text("ok", encoding="utf-8")
        probe_path.unlink()
    except OSError as exc:
        raise ValueError(f"应用数据目录不可写：{exc}") from exc
    default_dir = DEFAULT_CONFIG_DIR.resolve(strict=False)
    if target != default_dir and _data_entries(target):
        raise ValueError("新的应用数据目录必须为空")
    return target


def _migrate_data_dir(source: Path, target: Path) -> None:
    source = source.resolve(strict=False)
    target = target.resolve(strict=False)
    _validate_separate_dirs(source, target)
    if source == target:
        return
    if not source.is_dir():
        raise ValueError("原应用数据目录不存在")
    target.mkdir(parents=True, exist_ok=True)
    restoring_default = target == DEFAULT_CONFIG_DIR.resolve(strict=False)
    target_entries = _data_entries(
        target, exclude_migration_backups=restoring_default
    )
    if target_entries:
        if not restoring_default:
            raise ValueError("新的应用数据目录必须为空")
        backup_dir = target / datetime.now().strftime("migration-backup-%Y%m%d-%H%M%S")
        backup_dir.mkdir(parents=True, exist_ok=False)
        for item in target_entries:
            shutil.move(str(item), str(backup_dir / item.name))
    for item in _data_entries(source, exclude_migration_backups=True):
        destination = target / item.name
        if item.is_dir():
            shutil.copytree(item, destination)
        else:
            temp_path = destination.with_name(f".{destination.name}.migration.tmp")
            shutil.copy2(item, temp_path)
            temp_path.replace(destination)


def _remove_migrated_data_dir(source: Path) -> None:
    source = source.resolve(strict=False)
    for item in _data_entries(source):
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    if source != DEFAULT_CONFIG_DIR.resolve(strict=False):
        source.rmdir()


def _initialize_data_dir() -> tuple[Path, dict[str, Any]]:
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    state = _load_location_state()
    try:
        active_dir = _normalize_data_dir(
            state.get("data_dir") or str(DEFAULT_CONFIG_DIR)
        )
    except ValueError:
        active_dir = DEFAULT_CONFIG_DIR.resolve(strict=False)
        state = {"data_dir": str(active_dir), "migration_error": "目录指针无效"}

    pending_value = state.get("pending_data_dir")
    if pending_value and not _another_instance_running():
        source_dir = active_dir
        try:
            pending_dir = _normalize_data_dir(pending_value)
            _migrate_data_dir(source_dir, pending_dir)
            next_state = {"data_dir": str(pending_dir)}
            _write_location_state(next_state)
        except (OSError, ValueError) as exc:
            active_dir = source_dir
            state = {"data_dir": str(source_dir), "migration_error": str(exc)}
            try:
                _write_location_state(state)
            except OSError:
                pass
        else:
            active_dir = pending_dir
            state = next_state
            try:
                _remove_migrated_data_dir(source_dir)
            except OSError as exc:
                state = {**state, "migration_error": f"原应用数据目录清理失败：{exc}"}
                try:
                    _write_location_state(state)
                except OSError:
                    pass

    try:
        active_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        active_dir = DEFAULT_CONFIG_DIR.resolve(strict=False)
        active_dir.mkdir(parents=True, exist_ok=True)
        state = {"data_dir": str(active_dir), "migration_error": str(exc)}
        _write_location_state(state)
    return active_dir, state


def config_dir() -> Path:
    # 启动阶段已经通过固定指针解析实际数据目录。
    return CONFIG_DIR


CONFIG_DIR, _location_state = _initialize_data_dir()
WIDGET_STATE_PATH = CONFIG_DIR / "widget-state.json"
PANEL_LAYOUT_PATH = CONFIG_DIR / "panel-layout.json"
CONFIG_PATH = CONFIG_DIR / "config.json"
LOG_PATH = CONFIG_DIR / "TokenSpider.log"
UPDATE_STATE_PATH = CONFIG_DIR / "update-state.json"
UPDATE_CACHE_DIR = CONFIG_DIR / "updates"
PENDING_UPDATE_CLEANUP_PATH = CONFIG_DIR / "pending-update-cleanup.json"
UPDATER_LOG_PATH = CONFIG_DIR / "TokenScopeUpdater.log"
LEGACY_CONFIG_PATH = app_dir() / "config.py"
_config: dict[str, Any] = DEFAULT_CONFIG.copy()
_logger_ready = False


def pending_data_dir() -> Path | None:
    value = _location_state.get("pending_data_dir")
    if not value:
        return None
    try:
        return _normalize_data_dir(value)
    except ValueError:
        return None


def data_dir_migration_error() -> str:
    return str(_location_state.get("migration_error") or "")


def schedule_data_dir_change(value: str | os.PathLike[str]) -> bool:
    global _location_state
    target = validate_data_dir_target(value)
    current = CONFIG_DIR.resolve(strict=False)
    if target == current:
        state = {"data_dir": str(current)}
        changed = bool(_location_state.get("pending_data_dir"))
    else:
        state = {"data_dir": str(current), "pending_data_dir": str(target)}
        changed = _location_state.get("pending_data_dir") != str(target)
    _write_location_state(state)
    _location_state = state
    return changed


def logger() -> logging.Logger:
    global _logger_ready
    log = logging.getLogger(APP_NAME)
    if not _logger_ready:
        handler = RotatingFileHandler(
            LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False
        _logger_ready = True
    return log


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_CREDENTIALW_TYPE = 1  # CRED_TYPE_GENERIC
# Initialise the advapi32 DLL binding on first import (i.e. the main
# thread). Doing this lazily inside worker threads can trigger an
# `Error calling Python override of QThread::run()` because Windows
# credential APIs expect to be called from a thread that has already
# performed module initialisation.
_advapi32 = None
if os.name == "nt":
    try:
        _advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        _advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
        ]
        _advapi32.CredReadW.restype = wintypes.BOOL
        _advapi32.CredWriteW.argtypes = [
            ctypes.POINTER(_CREDENTIALW),
            wintypes.DWORD,
        ]
        _advapi32.CredWriteW.restype = wintypes.BOOL
        _advapi32.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        _advapi32.CredDeleteW.restype = wintypes.BOOL
        _advapi32.CredFree.argtypes = [ctypes.c_void_p]
    except Exception:
        _advapi32 = None


def _credential_target(key: str) -> str:
    return f"{APP_NAME}/{key}"


def _read_credential(key: str) -> str:
    if os.name != "nt":
        return os.environ.get(key, "")
    if _advapi32 is None:
        return ""
    pointer = ctypes.POINTER(_CREDENTIALW)()
    try:
        if not _advapi32.CredReadW(
            _credential_target(key),
            _CREDENTIALW_TYPE,
            0,
            ctypes.byref(pointer),
        ):
            return ""
        credential = pointer.contents
        if not credential.CredentialBlob or not credential.CredentialBlobSize:
            return ""
        raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return raw.decode("utf-16-le")
    except Exception:
        return ""
    finally:
        if pointer:
            try:
                _advapi32.CredFree(pointer)
            except Exception:
                pass


def _write_credential(key: str, value: str) -> None:
    if os.name != "nt":
        if value:
            raise OSError("非 Windows 环境请通过同名环境变量提供凭证")
        return
    if _advapi32 is None:
        if value:
            raise OSError("Windows 凭据管理器不可用，凭据未保存")
        return
    if not value:
        if not _advapi32.CredDeleteW(_credential_target(key), _CREDENTIALW_TYPE, 0):
            error = ctypes.get_last_error()
            # 1168 表示凭据本来就不存在，属于幂等删除成功。
            if error != 1168:
                raise ctypes.WinError(error)
        return
    raw = value.encode("utf-16-le")
    blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    credential = _CREDENTIALW()
    credential.Type = _CREDENTIALW_TYPE
    credential.TargetName = _credential_target(key)
    credential.CredentialBlobSize = len(raw)
    credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = 2
    credential.UserName = APP_NAME
    if not _advapi32.CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError()


def _parse_legacy_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id.isupper():
                values[target.id] = ast.literal_eval(node.value)
    return values


def validate_value(key: str, value: Any) -> Any:
    meta = FIELD_META.get(key, {"kind": "text"})
    kind = meta["kind"]
    if kind == "int":
        value = int(value)
        if "min" in meta and value < meta["min"]:
            raise ValueError(f"{key} 不能小于 {meta['min']}")
        if "max" in meta and value > meta["max"]:
            raise ValueError(f"{key} 不能大于 {meta['max']}")
        return value
    if kind == "tuple_int":
        if isinstance(value, list):
            value = tuple(value)
        if isinstance(value, str):
            parts = [p.strip() for p in value.replace("x", ",").split(",") if p.strip()]
            if len(parts) != 2:
                raise ValueError(f"{key} 必须是宽,高格式")
            value = (int(parts[0]), int(parts[1]))
        if not isinstance(value, tuple) or len(value) != 2 or not all(
            isinstance(v, int) for v in value
        ):
            raise ValueError(f"{key} 必须是两个整数")
        if value[0] < 280 or value[1] < 360:
            raise ValueError(f"{key} 尺寸过小")
        return value
    if kind == "color":
        value = str(value).strip()
        if len(value) != 7 or not value.startswith("#"):
            raise ValueError(f"{key} 必须是 #RRGGBB 颜色")
        int(value[1:], 16)
        return value
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        raise ValueError(f"{key} 必须是布尔值")
    if kind == "choice":
        normalized = str(value).strip().lower()
        if normalized not in meta["choices"]:
            choices = ", ".join(meta["choices"])
            raise ValueError(f"{key} must be one of: {choices}")
        return normalized
    return str(value)


# 旧调用方可能仍引用私有函数；保留别名，设置窗口已改用公开入口。
_validate_value = validate_value


def validate_config(values: dict[str, Any]) -> dict[str, Any]:
    merged = DEFAULT_CONFIG.copy()
    merged.update(values)
    for key in list(merged):
        merged[key] = validate_value(key, merged[key])
    active_provider = str(merged.get("ACTIVE_PROVIDER", "deepseek")).strip().lower()
    if active_provider not in {"deepseek", "mimo"}:
        raise ValueError("ACTIVE_PROVIDER 必须是 deepseek 或 mimo")
    merged["ACTIVE_PROVIDER"] = active_provider
    update_channel = str(merged.get("UPDATE_CHANNEL", "stable")).strip().lower()
    if update_channel not in {"stable", "prerelease"}:
        raise ValueError("UPDATE_CHANNEL must be stable or prerelease")
    merged["UPDATE_CHANNEL"] = update_channel
    # Provider 凭据会随请求发送，因此自定义地址至少必须是完整的 HTTP(S) URL；
    # 是否信任非官方主机由设置窗口在保存前再次向用户确认。
    for key in FIELD_META:
        if not str(key).endswith("_BASE"):
            continue
        value = str(merged.get(key, "")).strip()
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"{key} 必须是有效的 HTTP(S) 地址")
    return merged


def is_official_base_url(value: str) -> bool:
    return (urlparse(value).hostname or "").lower() in OFFICIAL_HOSTS


def _public_values(values: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in values.items() if key not in SECRET_KEYS}
    result["credential_store"] = "windows-credential-manager"
    return result


def _write_json(path: Path, values: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _load_public_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("config.json 顶层必须是对象")
    value.pop("credential_store", None)
    compact_size = int(value.get("WIDGET_COMPACT_SIZE", 88))
    # 96/108/120 were earlier defaults rather than user choices; migrate only
    # those known defaults so other valid custom sizes remain untouched.
    if compact_size < 88 or compact_size in (96, 108, 120):
        value["WIDGET_COMPACT_SIZE"] = 88
    panel_size = value.get("WIDGET_EXPANDED_SIZE", [820, 564])
    if isinstance(panel_size, (list, tuple)) and len(panel_size) == 2:
        if int(panel_size[0]) < 680 or int(panel_size[1]) < 564:
            value["WIDGET_EXPANDED_SIZE"] = [820, 564]
    return value


def _migrate_legacy_config() -> dict[str, Any]:
    values = _parse_legacy_config(LEGACY_CONFIG_PATH)
    if not values:
        return {}
    for key in SECRET_KEYS:
        secret = str(values.pop(key, ""))
        if secret:
            _write_credential(key, secret)
    logger().info("Migrated legacy config to user data directory")
    return values


def ensure_config_file() -> None:
    if CONFIG_PATH.exists():
        return
    values = DEFAULT_CONFIG.copy()
    legacy_values = _migrate_legacy_config()
    values.update(legacy_values)
    _write_json(CONFIG_PATH, _public_values(validate_config(values)))
    if legacy_values:
        try:
            # 凭据和普通配置均落盘成功后移除明文旧文件，避免迁移后仍残留一份密钥。
            LEGACY_CONFIG_PATH.unlink()
        except OSError:
            logger().warning("Legacy config could not be removed: %s", LEGACY_CONFIG_PATH)
    logger().info("Created config at %s", CONFIG_PATH)


def load_widget_position() -> tuple[int, int] | None:
    try:
        value = json.loads(WIDGET_STATE_PATH.read_text(encoding="utf-8"))
        return int(value["x"]), int(value["y"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def save_widget_position(x: int, y: int) -> None:
    try:
        # 位置状态独立于用户配置，拖动时不会触发配置备份或凭据写入。
        WIDGET_STATE_PATH.write_text(
            json.dumps({"x": int(x), "y": int(y)}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        logger().warning("Widget position could not be saved")


def load_panel_layout_state() -> dict[str, Any]:
    try:
        value = json.loads(PANEL_LAYOUT_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def save_panel_layout_state(values: dict[str, Any]) -> None:
    try:
        # 面板排序变化频率高于普通设置，单独落盘可避免触发配置备份与凭据回滚流程。
        _write_json(PANEL_LAYOUT_PATH, values)
    except OSError:
        logger().warning("Panel layout state could not be saved")


def updates_dir() -> Path:
    UPDATE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return UPDATE_CACHE_DIR


def load_update_state() -> dict[str, Any]:
    try:
        value = json.loads(UPDATE_STATE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def save_update_state(values: dict[str, Any]) -> None:
    current = load_update_state()
    current.update(values)
    _write_json(UPDATE_STATE_PATH, current)


def load_pending_update_cleanup() -> dict[str, Any]:
    try:
        value = json.loads(PENDING_UPDATE_CLEANUP_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def save_pending_update_cleanup(values: dict[str, Any]) -> None:
    _write_json(PENDING_UPDATE_CLEANUP_PATH, values)


def clear_pending_update_cleanup() -> None:
    try:
        PENDING_UPDATE_CLEANUP_PATH.unlink(missing_ok=True)
    except OSError:
        logger().warning("Pending update cleanup manifest could not be removed")


def load_config() -> dict[str, Any]:
    global _config
    ensure_config_file()
    try:
        values = _load_public_config()
        for key in SECRET_KEYS:
            values[key] = _read_credential(key)
        _config = validate_config(values)
    except Exception as exc:
        logger().exception("Config load failed, using previous/default values: %s", exc)
    return _config.copy()


def get(key: str, default: Any = None) -> Any:
    return _config.get(key, default)


def all_config() -> dict[str, Any]:
    return _config.copy()


def _prune_backups() -> None:
    backups = sorted(CONFIG_DIR.glob("config.json.bak-*"), reverse=True)
    for path in backups[3:]:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # 备份清理失败不能回滚已经原子写入的有效配置。
            logger().warning("Old config backup could not be removed: %s", path)


def save_config(values: dict[str, Any]) -> dict[str, Any]:
    global _config
    ensure_config_file()
    merged = _config.copy()
    merged.update(values)
    validated = validate_config(merged)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    backup_path = CONFIG_DIR / f"config.json.bak-{stamp}"
    temp_path = CONFIG_DIR / "config.json.tmp"
    _write_json(backup_path, _public_values(_config))
    old_secrets = {key: _config.get(key, "") for key in SECRET_KEYS}
    try:
        for key in SECRET_KEYS:
            _write_credential(key, validated[key])
        _write_json(temp_path, _public_values(validated))
        temp_path.replace(CONFIG_PATH)
        _config = validated.copy()
        _prune_backups()
        logger().info("Config saved successfully")
        return _config.copy()
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        # 多个凭据必须作为一组回滚，避免中途失败后出现新旧凭据混用。
        for key, value in old_secrets.items():
            try:
                _write_credential(key, value)
            except Exception:
                logger().exception("Credential rollback failed for %s", key)
        logger().exception("Config save failed; public config was not replaced: %s", exc)
        raise


def save_ui_theme(mode: str) -> str:
    """Atomically persist only the public theme preference."""
    global _config
    normalized = validate_value("UI_THEME", mode)
    temp_path = CONFIG_PATH.with_name(f"{CONFIG_PATH.name}.theme.tmp")
    try:
        if CONFIG_PATH.exists():
            public_values = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(public_values, dict):
                raise ValueError("config.json top level must be an object")
        else:
            public_values = _public_values(DEFAULT_CONFIG)

        # Read from disk instead of an in-memory settings draft, and strip any
        # accidentally persisted secrets so a theme click can never expose them.
        for key in SECRET_KEYS:
            public_values.pop(key, None)
        public_values["credential_store"] = "windows-credential-manager"
        public_values["UI_THEME"] = normalized
        _write_json(temp_path, public_values)
        temp_path.replace(CONFIG_PATH)
    except Exception:
        temp_path.unlink(missing_ok=True)
        logger().exception("Theme preference could not be saved")
        raise

    updated = _config.copy()
    updated["UI_THEME"] = normalized
    _config = updated
    return normalized


load_config()
