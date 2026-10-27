from google import genai
from langfuse import observe
from config import GEMINI_API_KEY
from gemini_retry import call_gemini

_client = genai.Client(api_key=GEMINI_API_KEY)
_MODEL = "gemini-3.5-flash"
_FALLBACKS = ["gemini-3.5-flash-lite"]


@observe(name="generate_sql")
def generate_sql(prompt: str) -> str:
    response = call_gemini(_client, _MODEL, prompt, fallback_models=_FALLBACKS)
    sql = response.text.strip()
    if sql.startswith("```"):
        sql = "\n".join(l for l in sql.split("\n") if not l.strip().startswith("```")).strip()
    return sql


@observe(name="generate_answer")
def generate_answer(question: str, sql: str, result_preview: str) -> str:
    prompt = f"""The user asked: "{question}"

Here is the data that answers it:
{result_preview}

Write a short, direct answer to exactly what they asked -- as if you're
replying to them in conversation, not writing a report.

Rules:
- Start by directly answering the question, using the same words they used
  where possible. If they asked "who," name the who. If they asked "how
  many," give the number first.
- Use simple, everyday words. Avoid "substantial," "significant,"
  "represents," "key insights," "top purchasing record" -- just say
  "biggest," "most," "highest," "bought the most," etc.
- Keep it to 2-3 short sentences. No filler opening like "Based on the
  data" or "According to the results."
- No mention of SQL, databases, or queries.
- Never mention that you can't display images, charts, or visuals, and
  never say things like "as a text-based assistant." A chart or table is
  rendered separately by the app whenever relevant -- just answer the
  question with the numbers, and don't comment on your own output format
  or capabilities at all.
- Only state what the data directly shows. Do not guess at the business
  meaning of codes, categories, or abbreviations unless the data itself
  explains them -- say the meaning is unclear instead of guessing."""
    response = call_gemini(_client, _MODEL, prompt, fallback_models=_FALLBACKS)
    return response.text.strip()