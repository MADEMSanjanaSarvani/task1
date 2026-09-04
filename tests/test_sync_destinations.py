import datetime
import decimal
import json

from common.sync_destinations import _stringify


def test_stringify_converts_decimal_to_float():
    result = _stringify(decimal.Decimal("87.50"))
    assert result == 87.5
    assert isinstance(result, float)


def test_stringify_converts_datetime_to_isoformat_string():
    dt = datetime.datetime(2026, 9, 4, 12, 30, tzinfo=datetime.timezone.utc)
    assert _stringify(dt) == dt.isoformat()


def test_stringify_passes_through_plain_scalars():
    assert _stringify("hello") == "hello"
    assert _stringify(42) == 42
    assert _stringify(None) is None


def test_stringify_json_encodes_dicts_and_lists():
    assert _stringify({"a": 1}) == json.dumps({"a": 1})
    assert _stringify([1, 2, 3]) == json.dumps([1, 2, 3])


def test_stringify_handles_decimal_nested_inside_dict_or_list():
    # a NUMERIC-column value ever ending up nested in a dict/list shouldn't
    # crash the json.dumps() branch either - this is what would have broken
    # sync_airtable (requests.post(json=...) raises TypeError, which isn't a
    # requests.RequestException, so its own try/except wouldn't have caught it)
    result = _stringify({"score": decimal.Decimal("12.34")})
    assert json.loads(result) == {"score": 12.34}


def test_stringify_handles_datetime_nested_inside_dict_or_list():
    dt = datetime.datetime(2026, 9, 4, 12, 30, tzinfo=datetime.timezone.utc)
    result = _stringify({"created_at": dt})
    assert json.loads(result) == {"created_at": dt.isoformat()}
