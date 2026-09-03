from unittest.mock import Mock, patch

import pytest

from common import gemini
from common.gemini import GeminiError, extract_text


def test_extract_text_pulls_the_nested_text_field():
    response = {"candidates": [{"content": {"parts": [{"text": '{"title": "hello"}'}]}}]}
    assert extract_text(response) == '{"title": "hello"}'


def test_extract_text_raises_gemini_error_on_unexpected_shape():
    with pytest.raises(GeminiError):
        extract_text({"unexpected": "shape"})

    with pytest.raises(GeminiError):
        extract_text({"candidates": []})


def test_generate_json_paces_back_to_back_calls_under_the_rpm_limit(monkeypatch):
    """Two Gemini calls made close together (e.g. by the same script) must be
    spaced at least MIN_CALL_INTERVAL_SECONDS apart, since the free tier's 5
    requests/minute cap is shared across the whole API key - one script
    bursting several calls can blow through it without ever hitting a 429."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    gemini._last_call_at = 0.0

    ok_response = Mock(status_code=200)
    ok_response.json.return_value = {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}
    ok_response.raise_for_status = Mock()

    # monotonic() is read once per attempt (wait calc) and once right before
    # each request (to stamp _last_call_at) - two back-to-back generate_json()
    # calls consume 4 readings.
    with patch("common.gemini.requests.post", return_value=ok_response), \
         patch("common.gemini.time.sleep") as mock_sleep, \
         patch("common.gemini.time.monotonic", side_effect=[100.0, 100.0, 100.5, 100.5]):
        gemini.generate_json("sys", "user")
        gemini.generate_json("sys", "user")

    mock_sleep.assert_called_once()
    waited = mock_sleep.call_args[0][0]
    assert waited == pytest.approx(gemini.MIN_CALL_INTERVAL_SECONDS - 0.5)
