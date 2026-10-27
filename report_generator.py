"""
Report Generator — plans and builds a report from a free-text request
(e.g. "give me a report on top customers, products, and delivery status")
instead of a fixed section list. Uses Gemini to break the request into
sections, then runs each one through the normal question -> SQL -> answer
pipeline.
"""

import io
import json
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.enums import TA_CENTER
import plotly.io as pio
from datetime import datetime

from google import genai
from langfuse import observe
from config import GEMINI_API_KEY
from gemini_retry import call_gemini

from prompt_builder import get_schema_context, _load_system_prompt
from llm import generate_sql, generate_answer
from schema import get_schema
from sql_validator import validate
from executor import execute, preview
from chart_generator import generate_chart, decide_report_display, build_kpi_cards, CHART_COLORS

_client = genai.Client(api_key=GEMINI_API_KEY)
_MODEL = "gemini-3.5-flash"
_FALLBACKS = ["gemini-3.5-flash-lite"]

# Build once, reuse for all report sections in a session
_CACHED_PROMPT_PREFIX = None


def _get_prompt_prefix() -> str:
    global _CACHED_PROMPT_PREFIX
    if _CACHED_PROMPT_PREFIX is None:
        _CACHED_PROMPT_PREFIX = f"{_load_system_prompt()}\n\n=== SCHEMA ===\n{get_schema_context()}\n=== END SCHEMA ===\n\nQuestion: "
    return _CACHED_PROMPT_PREFIX


_PLANNER_INSTRUCTIONS = """You turn a business report request into a structured plan.

Break the request into distinct, independently-answerable sections. A request
covering multiple topics (e.g. "top customers, products, and delivery status")
becomes one section per topic. A request about a single topic gets one section.

For any ranking-style section (top customers, top products, best performing
regions, etc.) where the user didn't specify a number, phrase the section's
question with an explicit reasonable limit -- default to "top 10" -- so the
generated SQL naturally includes a LIMIT instead of returning every row.

For each section, suggest a chart type if one would help: "bar", "line", or
"pie". Use "line" for anything time-based (trends, monthly, over time), "pie"
only for a small number of categories that sum to a meaningful whole (e.g.
revenue share by region), and "bar" as the default for rankings and
comparisons. This is just a suggestion -- the app decides on its own,
based on the question wording, whether a chart is shown at all.

Respond with ONLY valid JSON, no markdown fences, matching this shape:
{
  "title": "Short report title",
  "sections": [
    {"title": "Short section heading", "question": "Fully self-contained question", "chart_type": "bar"}
  ]
}

Each section's "question" must be a complete, standalone question -- it will
be sent independently with no other context, so do not use pronouns or refer
to other sections.

User's report request: """


class PlanningError(Exception):
    pass

@observe(name="plan_report")
def plan_report(request_text: str) -> dict:
    prompt = _PLANNER_INSTRUCTIONS + request_text
    response = call_gemini(_client, _MODEL, prompt, fallback_models=_FALLBACKS)
    raw = response.text.strip()

    if raw.startswith("```"):
        raw = "\n".join(l for l in raw.split("\n") if not l.strip().startswith("```")).strip()

    try:
        plan = json.loads(raw)
    except json.JSONDecodeError as e:
        raise PlanningError(f"Could not plan this report: {e}")

    if not plan.get("sections"):
        raise PlanningError("No sections were generated for this request.")

    plan.setdefault("title", "Business Report")
    return plan


@observe(name="run_report_section")
def run_section(section: dict, color_index: int = 0) -> dict:
    question = section["question"]
    result = {"title": section.get("title", question), "question": question,
              "sql": None, "df": pd.DataFrame(), "explanation": "",
              "chart_fig": None, "kpis": None, "display_mode": "table", "error": None}
    try:
        sql = generate_sql(_get_prompt_prefix() + question + "\nSQL:")
        result["sql"] = sql

        # FIX: validate() needs both the SQL and the schema
        is_valid, reason = validate(sql, get_schema())
        if not is_valid:
            result["error"] = reason
            return result
        df = execute(sql)
        result["df"] = df
        result["explanation"] = generate_answer(question, sql, preview(df))

        # Reports auto-pick the best display per section's data shape --
        # single aggregate -> KPI cards, multi-row comparison -> chart,
        # otherwise -> table as a fallback. Unlike the single-question tab,
        # reports don't wait for chart-related keywords in the question.
        display_mode = decide_report_display(df)
        result["display_mode"] = display_mode

        if display_mode == "kpi":
            result["kpis"] = build_kpi_cards(df)
        elif display_mode == "chart":
            result["chart_fig"] = generate_chart(
                df, question, chart_type=section.get("chart_type"), color_index=color_index
            )
    except Exception as exc:
        result["error"] = str(exc)
    return result


