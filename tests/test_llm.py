from unittest.mock import Mock, patch

import pytest

from common import llm
from common.llm import LLMError, extract_text


def test_extract_text_pulls_the_message_content():
    response = {"choices": [{"message": {"content": '{"title": "hello"}'}}]}
    assert extract_text(response) == '{"title": "hello"}'


def test_extract_text_raises_llm_error_on_unexpected_shape():
    with pytest.raises(LLMError):
        extract_text({"unexpected": "shape"})

    with pytest.raises(LLMError):
        extract_text({"choices": []})


def test_generate_json_paces_back_to_back_calls_under_the_rpm_limit(monkeypatch):
    """Two calls made close together (e.g. by the same script) must be spaced
    at least MIN_CALL_INTERVAL_SECONDS apart, since Groq's free tier's 30
    requests/minute cap is shared at the project level - one script bursting
    several calls can still blow through it without ever hitting a 429."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    llm._last_call_at = 0.0

    ok_response = Mock(status_code=200)
    ok_response.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
    ok_response.raise_for_status = Mock()

    # monotonic() is read once per attempt (wait calc) and once right before
    # each request (to stamp _last_call_at) - two back-to-back generate_json()
    # calls consume 4 readings.
    with patch("common.llm.requests.post", return_value=ok_response), \
         patch("common.llm.time.sleep") as mock_sleep, \
         patch("common.llm.time.monotonic", side_effect=[100.0, 100.0, 100.5, 100.5]):
        llm.generate_json("sys", "user")
        llm.generate_json("sys", "user")

    mock_sleep.assert_called_once()
    waited = mock_sleep.call_args[0][0]
    assert waited == pytest.approx(llm.MIN_CALL_INTERVAL_SECONDS - 0.5)


def test_generate_json_raises_on_invalid_json_response(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    llm._last_call_at = 0.0

    bad_response = Mock(status_code=200)
    bad_response.json.return_value = {"choices": [{"message": {"content": "not json"}}]}
    bad_response.raise_for_status = Mock()

    with patch("common.llm.requests.post", return_value=bad_response), \
         patch("common.llm.time.sleep"), \
         patch("common.llm.time.monotonic", return_value=100.0):
        with pytest.raises(LLMError):
            llm.generate_json("sys", "user")


def test_generate_text_returns_raw_content_not_parsed_json(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    llm._last_call_at = 0.0

    text_response = Mock(status_code=200)
    text_response.json.return_value = {"choices": [{"message": {"content": "Plain text plan."}}]}
    text_response.raise_for_status = Mock()

    with patch("common.llm.requests.post", return_value=text_response) as mock_post, \
         patch("common.llm.time.sleep"), \
         patch("common.llm.time.monotonic", return_value=100.0):
        result = llm.generate_text("sys", "user")

    assert result == "Plain text plan."
    # generate_text must not request JSON mode - it's a plain-text response
    assert "response_format" not in mock_post.call_args.kwargs["json"]
