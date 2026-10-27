
import re
import sqlparse

FORBIDDEN_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE",
    "CREATE", "GRANT", "REVOKE", "ATTACH", "DETACH", "RENAME",
    "OPTIMIZE", "SYSTEM", "KILL", "EXCHANGE", "REPLACE",
}


class ValidationError(Exception):
    pass


def _extract_identifiers(sql: str) -> set:
    """
    Extract SQL identifiers using sqlparse.
    This is a lightweight safety check, not a full SQL parser.
    """
    parsed = sqlparse.parse(sql)
    if not parsed:
        return set()

    tokens = []

    for statement in parsed:
        for tok in statement.flatten():
            if tok.ttype in sqlparse.tokens.Name:
                tokens.append(str(tok.value))

    return set(tokens)


def validate_sql(sql: str, schema: dict) -> tuple[bool, str]:
    """
    Validate a read-only SQL query against the supplied schema.

    Returns:
        (True, "") if valid
        (False, error_message) if invalid
    """
    if not sql or not sql.strip():
        return False, "Empty SQL generated."

    if sql.strip().upper().startswith("NO_QUERY"):
        return False, sql.strip()

    # Allow exactly one SQL statement.
    statements = [
        statement
        for statement in sqlparse.parse(sql)
        if str(statement).strip()
    ]

    if len(statements) != 1:
        return False, "Only a single SQL statement is allowed."

    # Remove comments before checking SQL structure.
    cleaned_sql = sqlparse.format(
        sql,
        strip_comments=True
    ).strip()

    if not re.match(r"^\s*SELECT\b", cleaned_sql, re.IGNORECASE):
        return False, "Only SELECT statements are allowed."

    # Check forbidden keywords.
    # This is a basic check; a read-only database user is still essential.
    for word in FORBIDDEN_KEYWORDS:
        if re.search(
            rf"\b{word}\b",
            cleaned_sql,
            re.IGNORECASE
        ):
            return False, f"Forbidden keyword detected: {word}"

    # Collect valid table and column names from the schema.
    valid_tables = set(schema.keys())
    valid_columns = set()

    for columns in schema.values():
        for column in columns:
            if isinstance(column, dict) and "column" in column:
                valid_columns.add(column["column"])

    # Find tables referenced after FROM and JOIN.
    from_join_tables = re.findall(
        r"\b(?:FROM|JOIN)\s+"
        r"([a-zA-Z_][a-zA-Z0-9_.]*)",
        cleaned_sql,
        re.IGNORECASE
    )

    if not from_join_tables:
        return False, "No table referenced in query."

    for table_name in from_join_tables:
        # Support schema-qualified table names.
        table_parts = table_name.split(".")
        table = table_parts[-1]

        if table not in valid_tables and table_name not in valid_tables:
            return False, f"Unknown table referenced: {table_name}"

    # Check identifiers against known columns and tables.
    identifiers = _extract_identifiers(cleaned_sql)

    sql_keywords_and_funcs = {
        "SELECT", "FROM", "WHERE", "GROUP", "BY", "ORDER",
        "LIMIT", "AS", "AND", "OR", "NOT", "IN", "IS",
        "NULL", "JOIN", "INNER", "LEFT", "RIGHT", "OUTER",
        "ON", "DESC", "ASC", "SUM", "COUNT", "AVG", "MIN",
        "MAX", "DISTINCT", "HAVING", "BETWEEN", "LIKE",
        "CASE", "WHEN", "THEN", "ELSE", "END", "TOP",
        "TRUE", "FALSE", "UNION", "ALL", "EXISTS",
        "WITH", "OVER", "PARTITION", "ROWS", "CURRENT",
        "ROW", "PRECEDING", "FOLLOWING", "INTERVAL",
        "DATE", "YEAR", "MONTH", "QUARTER",
    }

    # Get aliases declared with AS.
    aliases = set(
        re.findall(
            r"\bAS\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            cleaned_sql,
            re.IGNORECASE
        )
    )

    unknown = []

    for identifier in identifiers:
        upper_identifier = identifier.upper()

        if upper_identifier in sql_keywords_and_funcs:
            continue

        if identifier in valid_tables or identifier in valid_columns:
            continue

        if identifier in aliases:
            continue

        if identifier.isdigit():
            continue

        # Allow common table aliases, e.g. s.column_name.
        if re.search(
            rf"\b{re.escape(identifier)}\s*\.",
            cleaned_sql
        ):
            continue

        unknown.append(identifier)

    if unknown:
        return (
            False,
            "Unknown column(s) or identifier(s) referenced: "
            + ", ".join(sorted(set(unknown)))
        )

    return True, ""


def validate(sql: str, schema: dict) -> tuple[bool, str]:
    """
    Compatibility wrapper for app.py.

    Allows:
        from sql_validator import validate

    Returns:
        (is_valid, error_message)
    """
    return validate_sql(sql, schema)


def enforce_limit(sql: str, max_rows: int) -> str:
    """
    Add a LIMIT if missing, or cap an existing LIMIT.
    """
    if max_rows < 1:
        raise ValueError("max_rows must be at least 1.")

    sql = sql.strip().rstrip(";")

    match = re.search(
        r"\bLIMIT\s+(\d+)\b",
        sql,
        re.IGNORECASE
    )

    if match:
        existing_limit = int(match.group(1))

        if existing_limit > max_rows:
            sql = (
                sql[:match.start(1)]
                + str(max_rows)
                + sql[match.end(1):]
            )

        return sql

    return f"{sql} LIMIT {max_rows}"
