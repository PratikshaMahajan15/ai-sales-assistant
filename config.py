import os
from dotenv import load_dotenv 
load_dotenv(override=True)
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST")
CLICKHOUSE_PORT = os.getenv("CLICKHOUSE_PORT")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Safety limits (defense-in-depth, on top of the read-only DB user)
MAX_ROWS_RETURNED = 200
QUERY_TIMEOUT_SECONDS = 30

