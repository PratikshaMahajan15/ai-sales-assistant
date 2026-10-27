"""
Chart Generator
Detects if the user wants a chart, picks the right chart type,
and generates a Plotly figure from the query result.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google import genai
from config import GEMINI_API_KEY

_client = genai.Client(api_key=GEMINI_API_KEY)
_MODEL = "gemini-3.5-flash"

_CHART_KEYWORDS = [
    "chart", "graph", "plot", "visualize", "visualise",
    "trend", "bar", "line", "pie", "distribution",
    "show me", "display", "breakdown", "compare",
]

_EXPLICIT_TYPE_KEYWORDS = [
    ("pie", "pie"),
    ("scatter", "scatter"),
    ("line", "line"),
    ("trend", "line"),
    ("bar", "bar"),
]

# Rotating palette -- each report section gets a different color instead of
# everything being the same teal.
CHART_COLORS = [
    "#0F6E56",  # teal
    "#2E5EAA",  # blue
    "#C1440E",  # burnt orange
    "#6A4C93",  # purple
    "#B08900",  # gold
    "#1B7A3D",  # green
    "#A63446",  # brick red
    "#3A6B8A",  # steel blue
]


def wants_chart(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in _CHART_KEYWORDS)


def detect_explicit_chart_type(question: str) -> str | None:
    """
    Returns a chart type if the question explicitly names one (e.g. "as a
    pie chart"), otherwise None. Checked before asking Gemini so we honor
    what the user actually asked for, and skip a wasted API call.
    """
    q = question.lower()
    for keyword, chart_type in _EXPLICIT_TYPE_KEYWORDS:
        if keyword in q:
            return chart_type
    return None


def suggest_chart_type(question: str, df: pd.DataFrame) -> str:
    """Only called when the question doesn't explicitly name a chart type."""
    col_info = ", ".join(f"{c} ({df[c].dtype})" for c in df.columns[:8])
    prompt = f"""Given this user question: "{question}"
And these result columns: {col_info}
With {len(df)} rows of data.

Which chart type is most appropriate? Reply with ONLY one word:
bar / line / pie / scatter / none"""
    try:
        response = _client.models.generate_content(model=_MODEL, contents=prompt)
        chart_type = response.text.strip().lower().split()[0]
        return chart_type if chart_type in ("bar", "line", "pie", "scatter") else "bar"
    except Exception:
        return "bar"


def _pick_columns(df: pd.DataFrame, prefer_time_granularity: bool = False) -> tuple[str, str] | None:
    """
    Picks (label_column, value_column) for charting, or None if the shape
    doesn't suit a chart (no numeric column to plot).

    Deliberately avoids *_id columns and purely numeric columns as the
    label axis -- plotting customer_id/material_id as x makes Plotly treat
    it as a continuous numeric scale instead of categories, which collapses
    bars into 1-2 giant blocks instead of one bar per row.

    When prefer_time_granularity=True (used for line/trend charts), prefers
    the most granular time-like column available (month/date/week over
    year/quarter) -- otherwise a coarse column like fiscal_year gets picked
    even when a proper monthly column exists, stacking many data points at
    the same x position and drawing a jagged zigzag instead of a real trend.
    """
    if df.empty or len(df.columns) < 2:
        return None

    cols = df.columns.tolist()
    candidates = [c for c in cols if not c.lower().endswith("_id") and not pd.api.types.is_numeric_dtype(df[c])]

    label_col = None
    if prefer_time_granularity and candidates:
        granularity_priority = ["date", "month", "week", "day", "period"]
        for keyword in granularity_priority:
            match = next((c for c in candidates if keyword in c.lower()), None)
            if match:
                label_col = match
                break

    if label_col is None:
        label_col = candidates[0] if candidates else cols[0]

    value_col = next(
        (c for c in cols if pd.api.types.is_numeric_dtype(df[c]) and c != label_col),
        None,
    )
    if value_col is None:
        return None  # nothing numeric to plot -- not chartable

    return label_col, value_col


def _build_chronological_sort_series(df: pd.DataFrame, x_col: str) -> pd.Series | None:
    """
    Builds a sortable chronological key for a line chart's x-axis values.

    Rather than guessing from column NAMES (which can be misleading -- a
    column named "month_num" may actually contain formatted strings like
    "01-2025", not a numeric index), this tries to directly PARSE the
    actual x-axis values as dates first. That sidesteps naming confusion
    entirely and is the most reliable approach for real-world data.
    """
    # 1. Try parsing the x-axis column's own values as common date formats.
    for fmt in ["%m-%Y", "%b-%Y", "%B-%Y", "%Y-%m", "%Y-%b", "%m/%Y", "%b %Y"]:
        try:
            return pd.to_datetime(df[x_col], format=fmt)
        except (ValueError, TypeError):
            continue
    try:
        return pd.to_datetime(df[x_col])
    except (ValueError, TypeError):
        pass

    # 2. Fall back to combining a numeric year column + numeric month column.
    cols = df.columns.tolist()
    numeric_month_col = next(
        (c for c in cols if c.lower().endswith("_num") and pd.api.types.is_numeric_dtype(df[c]) and c != x_col),
        None,
    )
    numeric_year_col = next(
        (c for c in cols if "year" in c.lower() and pd.api.types.is_numeric_dtype(df[c])),
        None,
    )
    if numeric_month_col and numeric_year_col:
        return df[numeric_year_col] * 100 + df[numeric_month_col]

    # 3. Fall back to any other date-like column.
    date_col = next((c for c in cols if "date" in c.lower() and c != x_col), None)
    if date_col:
        try:
            return pd.to_datetime(df[date_col])
        except (ValueError, TypeError):
            pass

    return None


def should_show_chart(question: str) -> bool:
    """
    Chart shows ONLY when the question explicitly asks for one -- via a
    chart-related keyword (chart, graph, plot, pie, line, bar, trend, etc.).
    Deliberately keyword-only, not data-shape-based: showing a chart AND a
    table by default for every multi-row answer is visual clutter the user
    didn't ask for. Default is table; chart is opt-in via wording.

    Note: this is used by the single-question tab. Reports use
    decide_report_display() instead, which auto-picks KPI/chart/table per
    section based on data shape, since a full report benefits from richer
    visuals by default.
    """
    return wants_chart(question)


def generate_chart(
    df: pd.DataFrame,
    question: str,
    chart_type: str = None,
    color_index: int = 0,
) -> go.Figure | None:
    if df.empty or len(df.columns) < 2:
        return None

    if chart_type is None:
        chart_type = detect_explicit_chart_type(question) or suggest_chart_type(question, df)

    is_line = chart_type == "line"
    picked = _pick_columns(df, prefer_time_granularity=is_line)
    if picked is None:
        return None
    x_col, y_col = picked

    # Line charts need real chronological order, not row-return order --
    # otherwise the line zigzags instead of showing a real trend. This
    # parses the actual x-axis values as dates rather than guessing from
    # column names, since a column's name (e.g. "month_num") doesn't
    # always match what it actually contains.
    if is_line:
        sort_series = _build_chronological_sort_series(df, x_col)
        if sort_series is not None:
            df = (
                df.assign(_chrono_sort_key=sort_series)
                .sort_values("_chrono_sort_key")
                .drop(columns="_chrono_sort_key")
            )

    title = question[:80]
    color = CHART_COLORS[color_index % len(CHART_COLORS)]

    try:
        if chart_type == "pie":
            fig = px.pie(df.head(15), names=x_col, values=y_col, title=title,
                         color_discrete_sequence=px.colors.sequential.Teal
                         if color_index == 0 else _tint_sequence(color))
        elif chart_type == "line":
            fig = px.line(df, x=x_col, y=y_col, title=title,
                          markers=True, color_discrete_sequence=[color])
        elif chart_type == "scatter":
            fig = px.scatter(df, x=x_col, y=y_col, title=title,
                             color_discrete_sequence=[color])
        else:
            fig = px.bar(df.head(20), x=x_col, y=y_col, title=title,
                         color_discrete_sequence=[color])
            fig.update_layout(xaxis_tickangle=-35)

        # Force categorical x-axis so numeric-looking labels (e.g. codes)
        # never get treated as a continuous scale.
        fig.update_xaxes(type="category")

        fig.update_layout(plot_bgcolor="rgba(0,0,0,0)",
                          paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=50, b=10))
        return fig
    except Exception as exc:
        print(f"[chart] Failed: {exc}")
        return None


