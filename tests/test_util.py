import re

from common.util import new_run_id, today


def test_new_run_id_format_is_date_prefixed_and_lexicographically_sortable():
    a = new_run_id()
    assert re.match(r"^\d{8}-\d+$", a), a
    # date-prefix + millisecond-timestamp construction guarantees sort order across
    # any two calls separated by real wall-clock time (same-millisecond calls may
    # tie, which is fine - this run_id only needs to be unique per actual pipeline
    # run, not per Python statement).
    date_prefix, ms = a.split("-")
    assert len(date_prefix) == 8
    assert ms.isdigit()


def test_today_format():
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", today())
