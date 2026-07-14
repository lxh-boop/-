from __future__ import annotations

from agent.context import ContextBudget, build_agent_context
from agent.context.compressor import compress_text_preserving_facts
from agent.executor import run_agent_request
from agent.runtime import load_run_snapshot
from database.repositories import AgentRepository
from agent_control_center_utils import write_agent_fixture


DISCLAIMER = "本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。"


def test_context_builder_gathers_profile_portfolio_and_constraints(tmp_path):
    output_dir, db_path = write_agent_fixture(tmp_path, user_id="u1", with_position=True)

    context = build_agent_context(
        query="查看当前模拟盘持仓",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        run_id="run_1",
    )

    assert context.token_estimate <= context.token_budget.max_total_tokens
    assert DISCLAIMER in context.compressed_text
    assert "Portfolio Context" in context.compressed_text
    assert "000001" in context.compressed_text
    assert context.metadata["section_count"] >= 3


def test_context_compressor_preserves_financial_entities_under_budget():
    text = (
        "600519 在 2026-07-01 的新闻 chunk_abc123 显示收入增长 12.34%，"
        "组合金额 100,000.00 元，来源 src_001。" + " 长文本" * 300
    )

    compressed, facts, was_compressed = compress_text_preserving_facts(text, max_tokens=120)

    assert was_compressed is True
    assert "600519" in compressed
    assert "2026-07-01" in compressed
    assert "12.34%" in compressed
    assert "100,000.00" in compressed
    assert "chunk_abc123" in compressed
    assert "src_001" in compressed
    assert "600519" in facts["stock_codes"]


def test_context_builder_user_isolation_for_history_and_memory(tmp_path):
    output_dir, db_path = write_agent_fixture(tmp_path, user_id="u1", with_position=True)
    repo = AgentRepository(db_path)
    repo.upsert_conversation({"conversation_id": "conv_u1", "user_id": "u1", "title": "u1"})
    repo.upsert_conversation({"conversation_id": "conv_u2", "user_id": "u2", "title": "u2"})
    repo.upsert_message(
        {
            "message_id": "msg_u1",
            "conversation_id": "conv_u1",
            "user_id": "u1",
            "role": "user",
            "content": "只属于 u1 的 600519 偏好",
        }
    )
    repo.upsert_message(
        {
            "message_id": "msg_u2",
            "conversation_id": "conv_u2",
            "user_id": "u2",
            "role": "user",
            "content": "u2_secret_000002",
        }
    )
    repo.upsert_memory_item(
        {
            "memory_id": "mem_u1",
            "user_id": "u1",
            "memory_type": "long_term_preference",
            "content": "u1_memory_600519",
            "topics": ["portfolio"],
            "stock_codes": ["600519"],
        }
    )
    repo.upsert_memory_item(
        {
            "memory_id": "mem_u2",
            "user_id": "u2",
            "memory_type": "long_term_preference",
            "content": "u2_memory_000002",
            "topics": ["portfolio"],
            "stock_codes": ["000002"],
        }
    )

    context = build_agent_context(
        query="复盘 600519",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        session_id="conv_u1",
        run_id="run_1",
    )

    assert "u1_memory_600519" in context.compressed_text
    assert "只属于 u1" in context.compressed_text
    assert "u2_secret_000002" not in context.compressed_text
    assert "u2_memory_000002" not in context.compressed_text


def test_context_builder_includes_tool_result_and_evidence(tmp_path):
    output_dir, db_path = write_agent_fixture(tmp_path, user_id="u1")
    tool_result = {
        "success": True,
        "tool_name": "stock_news",
        "data": {
            "chunks": [
                {
                    "chunk_id": "chunk_001",
                    "source_id": "src_001",
                    "stock_code": "600519",
                    "publish_time": "2026-07-01",
                    "title": "业绩新闻",
                }
            ]
        },
    }

    context = build_agent_context(
        query="分析 600519 的新闻",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        run_id="run_2",
        phase="post_observation",
        tool_result=tool_result,
    )

    assert "Tool Results" in context.compressed_text
    assert "Evidence Context" in context.compressed_text
    assert "chunk_001" in context.compressed_text
    assert "src_001" in context.compressed_text
    assert "600519" in context.preserved_facts["stock_codes"]


def test_context_builder_respects_small_total_budget(tmp_path):
    output_dir, db_path = write_agent_fixture(tmp_path, user_id="u1", with_position=True)
    budget = ContextBudget(max_total_tokens=220, user_tokens=70, portfolio_tokens=80, business_tokens=70)

    context = build_agent_context(
        query="查看 000001 当前仓位和 2026-07-01 风险",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        run_id="run_small",
        budget=budget,
    )

    assert context.token_estimate <= 220
    assert "000001" in context.compressed_text


def test_executor_returns_and_persists_context_builder_summary(tmp_path):
    output_dir, db_path = write_agent_fixture(tmp_path, user_id="u1", with_position=True)

    result = run_agent_request(
        "查看当前模拟盘持仓",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        reply_language="zh",
    )

    assert result["success"] is True
    assert "pre_execution" in result["context"]
    assert "post_observation" in result["context"]
    assert result["context"]["pre_execution"]["token_estimate"] <= 1800
    assert "Portfolio Context" in result["context"]["pre_execution"]["compressed_text"]
    snapshot = load_run_snapshot(db_path, result["run_id"])
    metadata = snapshot["run"]["metadata_json"]
    assert "context_builder" in metadata
    assert metadata["context_builder"]["pre_execution"]["token_estimate"] <= 1800
    assert metadata["context_builder"]["post_observation"]["section_count"] >= 3
