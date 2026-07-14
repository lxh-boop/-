from __future__ import annotations

import json

from evaluation.ragas_eval.dataset_loader import load_jsonl_dataset


def _write_jsonl(path, rows) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_dataset_loader_loads_chinese_case_and_warns_missing_reference(tmp_path) -> None:
    dataset = tmp_path / "cases.jsonl"
    _write_jsonl(dataset, [
        {
            "case_id": "case_cn",
            "user_input": "这只股票最近有什么公告风险？",
            "stock_code": "300750.SZ",
            "decision_time": "2026-06-20T15:00:00+08:00",
            "reference": "",
            "tags": ["中文"],
        }
    ])

    result = load_jsonl_dataset(dataset)

    assert len(result.cases) == 1
    assert result.cases[0].stock_code == "300750"
    assert result.cases[0].user_input.startswith("这只股票")
    assert any("reference missing" in item["warning"] for item in result.warnings)
    assert any("reference_context_ids missing" in item["warning"] for item in result.warnings)


def test_dataset_loader_records_duplicate_case_id(tmp_path) -> None:
    dataset = tmp_path / "cases.jsonl"
    row = {
        "case_id": "dup",
        "user_input": "query",
        "stock_code": "000001",
        "decision_time": "2026-06-20T15:00:00+08:00",
        "reference_context_ids": [],
    }
    _write_jsonl(dataset, [row, row])

    result = load_jsonl_dataset(dataset)

    assert len(result.cases) == 1
    assert result.errors[0]["error_type"] == "ValueError"
    assert "duplicate case_id" in result.errors[0]["error"]


def test_dataset_loader_rejects_bad_time_and_empty_query(tmp_path) -> None:
    dataset = tmp_path / "cases.jsonl"
    _write_jsonl(dataset, [
        {
            "case_id": "bad_time",
            "user_input": "query",
            "stock_code": "000001",
            "decision_time": "2026-06-20 15:00:00",
            "reference_context_ids": [],
        },
        {
            "case_id": "empty_query",
            "user_input": "",
            "stock_code": "000001",
            "decision_time": "2026-06-20T15:00:00+08:00",
            "reference_context_ids": [],
        },
    ])

    result = load_jsonl_dataset(dataset)

    assert len(result.cases) == 0
    assert len(result.errors) == 2
    assert "timezone" in result.errors[0]["error"]
    assert "user_input cannot be empty" in result.errors[1]["error"]


def test_dataset_loader_rejects_non_list_reference_context_ids(tmp_path) -> None:
    dataset = tmp_path / "cases.jsonl"
    _write_jsonl(dataset, [
        {
            "case_id": "bad_refs",
            "user_input": "query",
            "stock_code": "000001",
            "decision_time": "2026-06-20T15:00:00+08:00",
            "reference_context_ids": "chunk_1",
        }
    ])

    result = load_jsonl_dataset(dataset)

    assert len(result.cases) == 0
    assert "reference_context_ids must be a list" in result.errors[0]["error"]


def test_dataset_loader_preserves_captured_production_response(tmp_path) -> None:
    dataset = tmp_path / "captured.jsonl"
    _write_jsonl(dataset, [{
        "case_id": "captured_1",
        "user_input": "查询 002468 的新闻证据",
        "stock_code": "002468",
        "decision_time": "2026-06-24T15:00:00+08:00",
        "reference": "公司公告了股份回购计划。",
        "reference_context_ids": ["chunk_1"],
        "actual_response": "用户实际看到的回答。",
        "response_run_id": "agent_run_1",
        "response_source": "production_agent_runtime",
    }])

    result = load_jsonl_dataset(dataset)

    assert result.cases[0].actual_response == "用户实际看到的回答。"
    assert result.cases[0].response_run_id == "agent_run_1"
    assert result.cases[0].response_source == "production_agent_runtime"
