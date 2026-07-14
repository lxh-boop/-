from database.connection import get_connection, initialize_database


def test_database_migration_removes_action_and_penalty_columns(tmp_path) -> None:
    db_path = tmp_path / "stage35.db"
    initialize_database(db_path)

    with get_connection(db_path) as conn:
        for table in ["agent_decision_log", "paper_order", "paper_decision_log"]:
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert "final_action" not in columns
            assert "risk_penalty" not in columns
            assert "rule_penalty" not in columns

