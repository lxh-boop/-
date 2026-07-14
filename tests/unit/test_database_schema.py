from __future__ import annotations

import sqlite3

from database.connection import initialize_database
from database.table_registry import CORE_TABLES


def test_database_initializes_all_core_tables(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"

    created = initialize_database(db_path)

    assert created == db_path
    assert db_path.exists()

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()

    table_names = {row[0] for row in rows}
    assert set(CORE_TABLES).issubset(table_names)
    assert "schema_migrations" in table_names


def test_schema_has_evidence_and_retention_columns(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    initialize_database(db_path)

    with sqlite3.connect(db_path) as conn:
        news_event_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(news_event)").fetchall()
        }
        news_chunk_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(news_chunk)").fetchall()
        }
        decision_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(agent_decision_log)").fetchall()
        }

    assert {"raw_file_path", "archive_file_path", "retention_level", "expire_at"}.issubset(
        news_event_cols
    )
    assert {"used_in_decision", "retrieval_count", "retention_level", "expire_at"}.issubset(
        news_chunk_cols
    )
    assert {"evidence_chunk_ids", "evidence_snapshot", "retrieval_id"}.issubset(
        decision_cols
    )


def test_schema_has_scheduler_execution_columns(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    initialize_database(db_path)

    with sqlite3.connect(db_path) as conn:
        user_profile_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(user_profile)").fetchall()
        }
        agent_decision_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(agent_decision_log)").fetchall()
        }

    assert "is_active" in user_profile_cols
    assert {"job_id", "run_id", "execution_source"}.issubset(agent_decision_cols)


def test_schema_has_paper_cash_flow_and_capital_metrics(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    initialize_database(db_path)

    with sqlite3.connect(db_path) as conn:
        cash_flow_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(paper_cash_flow)").fetchall()
        }
        account_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(paper_account)").fetchall()
        }

    assert {
        "cash_flow_id",
        "user_id",
        "effective_date",
        "flow_type",
        "amount",
        "status",
        "source",
        "idempotency_key",
    }.issubset(cash_flow_cols)
    assert {
        "cumulative_deposit",
        "cumulative_withdrawal",
        "net_contribution",
        "absolute_profit",
        "time_weighted_return",
    }.issubset(account_cols)
