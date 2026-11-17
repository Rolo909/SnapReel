"""Coming from SnapReel 1.0: data copied once, old models and results found and kept in use."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tvorka.core import migrate, paths
from tvorka.core.settings import Settings


@pytest.fixture
def appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("TVORKA_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setattr(paths.sys, "platform", "win32")
    return tmp_path / "AppData"


def old_release(root: Path) -> Path:
    home = root / "SnapReel"
    (home / "models" / "hub").mkdir(parents=True)
    (home / "output").mkdir()
    (home / "SnapReel.cmd").write_text("@echo off", encoding="utf-8")
    return home


def test_old_data_is_copied_once(appdata: Path) -> None:
    old = appdata / "SnapReel"
    (old / "plugins").mkdir(parents=True)
    (old / "settings.json").write_text('{"language": "en", "theme": "light"}', encoding="utf-8")
    (old / "plugins" / "mine.py").write_text("x = 1", encoding="utf-8")
    (old / "snapreel.lock").write_text("", encoding="utf-8")
    assert migrate.copy_old_data() == old
    new = appdata / "Tvorka"
    assert (new / "plugins" / "mine.py").exists() and not (new / "snapreel.lock").exists()
    assert (old / "settings.json").exists()  # kept as a backup
    settings = Settings.load()
    assert (settings.language, settings.theme) == ("en", "light")
    assert migrate.copy_old_data() is None  # the second start does nothing


def test_nothing_to_copy_on_a_fresh_install(appdata: Path) -> None:
    assert migrate.copy_old_data() is None and not (appdata / "Tvorka").exists()


def test_explicit_data_folder_is_left_alone(appdata: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (appdata / "SnapReel").mkdir(parents=True)
    monkeypatch.setenv("TVORKA_DATA_DIR", str(appdata / "custom"))
    assert migrate.copy_old_data() is None


def test_old_folders_found_through_the_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = old_release(tmp_path / "Games")
    new_home = tmp_path / "Desktop" / "Tvorka"
    new_home.mkdir(parents=True)
    monkeypatch.setenv("TVORKA_HOME", str(new_home))
    history = tmp_path / "history.json"
    history.write_text(json.dumps([{"path": str(home / "output" / "2026-11-16" / "image.png")}]),
                       encoding="utf-8")
    settings = Settings()
    adopted = migrate.adopt_old_folders(settings, history)
    assert settings.models_dir == str(home / "models") and settings.output_dir == str(home / "output")
    assert len(adopted) == 2


def test_old_folder_found_next_to_the_new_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = old_release(tmp_path)
    new_home = tmp_path / "Tvorka"
    new_home.mkdir()
    monkeypatch.setenv("TVORKA_HOME", str(new_home))
    settings = Settings()
    migrate.adopt_old_folders(settings, tmp_path / "no-history.json")
    assert settings.models_dir == str(home / "models")


def test_choices_of_the_user_are_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old_release(tmp_path)
    new_home = tmp_path / "Tvorka"
    (new_home / "output").mkdir(parents=True)
    (new_home / "output" / "already.png").write_bytes(b"x")  # the new folder is in use already
    monkeypatch.setenv("TVORKA_HOME", str(new_home))
    settings = Settings(models_dir="D:/my models")
    assert migrate.adopt_old_folders(settings, tmp_path / "none.json") == []
    assert settings.models_dir == "D:/my models" and settings.output_dir == ""
