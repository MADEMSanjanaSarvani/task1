"""LLM helper (Groq) - used by every content-generation step.

Uses the plain REST API (not an SDK) so there's one fewer dependency to pin.
Groq's free tier is 30 requests/minute at the project level (vs Gemini's 5
RPM, which is what this pipeline ran on before) - comfortably enough
headroom for every script's call volume without the constant 429s.
"""
import json
import os
import time

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# 30 RPM free tier - paced with margin below the limit, same reasoning as the
# old Gemini module: a single script can burst several calls back-to-back on
# its own, so proactive spacing avoids 429s instead of only reacting to them.
MIN_CALL_INTERVAL_SECONDS = 2.5
_last_call_at = 0.0


class LLMError(Exception):
    pass


def _call(system_prompt: str, user_prompt: str, temperature: float, timeout: int,
          max_retries: int, json_mode: bool) -> str:
    api_key = os.environ["GROQ_API_KEY"]
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    global _last_call_at
    last_err = None
    for attempt in range(1, max_retries + 1):
        wait = MIN_CALL_INTERVAL_SECONDS - (time.monotonic() - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        try:
            _last_call_at = time.monotonic()
            resp = requests.post(
                GROQ_URL, headers={"Authorization": f"Bearer {api_key}"}, json=body, timeout=timeout,
            )
            # 429 (rate limited) and 5xx (transient server-side overload) both
            # warrant a longer backoff than a plain retry.
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = LLMError(f"transient error ({resp.status_code}): {resp.text[:500]}")
                if attempt < max_retries:
                    time.sleep(10 * attempt)
                continue
            if not resp.ok:
                # a non-transient client error (400, 401, 404...) - resp.raise_for_status()
                # would raise requests.HTTPError, whose default message drops the response
                # body, hiding exactly the detail that explains what's wrong.
                raise LLMError(f"client error ({resp.status_code}): {resp.text[:500]}")
            return extract_text(resp.json())
        except (requests.RequestException, LLMError) as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(3 * attempt)
    raise LLMError(f"LLM call failed after {max_retries} attempts: {last_err}")


def generate_json(system_prompt: str, user_prompt: str, temperature: float = 0.7,
                   max_retries: int = 5, timeout: int = 240) -> dict:
    """Call the LLM in JSON mode and return the parsed object.

    Raises LLMError if the API call fails after retries, or if the response
    isn't valid JSON (a schema mismatch is the caller's problem - this only
    guarantees syntactically valid JSON, same guarantee level the provider's
    JSON mode provides).
    """
    text = _call(system_prompt, user_prompt, temperature, timeout, max_retries, json_mode=True)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"Response wasn't valid JSON: {text[:500]}") from e


def generate_text(system_prompt: str, user_prompt: str, temperature: float = 0.7,
                   max_retries: int = 5, timeout: int = 240) -> str:
    """Call the LLM for a plain-text (non-JSON) response."""
    return _call(system_prompt, user_prompt, temperature, timeout, max_retries, json_mode=False)


def extract_text(response_json: dict) -> str:
    """Pull the message content out of a chat-completions response."""
    try:
        return response_json["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"Unexpected response shape: {json.dumps(response_json)[:500]}") from e
