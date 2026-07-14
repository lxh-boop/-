import sqlite3

from database.connection import initialize_database


def test_migrations_skip_existing_decision_time_column(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    initialize_database(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM schema_migrations WHERE version = ?", ("002_rag_retrieval_fields",))
        conn.commit()

    initialize_database(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("PRAGMA table_info(rag_retrieval_log)").fetchall()
        columns = [row[1] for row in rows]
        assert columns.count("decision_time") == 1
        applied = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?",
            ("002_rag_retrieval_fields",),
        ).fetchone()
        assert applied is not None