def _tint_sequence(base_color: str) -> list[str]:
    """Simple sequential shades of one color, for pie charts on non-default sections."""
    return px.colors.sample_colorscale(
        [[0, "#FFFFFF"], [1, base_color]], [i / 8 for i in range(1, 9)]
    )


def decide_report_display(df: pd.DataFrame) -> str:
    """
    Decides how a report section's data should be displayed:
    - "kpi"   -- a single row of one or more aggregate numbers (e.g. total
                 revenue, total orders) -- shown as KPI cards, not a table.
    - "chart" -- multiple comparable rows with a label + numeric column --
                 shown as a chart, picked automatically per the data shape.
    - "table" -- doesn't fit either pattern (too many rows, no numeric
                 column, or not enough structure) -- falls back to a table.
    - "none"  -- empty result.
    """
    if df.empty:
        return "none"

    if len(df) == 1:
        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        if numeric_cols:
            return "kpi"

    if _pick_columns(df) is not None and 2 <= len(df) <= 30:
        return "chart"

    return "table"


def _format_kpi_value(value) -> str:
    """Formats a raw number into a compact, readable KPI display value."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)

    abs_num = abs(num)
    if abs_num >= 1_000_000_000:
        return f"{num / 1_000_000_000:,.2f}B"
    if abs_num >= 1_000_000:
        return f"{num / 1_000_000:,.2f}M"
    if abs_num >= 1_000:
        return f"{num:,.0f}"
    if num == int(num):
        return f"{int(num):,}"
    return f"{num:,.2f}"


def build_kpi_cards(df: pd.DataFrame) -> list[dict]:
    """
    Turns a single-row result into a list of KPI cards, one per numeric
    column: [{"label": "Total Revenue", "value": "3.61B"}, ...].
    Column names are turned into readable labels (snake_case -> Title Case).
    """
    if df.empty or len(df) != 1:
        return []

    row = df.iloc[0]
    cards = []
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            label = col.replace("_", " ").title()
            cards.append({"label": label, "value": _format_kpi_value(row[col])})
    return cards

