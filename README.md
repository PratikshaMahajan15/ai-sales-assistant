# AI Sales Assistant

Ask business questions in plain English and get validated, read-only SQL, query results, charts and written reports. Built with Gemini, ClickHouse, Streamlit and Langfuse tracing.

This is a personal learning project, developed on my own to explore text-to-SQL with LLMs.

<img width="1920" height="647" alt="ask-question" src="https://github.com/user-attachments/assets/38e87cc4-697e-49bf-9108-34b1e5297b95" />


## What it does

- **Ask a Question tab:** type a question such as "Who are the top 10 customers by revenue?" or click an example. The app generates SQL, validates it, runs it on ClickHouse, then shows the answer with a table or chart (line, pie and more) chosen automatically, plus a short written summary.
- **Generate Report tab:** describe the report you need in plain English, for example "Top products, revenue by region, and delivery status". The app breaks the request into sections, runs a query for each one, and builds a titled report with commentary. Reports can be exported as PDF.
- **Schema-agnostic:** table and column names are discovered at runtime from ClickHouse system tables, so nothing about the database is hard-coded.

<img width="1920" height="597" alt="generate-report" src="https://github.com/user-attachments/assets/f1f612da-e6d6-4c8f-8817-e0bfe94e7409" />

## How it works

```
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
```

## Safety and reliability

- The model is instructed to produce **SELECT queries only**, and the output is checked by a SQL validator before execution.
- The app connects with a **read-only ClickHouse user** (see `setup_readonly_user.sql`).
- Table and column names used for sample-value lookups are validated against the live schema, which prevents SQL injection through identifiers.
- Gemini calls use **retry with backoff** to handle rate limits (`gemini_retry.py`).
- No credentials are stored in the code. Everything is read from environment variables.

## Sample outputs

These examples were generated from a **fictional dataset**.

- [Sample report (PDF)](docs/sample_report.pdf)
- [Monthly sales trend, line chart (PDF)](docs/sample_line_chart.pdf)
- [Revenue by region, pie chart (PDF)](docs/sample_pie_chart.pdf)

## Tech stack

Python, Streamlit, Google Gemini, ClickHouse, Plotly, ReportLab, Langfuse, sqlparse

## Project structure

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI (Ask a Question and Generate Report tabs) |
| `llm.py`, `gemini_retry.py` | Gemini client and retry logic |
| `prompt_builder.py`, `prompts/` | System prompt and prompt assembly |
| `schema.py` | Runtime schema discovery from ClickHouse |
| `sql_validator.py` | Pre-execution SQL checks |
| `executor.py`, `db.py` | Query execution and ClickHouse connection |
| `chart_generator.py` | Automatic chart selection and rendering |
| `report_generator.py` | Report planning, section queries and PDF export |
| `observability.py` | Langfuse tracing |
| `config.py` | Environment-based configuration |
| `demo/` | Synthetic demo data generator (optional) |
| `docs/` | Screenshots and sample outputs |

## Setup

1. Clone the repo and install dependencies:
   ```bash
   git clone https://github.com/PratikshaMahajan15/ai-sales-assistant.git
   cd ai-sales-assistant
   pip install -r requirements.txt
   ```
2. Create a read-only ClickHouse user with `setup_readonly_user.sql` (replace the placeholder password first).
3. Copy the example environment file and fill in your values:
   ```bash
   cp .env.example .env
   ```
   Required variables: `GEMINI_API_KEY`, `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`, `CLICKHOUSE_DATABASE`, plus `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_HOST` for tracing.
4. Run the app:
   ```bash
   streamlit run app.py
   ```

## Try it with demo data

No sales database? Generate a fictional one:

```bash
python demo/generate_demo_data.py --load
```

This creates a `sales_demo` database in a local ClickHouse (6 regions, 60 customers, 15 products, about 7,500 orders). Then set `CLICKHOUSE_DATABASE=sales_demo` in `.env` and start the app. Use a local ClickHouse instance, for example:

```bash
docker run -d --name clickhouse-demo -p 8123:8123 -e CLICKHOUSE_PASSWORD=demo123 clickhouse/clickhouse-server
```

Without `--load`, the script only writes CSV files to `demo/data/`.

## Limitations and next steps

- Accuracy has not yet been measured with an execution-based benchmark. Adding one (comparing result sets, not SQL strings) is the next planned step.
- Works best on schemas with clear, descriptive column names.
- Reports depend on the LLM correctly planning sections, so unusual requests may need rephrasing.

