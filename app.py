"""
AI Sales Order Assistant — Clean conversational interface.
No SQL or technical details shown by default.
"""
import observability  # noqa: F401 -- sets up Langfuse tracing as a side effect, must be first

import inspect

import streamlit as st
from db import test_connection
from schema import get_schema, get_tables
from prompt_builder import build_prompt
from llm import generate_sql, generate_answer
from sql_validator import validate
from executor import execute, preview
from chart_generator import should_show_chart, generate_chart
from report_generator import generate_report_from_request, generate_pdf

st.set_page_config(page_title="AI Sales Assistant", layout="wide")


def safe_markdown_text(text: str) -> str:
    """
    Escapes $ so Streamlit's st.markdown doesn't interpret dollar amounts
    as LaTeX math delimiters (e.g. "$295.83 million" rendering as garbled
    italic math instead of a plain dollar figure). Apply this to any
    LLM-generated text before passing it to st.markdown().
    """
    return text.replace("$", "\\$")


def call_chart_fn(func, question, df):
    """
    Calls a chart_generator function with whatever arguments it actually
    accepts (question, df, or both), so a signature change in
    chart_generator.py can't crash the app with a TypeError.
    """
    df_names = {"df", "data", "dataframe", "result", "results"}
    params = list(inspect.signature(func).parameters)

    if len(params) >= 2:
        if params[0].lower() in df_names:
            return func(df, question)
        return func(question, df)
    if len(params) == 1:
        if params[0].lower() in df_names:
            return func(df)
        return func(question)
    return func()


# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("AI Sales Assistant")
    st.markdown("---")

    if test_connection():
        st.success("Database connected ✅")
        st.success("Read-only mode")
    else:
        st.error("Cannot connect — check .env")
        st.stop()

    st.subheader("Available Tables")
    for t in get_tables():
        st.code(t)

    # Load the schema once, outside the expander, so it is always
    # available for SQL validation below.
    schema = get_schema()

    with st.expander("Schema Explorer"):
        for table, cols in schema.items():
            st.markdown(f"**{table}** ({len(cols)} columns)")
            for c in cols:
                st.text(f"  {c['column']}  ({c['type']})")

# ── Main ───────────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["Ask a Question", "Generate Report"])

# ══════════════════════════════════════════════════════════════════════════
# TAB 1 — Conversational Q&A
# ══════════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown("## Ask anything about your sales data")
    st.caption("Get instant answers in plain English. Charts and tables show automatically when they help.")

    if "question_text" not in st.session_state:
        st.session_state.question_text = ""

    examples = [
        "What is the total revenue?",
        "Who are the top 10 customers by revenue?",
        "Show monthly sales trend as line chart",
        "Which products generate the highest revenue?",
        "What is the delivery completion rate?",
        "Show revenue by region as pie chart",
        "How many orders are pending delivery?",
        "Which customers placed the most orders?",
    ]
    cols = st.columns(4)
    for i, q in enumerate(examples):
        if cols[i % 4].button(q, key=f"ex_{i}"):
            st.session_state.question_text = q

    question = st.text_input(
        "",
        key="question_text",  # bound to session_state, survives reruns
        placeholder="Ask a business question...",
        label_visibility="collapsed",
    )

    if question:
        with st.spinner("Thinking..."):
            try:
                prompt = build_prompt(question)
                sql = generate_sql(prompt)

                # FIX: validate() needs both the SQL and the schema
                is_valid, reason = validate(sql, schema)
                if not is_valid:
                    st.error(f"Could not answer: {reason}")
                    st.stop()

                df = execute(sql)
                answer = generate_answer(question, sql, preview(df))

            except Exception as exc:
                st.error(f"Something went wrong: {exc}")
                st.stop()

        st.markdown("---")
        st.markdown(f"### {safe_markdown_text(answer)}")

        # Chart only if the question explicitly asked for one; otherwise
        # the table shows instead. Never both, to avoid visual clutter.
        if call_chart_fn(should_show_chart, question, df) and not df.empty:
            fig = call_chart_fn(generate_chart, question, df)
            if fig:
                st.plotly_chart(fig, use_container_width=True)
                st.caption(f"🔍 debug — columns: {df.columns.tolist()}")  # TEMPORARY, remove after debugging
            elif len(df) > 1:
                st.dataframe(df, use_container_width=True, hide_index=True)
        elif not df.empty and len(df) > 1:
            st.dataframe(df, use_container_width=True, hide_index=True)

        with st.expander("Show SQL"):
            st.code(sql, language="sql")

# ══════════════════════════════════════════════════════════════════════════
# TAB 2 — Custom Report
# ══════════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("## Generate a custom report")
    st.caption(
        "Describe the report you need — e.g. \"top customers, top products, "
        "and delivery status\" — and it'll be broken into sections automatically."
    )

    if "report_request_text" not in st.session_state:
        st.session_state.report_request_text = ""

    report_examples = [
        "Revenue overview and top 10 customers",
        "Top products, revenue by region, and delivery status",
        "Monthly sales trend and pending orders",
    ]
    rcols = st.columns(3)
    for i, ex in enumerate(report_examples):
        if rcols[i].button(ex, key=f"rex_{i}"):
            st.session_state.report_request_text = ex

    report_request = st.text_area(
        "",
        key="report_request_text",  # bound to session_state, survives reruns
        placeholder="Describe the report you need...",
        label_visibility="collapsed",
        height=80,
    )

    if st.button("Generate Report", type="primary") and report_request.strip():
        with st.spinner("Planning and building your report..."):
            try:
                title, sections = generate_report_from_request(report_request.strip())
            except Exception as exc:
                st.error(f"Could not build this report: {exc}")
                st.stop()

        st.markdown(f"## {title}")

        for result in sections:
            st.markdown(f"### {result['title']}")
            if result.get("error"):
                st.warning(result["error"])
            else:
                if result.get("explanation"):
                    st.markdown(safe_markdown_text(result["explanation"]))

                display_mode = result.get("display_mode", "table")

                if display_mode == "kpi" and result.get("kpis"):
                    kpi_cols = st.columns(len(result["kpis"]))
                    for col, kpi in zip(kpi_cols, result["kpis"]):
                        col.metric(kpi["label"], kpi["value"])
                elif display_mode == "chart" and result.get("chart_fig"):
                    st.plotly_chart(result["chart_fig"], use_container_width=True)
                else:
                    df = result.get("df")
                    if df is not None and not df.empty:
                        st.dataframe(df, use_container_width=True, hide_index=True)
            st.divider()

        try:
            pdf_bytes = generate_pdf(title, sections)
            import datetime
            st.download_button(
                label="⬇️ Download Report (PDF)",
                data=pdf_bytes,
                file_name=f"{title.lower().replace(' ', '_')}_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                mime="application/pdf",
            )
        except Exception as exc:
            st.warning(f"PDF generation failed: {exc}")