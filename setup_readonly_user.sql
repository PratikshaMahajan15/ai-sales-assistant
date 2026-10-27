-- Run this once, as a ClickHouse admin, BEFORE running the app.
-- This creates the account the app connects with (CLICKHOUSE_USER in .env).
-- Do NOT use your admin/default user for the app.

CREATE USER IF NOT EXISTS ai_reader
IDENTIFIED BY 'CHANGE_ME_STRONG_PASSWORD'
SETTINGS readonly = 1, max_execution_time = 30, max_rows_to_read = 5000000;

-- Grant SELECT only, scoped to the sales mart database.
-- No INSERT / ALTER / DROP / CREATE / TRUNCATE grants exist for this user at all.
GRANT SELECT ON JTC_sap_sales_mart.* TO ai_reader;

-- Verify: this user should NOT be able to run the statement below.
-- (Run as ai_reader to confirm it's rejected.)
-- INSERT INTO JTC_sap_sales_mart.sales_final_dataset VALUES (...);
