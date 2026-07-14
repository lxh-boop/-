from __future__ import annotations

from contextlib import closing
import sqlite3
import re
from pathlib import Path

from config import AGENT_QUANT_DB_PATH


DATABASE_ROOT = Path(__file__).resolve().parent
MIGRATIONS_DIR = DATABASE_ROOT / "migrations"
ADD_COLUMN_RE = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?P<table>[A-Za-z_][A-Za-z0-9_]*)\s+ADD\s+COLUMN\s+(?P<column>[A-Za-z_][A-Za-z0-9_]*)\b",
    re.IGNORECASE,
)


def get_database_path(db_path: str | Path | None = None) -> Path:
    return Path(db_path or AGENT_QUANT_DB_PATH)


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = get_database_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _applied_migrations(conn: sqlite3.Connection) -> set[str]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {str(row["version"]) for row in rows}


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(str(row["name"]).lower() == column.lower() for row in rows)


def _execute_migration_sql(conn: sqlite3.Connection, sql: str) -> None:
    statements = [statement.strip() for statement in sql.split(";") if statement.strip()]
    for statement in statements:
        match = ADD_COLUMN_RE.match(statement)
        if match and _column_exists(conn, match.group("table"), match.group("column")):
            continue
        conn.execute(statement)


def initialize_database(db_path: str | Path | None = None) -> Path:
    path = get_database_path(db_path)
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        raise FileNotFoundError(f"no migration files found in {MIGRATIONS_DIR}")

    with closing(get_connection(path)) as conn:
        applied = _applied_migrations(conn)
        for migration_path in migration_files:
            version = migration_path.stem
            if version in applied:
                continue
            sql = migration_path.read_text(encoding="utf-8")
            _execute_migration_sql(conn, sql)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)",
                (version,),
            )
        conn.commit()
    return path
