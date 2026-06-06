from __future__ import annotations

import model_zoo_backend
from model_zoo_backend import validate_zoo_backend_environment


def test_zoo_preflight_reports_missing_dependency(monkeypatch, tmp_path):
    monkeypatch.setattr(
        model_zoo_backend,
        "get_model_metadata",
        lambda name: {"status": "downloaded", "local_path": str(tmp_path)},
    )
    monkeypatch.setitem(
        model_zoo_backend.ZOO_OPTIONAL_DEPENDENCIES,
        "chronos",
        ("definitely_missing_module_for_test", "请先安装测试依赖"),
    )
    ok, message = validate_zoo_backend_environment("chronos_bolt_small")
    assert not ok
    assert "请先安装测试依赖" in message


def test_zoo_preflight_reports_missing_model_dir(monkeypatch, tmp_path):
    missing_path = tmp_path / "missing_model"
    monkeypatch.setattr(
        model_zoo_backend,
        "get_model_metadata",
        lambda name: {"status": "downloaded", "local_path": str(missing_path)},
    )
    ok, message = validate_zoo_backend_environment("chronos_bolt_small")
    assert not ok
    assert "本地模型目录不存在" in message
