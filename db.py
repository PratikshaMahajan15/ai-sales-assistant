import threading
import clickhouse_connect
from config import (
    CLICKHOUSE_HOST, CLICKHOUSE_PORT,
    CLICKHOUSE_USER, CLICKHOUSE_PASSWORD,
    CLICKHOUSE_DATABASE,
)

# Thread-local storage -- each thread gets its own ClickHouse client instance.
# This is required because report sections now run in parallel
# (ThreadPoolExecutor in report_generator.py), and ClickHouse's client does
# not support concurrent queries on a single shared client/session across
# threads -- doing so raises "Attempt to execute concurrent queries within
# the same session." A single global _client (the old approach) worked fine
# for sequential single-question use but breaks the moment multiple report
# sections query at the same time.
_thread_local = threading.local()


def get_client():
    """Return a read-only ClickHouse client, scoped to the current thread."""
    if not hasattr(_thread_local, "client"):
        _thread_local.client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            database=CLICKHOUSE_DATABASE,
            settings={
                "readonly": 1  # ClickHouse protocol-level read-only mode.
                               # Blocks INSERT, UPDATE, DELETE, DROP, ALTER
                               # at the server side -- not just in our code.
                               # Even if someone bypasses our SQL validator,
                               # ClickHouse itself will reject any write query.
            },
        )
    return _thread_local.client


def test_connection():
    """Quick connectivity check. Returns True if the DB is reachable."""
    try:
        result = get_client().query("SELECT 1")
        return result.result_rows == [(1,)]
    except Exception as exc:
        print(f"[db] Connection failed: {exc}")
        return False