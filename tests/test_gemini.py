import pytest

from common.gemini import GeminiError, extract_text


def test_extract_text_pulls_the_nested_text_field():
    response = {"candidates": [{"content": {"parts": [{"text": '{"title": "hello"}'}]}}]}
    assert extract_text(response) == '{"title": "hello"}'


def test_extract_text_raises_gemini_error_on_unexpected_shape():
    with pytest.raises(GeminiError):
        extract_text({"unexpected": "shape"})

    with pytest.raises(GeminiError):
        extract_text({"candidates": []})
