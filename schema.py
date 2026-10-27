"""
Schema discovery -- reads metadata directly from ClickHouse.
Nothing is hardcoded: table names, column names, and data types
are all discovered at runtime from system.columns and system.tables.
"""

from db import get_client
from config import CLICKHOUSE_DATABASE


def get_tables() -> list[str]:
    """Return all table names in the configured database."""
    result = get_client().query(
        "SELECT name FROM system.tables WHERE database = %(db)s ORDER BY name",
        parameters={"db": CLICKHOUSE_DATABASE},
    )
    return [row[0] for row in result.result_rows]


def get_schema() -> dict[str, list[dict]]:
    """
    Return the full schema of the database as a dict:
    {
        "table_name": [
            {"column": "col_name", "type": "String"},
            ...
        ],
        ...
    }
    """
    result = get_client().query(
        """
        SELECT table, name, type
        FROM system.columns
        WHERE database = %(db)s
        ORDER BY table, position
        """,
        parameters={"db": CLICKHOUSE_DATABASE},
    )

    schema: dict[str, list[dict]] = {}
    for table, col_name, col_type in result.result_rows:
        schema.setdefault(table, []).append({"column": col_name, "type": col_type})

    return schema


def get_table_schema(table_name: str) -> list[dict]:
    """Return column metadata for a single table."""
    full = get_schema()
    return full.get(table_name, [])


def get_sample_values(table_name: str, column: str, limit: int = 5) -> list:
    """Fetch a few distinct values for a column to help the LLM understand the data."""
    # Only allow names that exist in the live schema (prevents SQL injection)
    schema = get_schema()
    if table_name not in schema or column not in [c["column"] for c in schema[table_name]]:
        return []
    try:
        result = get_client().query(
            f"SELECT DISTINCT `{column}` FROM `{table_name}` WHERE `{column}` IS NOT NULL LIMIT %(limit)s",
            parameters={"limit": limit},
        )
        return [row[0] for row in result.result_rows]
    except Exception:
        return []