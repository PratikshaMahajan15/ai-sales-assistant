AI Sales Assistant

Ask business questions in plain English and get validated, read-only SQL, query results, charts and written reports. Built with Gemini, ClickHouse, Streamlit and Langfuse tracing.

<!-- TODO: add a screenshot or GIF here, e.g. ![Demo](docs/demo.gif) -->
What it does
Q&A tab: type a question such as "Top 10 customers by revenue". The app generates SQL, validates it, runs it on ClickHouse, then shows the table, an automatically chosen chart and a short written summary.
Report tab: describe the report you need in plain English (for example "Monthly sales trend and pending orders"). The app plans the sections, runs the queries for each one and assembles a titled report with charts and commentary. Reports can be exported as PDF.
Schema-agnostic: table and column names are discovered at runtime from ClickHouse system tables, so nothing about the database is hard-coded.
How it works

Question
   |
   v
Prompt builder (live schema + rules)
   |
   v
Gemini  -->  SQL
   |
   v
SQL validator (checks the query before it runs)
   |
   v
ClickHouse (read-only user)
   |
   v
Results --> chart selection --> summary / report --> Streamlit UI (+ PDF export)

Every LLM call is traced in Langfuse.

Safety and reliability

The model is instructed to produce SELECT queries only, and the output is checked by a SQL validator before execution.
The app connects with a read-only ClickHouse user (see setup_readonly_user.sql).
Table and column names used for sample-value lookups are validated against the live schema, which prevents SQL injection through identifiers.
Gemini calls use retry with backoff to handle rate limits (gemini_retry.py).
No credentials are stored in the code. Everything is read from environment variables.
Tech stack

Python, Streamlit, Google Gemini, ClickHouse, Plotly, ReportLab, Langfuse, sqlparse

Project structure
File	Purpose
app.py	Streamlit UI (Q&A and Report tabs)
llm.py, gemini_retry.py	Gemini client and retry logic
prompt_builder.py, prompts/	System prompt and prompt assembly
schema.py	Runtime schema discovery from ClickHouse
sql_validator.py	Pre-execution SQL checks
executor.py, db.py	Query execution and ClickHouse connection
chart_generator.py	Automatic chart selection and rendering
report_generator.py	Report planning, section queries and PDF export
observability.py	Langfuse tracing
config.py	Environment-based configuration
Setup
Clone the repo and install dependencies:
bash
   git clone https://github.com/PratikshaMahajan15/ai-sales-assistant.git
   cd ai-sales-assistant
   pip install -r requirements.txt
Create a read-only ClickHouse user with setup_readonly_user.sql (replace the placeholder password first).
Copy the example environment file and fill in your values:
bash
   cp .env.example .env

Required variables: GEMINI_API_KEY, CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_USER, CLICKHOUSE_PASSWORD, CLICKHOUSE_DATABASE, plus LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_HOST for tracing. 4. Run the app:

bash
   streamlit run app.py
Example
<!-- TODO: replace with a real example from your demo data -->

Question: Top 10 customers by revenue

Generated SQL:

sql
-- paste an example query here

Output: table + bar chart + short summary

Limitations and next steps
Accuracy has not yet been measured with an execution-based benchmark. Adding one (comparing result sets, not SQL strings) is the next planned step.
Works best on schemas with clear, descriptive column names.
Reports depend on the LLM correctly planning sections, so unusual requests may need rephrasing.

