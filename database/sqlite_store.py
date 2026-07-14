from __future__ import annotations

from contextlib import closing
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from database.connection import get_connection, initialize_database
from database.table_registry import primary_key_for


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
T = TypeVar("T")


def quote_identifier(identifier: str) -> str:
    if not IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"unsafe SQL identifier: {identifier}")
    return f'"{identifier}"'


def row_to_dict(row) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def is_sqlite_lock_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return isinstance(exc, sqlite3.OperationalError) and ("database is locked" in message or "database is busy" in message)


def run_with_sqlite_lock_retry(
    operation: Callable[[], T],
    *,
    max_attempts: int = 4,
    base_delay_seconds: float = 0.05,
) -> T:
    last_error: BaseException | None = None
    for attempt in range(max(1, int(max_attempts))):
        try:
            return operation()
        except BaseException as exc:
            if not is_sqlite_lock_error(exc) or attempt >= max_attempts - 1:
                raise
            last_error = exc
            time.sleep(base_delay_seconds * (2 ** attempt))
    raise RuntimeError(f"sqlite_retry_exhausted:{last_error}")


class SQLiteStore:
    def __init__(self, db_path: str | Path | None = None, initialize: bool = True):
        self.db_path = initialize_database(db_path) if initialize else Path(db_path)

    def insert(self, table: str, record: dict[str, Any], replace: bool = False) -> dict[str, Any]:
        if not record:
            raise ValueError("record cannot be empty")

        table_sql = quote_identifier(table)
        columns = list(record)
        column_sql = ", ".join(quote_identifier(col) for col in columns)
        placeholders = ", ".join(f":{col}" for col in columns)
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        sql = f"{verb} INTO {table_sql} ({column_sql}) VALUES ({placeholders})"

        def operation() -> None:
            with closing(get_connection(self.db_path)) as conn:
                conn.execute(sql, record)
                conn.commit()
        run_with_sqlite_lock_retry(operation)
        return record

    def upsert(self, table: str, record: dict[str, Any]) -> dict[str, Any]:
        pk_columns = primary_key_for(table)
        if not all(col in record for col in pk_columns):
            raise ValueError(f"upsert into {table} requires primary keys: {pk_columns}")

        columns = list(record)
        table_sql = quote_identifier(table)
        column_sql = ", ".join(quote_identifier(col) for col in columns)
        placeholders = ", ".join(f":{col}" for col in columns)
        conflict_sql = ", ".join(quote_identifier(col) for col in pk_columns)
        update_columns = [col for col in columns if col not in pk_columns]

        if update_columns:
            update_sql = ", ".join(
                f"{quote_identifier(col)}=excluded.{quote_identifier(col)}"
                for col in update_columns
            )
            sql = (
                f"INSERT INTO {table_sql} ({column_sql}) VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict_sql}) DO UPDATE SET {update_sql}"
            )
        else:
            sql = (
                f"INSERT INTO {table_sql} ({column_sql}) VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict_sql}) DO NOTHING"
            )

        def operation() -> None:
            with closing(get_connection(self.db_path)) as conn:
                conn.execute(sql, record)
                conn.commit()
        run_with_sqlite_lock_retry(operation)
        return record

    def get(self, table: str, key: dict[str, Any]) -> dict[str, Any] | None:
        if not key:
            raise ValueError("key cannot be empty")
        where_sql = " AND ".join(f"{quote_identifier(col)}=:{col}" for col in key)
        sql = f"SELECT * FROM {quote_identifier(table)} WHERE {where_sql} LIMIT 1"
        def operation() -> dict[str, Any] | None:
            with closing(get_connection(self.db_path)) as conn:
                return row_to_dict(conn.execute(sql, key).fetchone())
        return run_with_sqlite_lock_retry(operation)

    def list(
        self,
        table: str,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        descending: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        filters = filters or {}
        sql = f"SELECT * FROM {quote_identifier(table)}"
        params: dict[str, Any] = dict(filters)
        if filters:
            where_sql = " AND ".join(f"{quote_identifier(col)}=:{col}" for col in filters)
            sql += f" WHERE {where_sql}"
        if order_by:
            sql += f" ORDER BY {quote_identifier(order_by)}"
            if descending:
                sql += " DESC"
        if limit is not None:
            params["_limit"] = int(limit)
            sql += " LIMIT :_limit"
        if offset is not None:
            params["_offset"] = int(offset)
            sql += " OFFSET :_offset"
        def operation() -> list[dict[str, Any]]:
            with closing(get_connection(self.db_path)) as conn:
                return [dict(row) for row in conn.execute(sql, params).fetchall()]
        return run_with_sqlite_lock_retry(operation)

    def list_by_values(
        self,
        table: str,
        column: str,
        values: list[Any],
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        descending: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if not values:
            return []
        filters = filters or {}
        params: dict[str, Any] = dict(filters)
        value_placeholders = []
        for index, value in enumerate(values):
            key = f"_value_{index}"
            params[key] = value
            value_placeholders.append(f":{key}")
        predicates = [f"{quote_identifier(column)} IN ({', '.join(value_placeholders)})"]
        predicates.extend(f"{quote_identifier(col)}=:{col}" for col in filters)
        sql = f"SELECT * FROM {quote_identifier(table)} WHERE {' AND '.join(predicates)}"
        if order_by:
            sql += f" ORDER BY {quote_identifier(order_by)}"
            if descending:
                sql += " DESC"
        if limit is not None:
            params["_limit"] = int(limit)
            sql += " LIMIT :_limit"
        def operation() -> list[dict[str, Any]]:
            with closing(get_connection(self.db_path)) as conn:
                return [dict(row) for row in conn.execute(sql, params).fetchall()]
        return run_with_sqlite_lock_retry(operation)

    def update(self, table: str, key: dict[str, Any], changes: dict[str, Any]) -> int:
        if not key:
            raise ValueError("key cannot be empty")
        if not changes:
            return 0

        params = {**{f"set_{k}": v for k, v in changes.items()}, **{f"key_{k}": v for k, v in key.items()}}
        set_sql = ", ".join(f"{quote_identifier(col)}=:set_{col}" for col in changes)
        where_sql = " AND ".join(f"{quote_identifier(col)}=:key_{col}" for col in key)
        sql = f"UPDATE {quote_identifier(table)} SET {set_sql} WHERE {where_sql}"
        def operation() -> int:
            with closing(get_connection(self.db_path)) as conn:
                cur = conn.execute(sql, params)
                conn.commit()
                return int(cur.rowcount)
        return run_with_sqlite_lock_retry(operation)
