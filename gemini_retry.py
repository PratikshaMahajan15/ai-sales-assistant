"""
Wraps Gemini generate_content calls with retry + exponential backoff for
transient errors (503 UNAVAILABLE, 500 INTERNAL), with an optional
fallback model chain for when the primary model is overloaded or its quota
is exhausted.

Also applies a low "thinking" setting per model to reduce reasoning tokens
on tasks that don't need heavy internal reasoning (e.g. writing a short
answer from data that's already provided). gemini-3.5-flash uses the newer
thinking_level string param; gemini-2.5-flash (and earlier) uses the legacy
thinking_budget integer param -- these can't be mixed in one request, so
we pick the right one based on which model is actually being called.
"""

import time
import random
import logging
from google.genai import types as genai_types

logger = logging.getLogger("gemini-retry")

# Errors worth retrying with backoff -- genuinely transient, likely to
# clear up within seconds.
_RETRYABLE_MARKERS = ["503", "UNAVAILABLE", "500", "INTERNAL"]

# Daily/rate quota exhaustion -- retrying within seconds will NOT fix this,
# so we skip retries entirely and jump straight to the next fallback model
# instead of wasting the full backoff cycle on an error that's guaranteed
# to fail again.
_QUOTA_EXHAUSTED_MARKERS = ["RESOURCE_EXHAUSTED", "429"]

# Models using the newer thinking_level string param (minimal/low/medium/high)
_THINKING_LEVEL_MODELS = {"gemini-3.5-flash", "gemini-3.5-pro", "gemini-3.5-flash-lite", "gemini-3.6-flash"}


def _build_thinking_config(model_name: str, user_config=None):
    """
    Merges a low-thinking setting into the user-supplied config, without
    overwriting anything the caller explicitly set (e.g. system_instruction).
    """
    kwargs = {}
    if user_config is not None:
        # GenerateContentConfig doesn't expose a clean way to copy fields
        # generically across SDK versions, so we only forward the fields
        # this app actually uses.
        if hasattr(user_config, "system_instruction") and user_config.system_instruction:
            kwargs["system_instruction"] = user_config.system_instruction
        if hasattr(user_config, "temperature") and user_config.temperature is not None:
            kwargs["temperature"] = user_config.temperature

    if model_name in _THINKING_LEVEL_MODELS:
        kwargs["thinking_config"] = genai_types.ThinkingConfig(thinking_level="low")
    else:
        # Legacy models (gemini-2.5-flash and earlier) use thinking_budget.
        # A small positive budget keeps some reasoning for harder prompts
        # without letting it run unbounded; 0 disables thinking entirely.
        kwargs["thinking_config"] = genai_types.ThinkingConfig(thinking_budget=256)

    return genai_types.GenerateContentConfig(**kwargs)


def call_gemini(
    client,
    model: str,
    contents: str,
    config=None,
    max_retries: int = 4,
    fallback_models: list[str] | None = None,
):
    models_to_try = [model] + (fallback_models or [])
    last_exc = None

    for model_name in models_to_try:
        effective_config = _build_thinking_config(model_name, config)

        for attempt in range(max_retries):
            try:
                return client.models.generate_content(
                    model=model_name, contents=contents, config=effective_config
                )
            except Exception as exc:
                last_exc = exc
                err_str = str(exc)

                is_quota_exhausted = any(marker in err_str for marker in _QUOTA_EXHAUSTED_MARKERS)
                is_retryable = any(marker in err_str for marker in _RETRYABLE_MARKERS)

                if is_quota_exhausted:
                    logger.warning(
                        "Model %s quota exhausted, skipping retries, trying next fallback.",
                        model_name,
                    )
                    break  # skip straight to the next model, no point retrying a daily quota

                if not is_retryable:
                    raise

                if attempt == max_retries - 1:
                    logger.warning(
                        "Model %s exhausted retries, moving to next fallback if any.",
                        model_name,
                    )
                    break

                wait = (2 ** attempt) + random.uniform(0, 0.5)
                logger.warning(
                    "Gemini call failed on %s (attempt %d/%d), retrying in %.1fs: %s",
                    model_name, attempt + 1, max_retries, wait, err_str,
                )
                time.sleep(wait)

    raise last_exc