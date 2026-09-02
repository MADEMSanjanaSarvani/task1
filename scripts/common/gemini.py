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


class GeminiError(Exception):
    pass


def generate_json(system_prompt: str, user_prompt: str, temperature: float = 0.7,
                   max_retries: int = 3, timeout: int = 240) -> dict:
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

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, params={"key": api_key}, json=body, timeout=timeout)
            if resp.status_code == 429:
                # rate limited - back off and retry
                last_err = GeminiError(f"rate limited (429): {resp.text[:300]}")
                time.sleep(5 * attempt)
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
