"""Property-based tests: messy input must never crash tieout or produce a guessed number."""

import csv
import io
from datetime import date
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tieout import clean_file
from tieout.export import to_payload
from tieout.normalize import parse_date, parse_money, parse_number, parse_status

messy_text = st.one_of(
    st.text(max_size=30),
    st.sampled_from(["", "-", "N/A", "TBD", "VACANT", "Total", "$1,000.00", "(50)", "1/2/26", "MTM", "=SUM(A1)"]),
)
cell = st.one_of(
    st.none(),
    messy_text,
    st.integers(-(10**9), 10**9),
    st.floats(allow_nan=True, allow_infinity=True),
    st.decimals(allow_nan=False, allow_infinity=False, places=2),
    st.dates(),
    st.booleans(),
)


@given(cell)
def test_parsers_never_raise_and_always_explain_a_blank(value):
    for parser in (parse_money, parse_number, parse_date, parse_status):
        result, issue = parser(value)
        assert issue is None or isinstance(issue, str)
        if result is None and issue is None:
            # A blank is only allowed for empty-looking input, never for unreadable data.
            assert value is None or str(value).strip().lower() in {"", "-", "--", "—", "–", "n/a", "na", "none", "nil"}


@given(st.decimals(min_value=-(10**7), max_value=10**7, places=2, allow_nan=False))
def test_money_round_trips_through_common_formats(amount):
    plain = f"{amount:.2f}"
    commas = f"{abs(amount):,.2f}"
    accounting = f"({commas})" if amount < 0 else f"${commas}"
    for text in (plain, accounting):
        assert parse_money(text) == (amount, None)


@given(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz /:#", min_size=1, max_size=20).filter(lambda s: s.strip()),
    st.integers(0, 99),
)
def test_words_around_a_number_are_never_read_as_money(word, n):
    value, issue = parse_money(f"{word.strip()} {n}")
    assert value is None and issue


@given(st.dates(min_value=date(1950, 1, 1), max_value=date(2099, 12, 31)))
def test_dates_round_trip(d):
    for text in (d.isoformat(), f"{d.month}/{d.day}/{d.year}", f"{d:%b} {d.day}, {d.year}"):
        assert parse_date(text) == (d, None)


header = st.sampled_from(
    ["Unit", "Tenant", "Rent", "Market Rent", "Sq Ft", "Status", "Lease From", "Lease To", "Notes"]
)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    headers=st.lists(header, min_size=2, max_size=8, unique=True),
    body=st.lists(st.lists(st.one_of(st.none(), messy_text), max_size=10), max_size=25),
    title_rows=st.integers(0, 3),
)
def test_pipeline_survives_random_csv(tmp_path_factory, headers, body, title_rows):
    path = tmp_path_factory.mktemp("fuzz") / "random.csv"
    buf = io.StringIO()
    w = csv.writer(buf)
    for i in range(title_rows):
        w.writerow([f"Report title {i}"])
    w.writerow(headers)
    for row in body:
        w.writerow(["" if v is None else v for v in row])
    path.write_text(buf.getvalue(), newline="")
    try:
        result = clean_file(path)
    except ValueError as e:
        # The only acceptable failure: no recognisable header at all.
        assert "header" in str(e).lower()
        return
    payload = to_payload(result)  # must serialise
    assert payload["summary"]["units"] == len(result.rows)
    for row in result.rows:
        rent = row.get("current_rent")
        assert rent is None or isinstance(rent, Decimal)


def test_found_by_fuzzing_huge_and_infinite_values_are_flagged_not_crashes():
    assert parse_money(1e26)[0] is None
    assert parse_money(float("inf"))[0] is None
    assert parse_money("9" * 40)[0] is None
    assert parse_number("9" * 400)[0] is None
    assert parse_number(float("-inf"))[0] is None
