from __future__ import annotations

from database.connection import get_connection, initialize_database


def test_strategy_binding_schema_contains_scope_and_lineage(tmp_path) -> None:
    db_path = initialize_database(tmp_path / "agent_quant.db")
    with get_connection(db_path) as connection:
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(strategy_bindings)"
            ).fetchall()
        }
        indexes = {
            row["name"]
            for row in connection.execute(
                "PRAGMA index_list(strategy_bindings)"
            ).fetchall()
        }

    assert {
        "binding_id",
        "user_id",
        "account_id",
        "strategy_id",
        "strategy_version",
        "config_hash",
        "effective_from",
        "status",
        "previous_binding_id",
        "source_plan_id",
        "created_at",
        "activated_at",
        "disabled_at",
    } <= columns
    assert "uq_strategy_bindings_active_account" in indexes
