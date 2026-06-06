from __future__ import annotations

import json

from app.services.file_loader import safe_read_csv, safe_read_json


def test_safe_read_csv_missing_file(tmp_path):
    result = safe_read_csv(tmp_path / "missing.csv", required_columns=["a"])
    assert not result.ok
    assert "文件不存在" in result.message


def test_safe_read_csv_empty_file(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    result = safe_read_csv(path)
    assert not result.ok
    assert "文件为空" in result.message


def test_safe_read_csv_missing_columns(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    result = safe_read_csv(path, required_columns=["a", "c"])
    assert not result.ok
    assert result.missing_columns == ["c"]


def test_safe_read_csv_replaces_inf(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("a\ninf\n", encoding="utf-8")
    result = safe_read_csv(path)
    assert result.ok
    assert result.data["a"].isna().iloc[0]


def test_safe_read_csv_reports_bad_dates(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("date,a\nbad,1\n", encoding="utf-8")
    result = safe_read_csv(path, parse_dates=["date"])
    assert result.ok
    assert "无法解析" in result.message


def test_safe_read_json_missing_and_broken(tmp_path):
    missing = safe_read_json(tmp_path / "missing.json")
    assert not missing.ok
    broken_path = tmp_path / "bad.json"
    broken_path.write_text("{bad", encoding="utf-8")
    broken = safe_read_json(broken_path)
    assert not broken.ok
    assert "JSON 读取失败" in broken.message


def test_safe_read_json_success(tmp_path):
    path = tmp_path / "ok.json"
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    result = safe_read_json(path)
    assert result.ok
    assert result.data["a"] == 1
