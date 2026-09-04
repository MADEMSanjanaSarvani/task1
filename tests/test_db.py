import decimal

import pytest

from common.db import json_default


def test_json_default_converts_decimal_to_float():
    assert json_default(decimal.Decimal("42.50")) == 42.5
    assert isinstance(json_default(decimal.Decimal("42.50")), float)


def test_json_default_raises_typeerror_for_other_unsupported_types():
    with pytest.raises(TypeError):
        json_default(object())
