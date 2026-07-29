from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import model_zoo_backend


def test_windows_relative_model_path_resolves_inside_linux_project(
    monkeypatch,
    tmp_path: Path,
) -> None:
    model_dir = (
        tmp_path
        / "models"
        / "external_zoo"
        / "chronos"
        / "chronos_bolt_small"
    )
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "model.safetensors").write_bytes(b"model")

    entry = SimpleNamespace(
        name="chronos_bolt_small",
        adapter="chronos",
        local_path=(
            r"models\external_zoo\chronos\chronos_bolt_small"
        ),
    )
    monkeypatch.setattr(model_zoo_backend, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        model_zoo_backend,
        "get_model_entry",
        lambda _name: entry,
    )
    monkeypatch.setattr(
        model_zoo_backend,
        "get_model_metadata",
        lambda _name: {
            "status": "downloaded",
            "local_path": entry.local_path,
        },
    )

    resolved = model_zoo_backend.resolve_zoo_local_path(entry.name)

    assert resolved == model_dir.resolve()


def test_absolute_windows_project_path_remaps_from_models_segment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    model_dir = (
        tmp_path
        / "models"
        / "external_zoo"
        / "chronos"
        / "chronos_bolt_small"
    )
    model_dir.mkdir(parents=True)

    entry = SimpleNamespace(
        name="chronos_bolt_small",
        adapter="chronos",
        local_path=(
            r"D:\stock_daily_app\models\external_zoo"
            r"\chronos\chronos_bolt_small"
        ),
    )
    monkeypatch.setattr(model_zoo_backend, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        model_zoo_backend,
        "get_model_entry",
        lambda _name: entry,
    )
    monkeypatch.setattr(
        model_zoo_backend,
        "get_model_metadata",
        lambda _name: {
            "status": "downloaded",
            "local_path": entry.local_path,
        },
    )

    resolved = model_zoo_backend.resolve_zoo_local_path(entry.name)

    assert resolved == model_dir.resolve()


def test_validate_uses_resolved_path_before_dependency_check(
    monkeypatch,
    tmp_path: Path,
) -> None:
    model_dir = (
        tmp_path
        / "models"
        / "external_zoo"
        / "chronos"
        / "chronos_bolt_small"
    )
    model_dir.mkdir(parents=True)

    entry = SimpleNamespace(
        name="chronos_bolt_small",
        adapter="chronos",
        local_path=(
            r"models\external_zoo\chronos\chronos_bolt_small"
        ),
    )
    monkeypatch.setattr(model_zoo_backend, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        model_zoo_backend,
        "get_model_entry",
        lambda _name: entry,
    )
    monkeypatch.setattr(
        model_zoo_backend,
        "get_model_metadata",
        lambda _name: {
            "status": "downloaded",
            "local_path": entry.local_path,
        },
    )
    monkeypatch.setattr(
        model_zoo_backend,
        "ZOO_OPTIONAL_DEPENDENCIES",
        {},
    )

    ok, message = model_zoo_backend.validate_zoo_backend_environment(
        entry.name
    )

    assert ok is True
    assert "检查通过" in message

def test_project_root_has_priority_over_existing_stale_absolute_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_model_dir = (
        tmp_path
        / "models"
        / "external_zoo"
        / "chronos"
        / "chronos_bolt_small"
    )
    project_model_dir.mkdir(parents=True)

    stale_root = tmp_path / "stale_checkout"
    stale_model_dir = (
        stale_root
        / "models"
        / "external_zoo"
        / "chronos"
        / "chronos_bolt_small"
    )
    stale_model_dir.mkdir(parents=True)

    entry = SimpleNamespace(
        name="chronos_bolt_small",
        adapter="chronos",
        local_path=str(stale_model_dir),
    )
    monkeypatch.setattr(model_zoo_backend, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        model_zoo_backend,
        "get_model_entry",
        lambda _name: entry,
    )
    monkeypatch.setattr(
        model_zoo_backend,
        "get_model_metadata",
        lambda _name: {
            "status": "downloaded",
            "local_path": entry.local_path,
        },
    )

    resolved = model_zoo_backend.resolve_zoo_local_path(entry.name)

    assert resolved == project_model_dir.resolve()
