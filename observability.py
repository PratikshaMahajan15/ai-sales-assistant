"""
Sets up Langfuse tracing for the whole app. Import this ONCE, as the very
first import in app.py -- before any file that creates a genai.Client()
(llm.py, chart_generator.py, report_generator.py) -- so every Gemini call
made anywhere in the app gets automatically traced.

How it works:
- Langfuse() reads LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST
  from the environment and sets up OpenTelemetry export to your project.
- GoogleGenAIInstrumentor patches google-genai's generate_content calls so
  every SQL generation, answer generation, chart-type suggestion, and
  report-planning call becomes a trace automatically -- no code changes
  needed at the call sites.
"""

from langfuse import Langfuse
from openinference.instrumentation.google_genai import GoogleGenAIInstrumentor

langfuse = Langfuse()
GoogleGenAIInstrumentor().instrument()