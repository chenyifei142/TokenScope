import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest

import data_directory


def _legacy_data(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "config.json").write_text(json.dumps({"UI_THEME": "dark"}), encoding="utf-8")
    with closing(sqlite3.connect(path / "usage.db")) as connection:
        connection.execute("CREATE TABLE usage (value INTEGER)")
        connection.execute("INSERT INTO usage VALUES (1)")
        connection.commit()
    profile = path / "browser-profile" / "Default"
    profile.mkdir(parents=True)
    (profile / "Cookies").write_bytes(b"browser-session")


def test_new_install_uses_install_directory_data(tmp_path):
    result = data_directory.resolve_data_dir(
        install_dir=tmp_path / "安装 目录", legacy_dir=tmp_path / "missing"
    )
    assert result == (tmp_path / "安装 目录" / "data").resolve()
    assert result.is_dir()


def test_existing_install_data_wins_over_legacy(tmp_path):
    installed = tmp_path / "app" / "data"
    installed.mkdir(parents=True)
    (installed / "config.json").write_text("{}", encoding="utf-8")
    legacy = tmp_path / "legacy"
    _legacy_data(legacy)

    assert data_directory.resolve_data_dir(install_dir=tmp_path / "app", legacy_dir=legacy) == installed.resolve()


def test_migration_copies_validates_switches_and_preserves_source(tmp_path):
    source = tmp_path / "legacy"
    target = tmp_path / "app" / "data"
    _legacy_data(source)

    result = data_directory.migrate_legacy_data(source, target)

    assert result == target.resolve()
    assert (source / "config.json").exists()
    assert (source / "browser-profile" / "Default" / "Cookies").exists()
    state = json.loads((target / "migration-state.json").read_text(encoding="utf-8"))
    assert state["completed"] is True
    assert state["source_preserved"] is True
    assert not list(target.parent.glob("data-migrating-*"))


@pytest.mark.parametrize("broken_name", ["config.json", "usage.db"])
def test_broken_critical_data_falls_back_and_cleans_temporary_copy(tmp_path, broken_name):
    source = tmp_path / "legacy"
    _legacy_data(source)
    (source / broken_name).write_bytes(b"not-valid")
    install = tmp_path / "app"

    assert data_directory.resolve_data_dir(install_dir=install, legacy_dir=source) == source.resolve()
    assert source.exists()
    assert not (install / "data").exists()
    assert not list(install.glob("data-migrating-*"))


def test_broken_widget_state_is_noncritical(tmp_path):
    source = tmp_path / "legacy"
    _legacy_data(source)
    (source / "widget-state.json").write_text("broken", encoding="utf-8")
    target = tmp_path / "app" / "data"

    data_directory.migrate_legacy_data(source, target)

    state = json.loads((target / "migration-state.json").read_text(encoding="utf-8"))
    assert state["warnings"]


def test_copy_and_atomic_switch_failures_keep_source(tmp_path):
    source = tmp_path / "legacy"
    _legacy_data(source)
    target = tmp_path / "app" / "data"

    with patch("data_directory.shutil.copytree", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            data_directory.migrate_legacy_data(source, target)
    assert source.exists()
    assert not list(target.parent.glob("data-migrating-*"))

    original_replace = Path.replace

    def fail_target_replace(path, destination):
        if Path(destination) == target:
            raise OSError("rename blocked")
        return original_replace(path, destination)

    with patch.object(Path, "replace", fail_target_replace):
        with pytest.raises(OSError):
            data_directory.migrate_legacy_data(source, target)
    assert source.exists()
    assert not target.exists()
    assert not list(target.parent.glob("data-migrating-*"))


def test_explicit_directory_has_highest_priority(tmp_path):
    explicit = tmp_path / "自定义 数据"
    result = data_directory.resolve_data_dir(
        explicit_dir=explicit,
        install_dir=tmp_path / "app",
        legacy_dir=tmp_path / "legacy",
    )
    assert result == explicit.resolve()


def test_unwritable_install_uses_local_fallback(tmp_path):
    fallback = tmp_path / "local" / "TokenMeter" / "data"
    with patch("data_directory._is_writable", side_effect=lambda path: path == fallback):
        result = data_directory.resolve_data_dir(
            install_dir=tmp_path / "app",
            legacy_dir=tmp_path / "missing",
            fallback_dir=fallback,
        )
    assert result == fallback.resolve()
