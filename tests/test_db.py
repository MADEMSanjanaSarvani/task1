import datetime
import decimal

import pytest

from common.db import json_default


def test_json_default_converts_decimal_to_float():
    assert json_default(decimal.Decimal("42.50")) == 42.5
    assert isinstance(json_default(decimal.Decimal("42.50")), float)


def test_json_default_converts_datetime_and_date_to_isoformat():
    dt = datetime.datetime(2026, 9, 4, 12, 30, tzinfo=datetime.timezone.utc)
    assert json_default(dt) == dt.isoformat()

    d = datetime.date(2026, 9, 4)
    assert json_default(d) == "2026-09-04"


def test_json_default_raises_typeerror_for_other_unsupported_types():
    with pytest.raises(TypeError):
        json_default(object())
