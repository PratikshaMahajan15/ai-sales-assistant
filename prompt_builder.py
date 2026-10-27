"""
Builds the LLM prompt efficiently.
Schema is cached after the first call -- not rebuilt on every question.
Sample data is one value per column, not full rows.
"""

from pathlib import Path
from schema import get_schema
from db import get_client
from config import CLICKHOUSE_DATABASE

# Module-level cache -- schema is fetched once and reused
_schema_context_cache: str | None = None


def _load_system_prompt() -> str:
    path = Path(__file__).parent / "prompts" / "system_prompt.txt"
    return path.read_text(encoding="utf-8")


def _one_example_per_column(table: str, columns: list[dict]) -> str:
    """
    Fetch one row and show one real value per column.
    Far cheaper than 5 full rows for a 50-column table.
    """
    try:
        col_names = ", ".join(c["column"] for c in columns[:20])  # cap at 20 cols
        result = get_client().query(
            f"SELECT {col_names} FROM {table} LIMIT 1"
        )
        if not result.result_rows:
            return "  (no data)"
        row = result.result_rows[0]
        names = result.column_names
        lines = [f"  {n}: {v}" for n, v in zip(names, row)]
        return "\n".join(lines)
    except Exception:
        return "  (sample not available)"


def _build_schema_context() -> str:
    """Build compact schema context. Called once, then cached."""
    schema = get_schema()
    lines = [f"Database: {CLICKHOUSE_DATABASE}\n"]

    for table, columns in schema.items():
        lines.append(f"Table: {table} ({len(columns)} columns)")
        # Column names + types only -- no verbose descriptions
        for col in columns:
            lines.append(f"  {col['column']} ({col['type']})")
        # One example row -- much cheaper than 5 full rows
        lines.append("Example values:")
        lines.append(_one_example_per_column(table, columns))
        lines.append("")

    return "\n".join(lines)


def get_schema_context() -> str:
    """Return cached schema context, building it only on first call."""
    global _schema_context_cache
    if _schema_context_cache is None:
        _schema_context_cache = _build_schema_context()
    return _schema_context_cache


def build_prompt(user_question: str) -> str:
    """Assemble the full prompt: system + cached schema + question."""
    system_prompt = _load_system_prompt()
    schema_context = get_schema_context()

    return f"""{system_prompt}

=== SCHEMA ===
{schema_context}
=== END SCHEMA ===

Question: {user_question}
SQL:"""