def generate_report_from_request(request_text: str) -> tuple[str, list[dict]]:
    """
    Main entry point: plans the report from free text, then runs every
    section IN PARALLEL (sections are fully independent -- one doesn't need
    another's result), rather than one at a time. This is what makes report
    generation fast -- each section involves multiple Gemini calls plus a
    ClickHouse query, so running 4 sections sequentially could take as long
    as 4x a single slow section; running them in parallel takes roughly as
    long as the single slowest section.

    Returns (title, sections) in the ORIGINAL planned order regardless of
    which section finishes first -- a failed section is included with an
    error note rather than aborting the whole report.
    """
    plan = plan_report(request_text)
    section_specs = list(enumerate(plan["sections"]))

    with ThreadPoolExecutor(max_workers=min(len(section_specs), 5)) as executor:
        futures = [
            executor.submit(run_section, section, color_index)
            for color_index, section in section_specs
        ]
        sections = [f.result() for f in futures]

    return plan["title"], sections


def _fig_to_image_bytes(fig) -> bytes | None:
    try:
        return pio.to_image(fig, format="png", width=700, height=350, scale=2)
    except Exception:
        return None


def generate_pdf(title: str, sections: list[dict]) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    title_style  = ParagraphStyle("T", fontSize=20, fontName="Helvetica-Bold",
                                  textColor=colors.HexColor("#0F6E56"), spaceAfter=6, alignment=TA_CENTER)
    sub_style    = ParagraphStyle("S", fontSize=10, textColor=colors.HexColor("#5F5E5A"),
                                  spaceAfter=20, alignment=TA_CENTER)
    section_style = ParagraphStyle("H", fontSize=14, fontName="Helvetica-Bold",
                                   spaceBefore=16, spaceAfter=8)
    body_style   = ParagraphStyle("B", fontSize=10, leading=14, spaceAfter=8)

    story = [
        Paragraph(title, title_style),
        Paragraph(f"Generated {datetime.now().strftime('%d %B %Y, %H:%M')}", sub_style),
        Spacer(1, 0.3*cm),
    ]

    for sec in sections:
        story.append(Paragraph(sec["title"], section_style))
        if sec.get("error"):
            story.append(Paragraph(f"Error: {sec['error']}", body_style))
        else:
            if sec.get("explanation"):
                story.append(Paragraph(sec["explanation"], body_style))

            if sec.get("display_mode") == "kpi" and sec.get("kpis"):
                kpi_rows = [[k["label"], k["value"]] for k in sec["kpis"]]
                kpi_table = Table(kpi_rows, hAlign="LEFT", colWidths=[6*cm, 4*cm])
                kpi_table.setStyle(TableStyle([
                    ("FONTSIZE", (0, 0), (-1, -1), 11),
                    ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                    ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#0F6E56")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]))
                story.append(kpi_table)
            elif sec.get("chart_fig"):
                img_bytes = _fig_to_image_bytes(sec["chart_fig"])
                if img_bytes:
                    story.append(Image(io.BytesIO(img_bytes), width=16*cm, height=8*cm))
            else:
                df = sec.get("df", pd.DataFrame())
                if not df.empty:
                    td = [list(df.columns)] + [[str(c)[:25] for c in r] for r in df.head(8).values.tolist()]
                    t = Table(td, repeatRows=1)
                    t.setStyle(TableStyle([
                        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0F6E56")),
                        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
                        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
                        ("FONTSIZE",   (0,0), (-1,-1), 8),
                        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F1EFE8")]),
                        ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#E0DDD4")),
                        ("PADDING",    (0,0), (-1,-1), 4),
                    ]))
                    story.append(t)
        story.append(Spacer(1, 0.4*cm))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()