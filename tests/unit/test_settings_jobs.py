from __future__ import annotations

import json
from pathlib import Path

from snapreel.core.jobs import History, Job, Result, output_file
from snapreel.core.settings import Settings


def test_settings_roundtrip(data_dir: Path) -> None:
    settings = Settings.load()
    assert settings.language == "ru" and settings.performance_mode == "auto"
    settings.language = "en"
    settings.performance_mode = "low_memory"
    settings.remember("image", model="stabilityai/sd-turbo", steps=2)
    settings.save()
    assert (data_dir / "settings.json").exists()
    again = Settings.load()
    assert again.language == "en"
    assert again.performance_mode == "low_memory"
    assert again.recall("image", "steps") == 2
    assert again.recall("video", "steps", 7) == 7


def test_settings_sanitize_and_ignore_unknown(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "settings.json").write_text(json.dumps({
        "language": "de", "theme": "neon", "performance_mode": "turbo",
        "last": [], "unknown_key": 1,
    }), encoding="utf-8")
    settings = Settings.load()
    assert settings.language == "ru"
    assert settings.theme == "dark"
    assert settings.performance_mode == "auto"
    assert settings.last == {}


def test_settings_survive_corrupt_file(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "settings.json").write_text("{", encoding="utf-8")
    assert Settings.load().theme == "dark"


def test_token_prefers_settings(monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "from-env")
    settings = Settings()
    assert settings.token() == "from-env"
    settings.hf_token = "  own  "
    assert settings.token() == "own"


def test_custom_paths(tmp_path: Path) -> None:
    settings = Settings(models_dir=str(tmp_path / "m"), output_dir=str(tmp_path / "o"))
    assert settings.hub_path() == tmp_path / "m" / "hub"
    assert settings.output_path() == tmp_path / "o"


def _result(job: Job, path: Path) -> Result:
    return Result.make(job, path, "Model", 1.5, seed=3)


def test_history(tmp_path: Path) -> None:
    file = tmp_path / "history.json"
    history = History(file)
    job = Job("image", "a/b", "a cat", {"steps": 2})
    first, second = tmp_path / "1.png", tmp_path / "2.png"
    first.write_bytes(b"x")
    second.write_bytes(b"y")
    history.add(_result(job, first))
    history.add(_result(job, second))
    items = History(file).items()
    assert [Path(r.path) for r in items] == [second, first]  # newest first
    assert items[0].params == {"steps": 2, "seed": 3}
    assert History(file).items("video") == []

    first.unlink()  # removed by hand
    assert len(History(file).items()) == 1

    history.remove(items[0].id)
    assert not second.exists()
    assert History(file).items() == []


def test_history_ignores_corrupt_file(tmp_path: Path) -> None:
    file = tmp_path / "history.json"
    file.write_text('[{"id": 1}]', encoding="utf-8")
    assert History(file).items() == []


def test_output_file_is_unique(tmp_path: Path) -> None:
    first = output_file(tmp_path, "image", "png")
    first.write_bytes(b"")
    second = output_file(tmp_path, "image", "png")
    assert first != second
    assert first.parent.parent.name == "images"
    assert output_file(tmp_path, "speech", "wav").parent.parent.name == "audio"


def test_job_ids_increase() -> None:
    assert Job("image", "m", "p").id < Job("image", "m", "p").id
