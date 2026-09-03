"""Gemini API helper - one function, used by every content-generation step.

Uses the plain REST API (not the SDK) so there's one fewer dependency to pin,
and so the exact same request shape used in the n8n version of this pipeline
carries over directly.
"""
import json
import os
import time

import requests

GEMINI_URL_TMPL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Gemini's free tier is only 5 requests/minute *per model, shared across the
# whole API key* - one script issuing 2-3 calls back-to-back can blow through
# that on its own even with no other job running. Spacing calls out proactively
# avoids 429s in the first place instead of only reacting to them after the fact.
MIN_CALL_INTERVAL_SECONDS = 13
_last_call_at = 0.0


class GeminiError(Exception):
    pass


def generate_json(system_prompt: str, user_prompt: str, temperature: float = 0.7,
                   max_retries: int = 5, timeout: int = 240) -> dict:
    """Call Gemini with responseMimeType=application/json and return the parsed object.

    Raises GeminiError if the API call fails after retries, or if the response
    isn't valid JSON (a schema mismatch is the caller's problem - this only
    guarantees syntactically valid JSON, same guarantee level Gemini's
    responseMimeType provides).
    """
    api_key = os.environ["GEMINI_API_KEY"]
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    url = GEMINI_URL_TMPL.format(model=model)

    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        # thinkingBudget=0 disables extended reasoning - this pipeline only needs
        # structured JSON output, not multi-step reasoning, and thinking mode adds
        # significant latency/cost for no benefit here. Some models ignore this
        # field silently if they don't support it, which is fine.
        "generationConfig": {
            "temperature": temperature, "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    global _last_call_at
    last_err = None
    for attempt in range(1, max_retries + 1):
        wait = MIN_CALL_INTERVAL_SECONDS - (time.monotonic() - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        try:
            _last_call_at = time.monotonic()
            resp = requests.post(url, params={"key": api_key}, json=body, timeout=timeout)
            # 429 (rate limited) and 5xx (transient server-side overload, e.g. the
            # "-latest" preview endpoints under load) both warrant a longer backoff
            # than a plain retry - a few seconds isn't enough for the server to recover.
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = GeminiError(f"transient error ({resp.status_code}): {resp.text[:300]}")
                if attempt < max_retries:
                    time.sleep(10 * attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            text = extract_text(data)
            return json.loads(text)
        except (requests.RequestException, json.JSONDecodeError, GeminiError) as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(3 * attempt)
    raise GeminiError(f"Gemini call failed after {max_retries} attempts: {last_err}")


def extract_text(response_json: dict) -> str:
    """Pull the text out of a Gemini generateContent response."""
    try:
        return response_json["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as e:
        raise GeminiError(f"Unexpected Gemini response shape: {json.dumps(response_json)[:500]}") from e
