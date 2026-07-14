from __future__ import annotations

from datetime import datetime
from typing import Any

from database.repositories import AgentRepository
from evaluation.agent_harness.schemas import HarnessAssertion, HarnessCase


def _runtime_tool_names(result: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for call in result.get("tool_calls") or []:
        if isinstance(call, dict):
            name = str(call.get("tool_name") or "")
            if name:
                names.append(name)
    for call in snapshot.get("tool_calls") or []:
        if isinstance(call, dict):
            name = str(call.get("tool_name") or "")
            if name:
                names.append(name)
    return list(dict.fromkeys(names))


def _run_status(result: dict[str, Any], snapshot: dict[str, Any]) -> str:
    run = snapshot.get("run") if isinstance(snapshot.get("run"), dict) else {}
    runtime = result.get("runtime") if isinstance(result.get("runtime"), dict) else {}
    return str(run.get("status") or runtime.get("status") or "")


def _status_transitions(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    run = snapshot.get("run") if isinstance(snapshot.get("run"), dict) else {}
    metadata = run.get("metadata_json")
    if not isinstance(metadata, dict):
        metadata = run.get("metadata")
    if not isinstance(metadata, dict):
        return []
    transitions = metadata.get("status_transitions") or []
    return [item for item in transitions if isinstance(item, dict)]


def _answer_text(result: dict[str, Any]) -> str:
    return str(result.get("answer") or result.get("message") or "")


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _walk_records(value: Any, records: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        marker_keys = {
            "chunk_id",
            "news_id",
            "source_id",
            "retrieval_id",
            "database_record_id",
            "stock_code",
            "publish_time",
        }
        if any(value.get(key) for key in marker_keys):
            records.append(value)
        for child in value.values():
            _walk_records(child, records)
    elif isinstance(value, list):
        for child in value:
            _walk_records(child, records)


def _evidence_records(result: dict[str, Any], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    _walk_records(result.get("result") or {}, records)
    _walk_records(result.get("orchestration") or {}, records)
    for source in snapshot.get("sources") or []:
        if isinstance(source, dict):
            records.append(
                {
                    "source_id": source.get("source_id"),
                    "database_record_id": source.get("database_record_id"),
                    "source_type": source.get("source_type"),
                    "source_title": source.get("source_title"),
                    "publish_time": source.get("source_time"),
                    "snippet": source.get("snippet"),
                }
            )
    return records


def _evidence_ids(records: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for row in records:
        for key in ("chunk_id", "news_id", "source_id", "retrieval_id", "database_record_id"):
            value = row.get(key)
            if value not in ("", None):
                ids.add(str(value))
    return ids


def _business_write_counts(case: HarnessCase, db_path: str) -> dict[str, int]:
    repo = AgentRepository(db_path)
    counts: dict[str, int] = {}
    for table in ("action_proposals", "action_commits", "paper_order"):
        try:
            rows = repo.store.list(table, filters={"user_id": case.user_id})
        except Exception:
            rows = []
        counts[table] = len(rows)
    return counts


def _quality_assertions(
    case: HarnessCase,
    *,
    result: dict[str, Any],
    snapshot: dict[str, Any],
    db_path: str,
) -> list[HarnessAssertion]:
    expected = case.expected
    assertions: list[HarnessAssertion] = []
    answer = _answer_text(result)

    if (
        expected.required_answer_phrases
        or expected.forbidden_answer_phrases
        or expected.required_answer_numbers
        or expected.require_disclaimer
    ):
        missing = [phrase for phrase in expected.required_answer_phrases if phrase not in answer]
        forbidden = [phrase for phrase in expected.forbidden_answer_phrases if phrase in answer]
        missing_numbers = [number for number in expected.required_answer_numbers if number not in answer]
        disclaimer_ok = (not expected.require_disclaimer) or ("不构成投资建议" in answer and "不用于实盘交易" in answer)
        assertions.append(
            HarnessAssertion(
                "answer_quality",
                not missing and not forbidden and not missing_numbers and disclaimer_ok,
                {
                    "missing_phrases": missing,
                    "forbidden_phrases": forbidden,
                    "missing_numbers": missing_numbers,
                    "disclaimer_ok": disclaimer_ok,
                    "answer_preview": answer[:500],
                },
            )
        )

    if (
        expected.required_evidence_ids
        or expected.forbidden_evidence_ids
        or expected.allowed_evidence_stock_codes
        or expected.max_evidence_publish_time
    ):
        records = _evidence_records(result, snapshot)
        ids = _evidence_ids(records)
        missing_ids = [item for item in expected.required_evidence_ids if item not in ids]
        forbidden_ids = [item for item in expected.forbidden_evidence_ids if item in ids]
        stock_hits = {
            str(row.get("stock_code")).split(".")[0].zfill(6)
            for row in records
            if row.get("stock_code") not in ("", None)
        }
        wrong_stocks = sorted(stock_hits - set(expected.allowed_evidence_stock_codes)) if expected.allowed_evidence_stock_codes else []
        future_rows = []
        max_time = _parse_time(expected.max_evidence_publish_time)
        if max_time:
            for row in records:
                publish_time = _parse_time(row.get("publish_time"))
                if publish_time and publish_time > max_time:
                    future_rows.append({"id": row.get("chunk_id") or row.get("news_id") or row.get("source_id"), "publish_time": row.get("publish_time")})
        assertions.append(
            HarnessAssertion(
                "evidence_quality",
                not missing_ids and not forbidden_ids and not wrong_stocks and not future_rows,
                {
                    "required_ids": expected.required_evidence_ids,
                    "actual_ids": sorted(ids),
                    "missing_ids": missing_ids,
                    "forbidden_ids": forbidden_ids,
                    "wrong_stocks": wrong_stocks,
                    "future_rows": future_rows,
                    "record_count": len(records),
                },
            )
        )

    if expected.read_only_no_business_writes:
        counts = _business_write_counts(case, db_path)
        assertions.append(
            HarnessAssertion(
                "business_rule_safety",
                all(count == 0 for count in counts.values()),
                {"write_counts": counts},
            )
        )

    return assertions


def assert_case_result(
    case: HarnessCase,
    *,
    result: dict[str, Any],
    snapshot: dict[str, Any],
    action_results: list[dict[str, Any]],
    db_path: str,
) -> list[HarnessAssertion]:
    expected = case.expected
    tool_names = _runtime_tool_names(result, snapshot)
    status = _run_status(result, snapshot)
    replan_count = int((result.get("runtime") or {}).get("replan_count") or (result.get("orchestration") or {}).get("replan_count") or 0)
    source_count = len(snapshot.get("sources") or [])
    assertions: list[HarnessAssertion] = []

    missing_tools = [tool for tool in expected.required_tools if tool not in tool_names]
    assertions.append(
        HarnessAssertion(
            "required_tools",
            not missing_tools,
            {"required": expected.required_tools, "actual": tool_names, "missing": missing_tools},
        )
    )
    forbidden_hits = [tool for tool in expected.forbidden_tools if tool in tool_names]
    assertions.append(
        HarnessAssertion(
            "forbidden_tools",
            not forbidden_hits,
            {"forbidden": expected.forbidden_tools, "actual": tool_names, "hits": forbidden_hits},
        )
    )
    assertions.append(
        HarnessAssertion(
            "expected_status",
            not expected.expected_status or status in expected.expected_status,
            {"expected": expected.expected_status, "actual": status},
        )
    )
    assertions.append(
        HarnessAssertion(
            "replan_limit",
            replan_count <= expected.max_replan_count,
            {"max": expected.max_replan_count, "actual": replan_count},
        )
    )
    assertions.append(
        HarnessAssertion(
            "source_trace",
            source_count >= expected.min_source_count,
            {"min_source_count": expected.min_source_count, "actual": source_count},
        )
    )
    assertions.append(
        HarnessAssertion(
            "state_transitions_recorded",
            bool(_status_transitions(snapshot)),
            {"transition_count": len(_status_transitions(snapshot))},
        )
    )
    plan_ids = list((result.get("runtime") or {}).get("attached_plan_ids") or [])
    waiting_for_approval = status == "waiting_for_approval" or bool(plan_ids)
    assertions.append(
        HarnessAssertion(
            "confirmation_required_boundary",
            waiting_for_approval if expected.requires_confirmation else True,
            {"requires_confirmation": expected.requires_confirmation, "status": status, "plan_ids": plan_ids},
        )
    )

    if expected.expect_commit_status:
        commits = AgentRepository(db_path).store.list("action_commits")
        matching = [row for row in commits if row.get("status") == expected.expect_commit_status]
        assertions.append(
            HarnessAssertion(
                "expected_commit_status",
                bool(matching),
                {"expected": expected.expect_commit_status, "matching_count": len(matching)},
            )
        )

    if expected.expect_duplicate_safe:
        duplicate_actions = [
            item
            for item in action_results
            if item.get("action_type") == "confirm_latest_plan" and item.get("duplicate") is True
        ]
        duplicate_ok = all(not item.get("success", True) for item in duplicate_actions)
        assertions.append(
            HarnessAssertion(
                "duplicate_confirmation_safe",
                bool(duplicate_actions) and duplicate_ok,
                {"duplicate_actions": duplicate_actions},
            )
        )

    assertions.extend(_quality_assertions(case, result=result, snapshot=snapshot, db_path=db_path))

    return assertions
