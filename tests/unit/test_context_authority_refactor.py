from __future__ import annotations

import sys
import types

# The audit bundle used by the isolated packaging test omits the database
# package. The real project provides it; this lightweight stub only allows the
# pure turn-resolution tests to import the module in isolation.
if "database.repositories.agent_repository" not in sys.modules:
    database_module = types.ModuleType("database")
    repositories_module = types.ModuleType("database.repositories")
    agent_repository_module = types.ModuleType("database.repositories.agent_repository")

    class _AgentRepository:
        pass

    agent_repository_module.AgentRepository = _AgentRepository
    sys.modules.setdefault("database", database_module)
    sys.modules.setdefault("database.repositories", repositories_module)
    sys.modules.setdefault("database.repositories.agent_repository", agent_repository_module)

from agent.memory.conversation_state_manager import (
    ConversationMessage,
    RELATION_CONTINUATION,
    RELATION_NEW_GOAL,
    resolve_turn_from_messages,
)
from agent.collaboration_v2.specialist_runtime import _artifact_refs
from agent.orchestration.multi_task_executor import _artifact_ref_from_result


def _history() -> list[ConversationMessage]:
    return [
        ConversationMessage(
            role="user",
            content="分析 600519",
            message_id="msg_user_1",
            run_id="run_1",
            created_at="2026-07-22 20:10:26",
        ),
        ConversationMessage(
            role="assistant",
            content="贵州茅台基础分析完成。",
            message_id="msg_assistant_1",
            run_id="run_1",
            created_at="2026-07-22 20:16:35",
            agent_result={
                "user_goal": {
                    "raw_message": "分析 600519",
                    "action": "analyze_stock",
                },
                "answer": "贵州茅台基础分析：排名169，模型置信度低。",
                "artifact_refs": [
                    {
                        "artifact_id": "artifact_stock_analysis_1",
                        "artifact_type": "stock_analysis_result",
                    }
                ],
                "result": {
                    "data": {
                        "stock_code": "600519",
                        "stock_name": "贵州茅台",
                    }
                },
                "conversation_state_after_run": {
                    "active_entities": {
                        "stock_code": "600519",
                        "stock_codes": ["600519"],
                        "stock_name": "贵州茅台",
                    }
                },
            },
        ),
    ]


def test_explicit_stock_is_authoritative_on_first_turn() -> None:
    turn = resolve_turn_from_messages(
        "分析 600519",
        conversation_id="conversation_1",
        messages=[],
    )

    assert turn.relation_type == RELATION_NEW_GOAL
    assert turn.active_entities["stock_code"] == "600519"
    assert turn.active_entities["stock_codes"] == ["600519"]


def test_more_detailed_analysis_is_continuation() -> None:
    turn = resolve_turn_from_messages(
        "还需要更详细的分析",
        conversation_id="conversation_1",
        messages=_history(),
    )

    assert turn.relation_type == RELATION_CONTINUATION
    assert turn.resolved_message == "对贵州茅台（600519）进行更详细的分析。"
    assert turn.active_entities["stock_code"] == "600519"
    assert turn.reference_turn_ids == ["msg_user_1", "msg_assistant_1", "run_1"]
    assert turn.reference_artifact_refs[0]["artifact_id"] == "artifact_stock_analysis_1"
    assert turn.reference_mode == "previous_result"
    assert turn.previous_result_summary.startswith("贵州茅台基础分析")


def test_explicit_new_stock_starts_new_goal() -> None:
    turn = resolve_turn_from_messages(
        "分析 000858",
        conversation_id="conversation_1",
        messages=_history(),
    )

    assert turn.relation_type == RELATION_NEW_GOAL
    assert turn.active_entities["stock_code"] == "000858"
    assert turn.reference_artifact_refs == []
    assert turn.previous_user_goal == {}


def test_freshness_request_uses_current_state() -> None:
    turn = resolve_turn_from_messages(
        "现在重新查询最新数据再详细分析",
        conversation_id="conversation_1",
        messages=_history(),
    )

    assert turn.relation_type == RELATION_CONTINUATION
    assert turn.reference_mode == "current_state"


def test_multi_task_boundary_preserves_persisted_artifact_ref() -> None:
    ref = _artifact_ref_from_result(
        {
            "artifact_id": "artifact_tool_1",
            "metadata": {
                "artifact_ref": {
                    "artifact_id": "artifact_tool_1",
                    "artifact_type": "tool_result",
                    "producer_id": "stock_analysis",
                }
            },
        }
    )

    assert ref == {
        "artifact_id": "artifact_tool_1",
        "artifact_type": "tool_result",
        "producer_id": "stock_analysis",
    }


def test_specialist_boundary_deduplicates_artifact_refs() -> None:
    refs = _artifact_refs(
        {
            "task_results": {
                "task_1": {
                    "artifact_id": "artifact_tool_1",
                    "artifact_refs": [
                        {
                            "artifact_id": "artifact_tool_1",
                            "artifact_type": "tool_result",
                        }
                    ],
                    "metadata": {
                        "artifact_ref": {
                            "artifact_id": "artifact_tool_1",
                            "artifact_type": "tool_result",
                        }
                    },
                    "data": {},
                }
            }
        }
    )

    assert len(refs) == 1
    assert refs[0]["artifact_id"] == "artifact_tool_1"
