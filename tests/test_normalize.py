from datetime import date, datetime
from decimal import Decimal

import pytest

from tieout.normalize import (
    is_vacant_marker,
    parse_date,
    parse_money,
    parse_number,
    parse_status,
    parse_text,
    tidy_name,
)

D = Decimal


# --- money ------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("$1,425.00", D("1425.00")),
        ("1425", D("1425.00")),
        ("(100.00)", D("-100.00")),
        ("$-100.00", D("-100.00")),
        ("-$100", D("-100.00")),
        ("100.00-", D("-100.00")),
        ("100.00 CR", D("-100.00")),
        ("1,300.00 USD", D("1300.00")),
        ("1,250 / mo", D("1250.00")),
        (".50", D("0.50")),
        (1450, D("1450.00")),
        (1425.1, D("1425.10")),
        (0.125, D("0.13")),  # half away from zero, like Excel
        ("0.125", D("0.13")),
    ],
)
def test_money_parses_valid_amounts(raw, expected):
    assert parse_money(raw) == (expected, None)


@pytest.mark.parametrize("raw", ["Paid thru 10/31", "See note 3", "1,425.00 2", "12,34,5", "1.2.3", "abc"])
def test_money_rejects_text_that_merely_contains_digits(raw):
    value, issue = parse_money(raw)
    assert value is None and issue


def test_money_flags_european_format_instead_of_misreading():
    value, issue = parse_money("€1.300,00")
    assert value is None and "European" in issue


@pytest.mark.parametrize("raw", ["-", "–", "N/A", "none"])
def test_money_empty_tokens_are_blank_not_errors(raw):
    assert parse_money(raw) == (None, None)


def test_money_rejects_bool_and_nan():
    assert parse_money(True)[0] is None
    assert parse_money(float("nan"))[0] is None


# --- numbers ------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected", [("1,200", 1200), ("1,200 SF", 1200), ("850 sq ft", 850), (812.5, 812.5), ("9.5", 9.5)]
)
def test_number(raw, expected):
    assert parse_number(raw) == (expected, None)


@pytest.mark.parametrize("raw", ["approx 900", "900-950", "12,34"])
def test_number_rejects_ambiguous(raw):
    assert parse_number(raw)[0] is None


# --- dates ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("3/1/2026", date(2026, 3, 1)),
        ("03/04/2025", date(2025, 3, 4)),  # US month-first
        ("1/2/26", date(2026, 1, 2)),
        ("2026-01-15", date(2026, 1, 15)),
        ("Jan 15, 2026", date(2026, 1, 15)),
        ("15-Jan-2026", date(2026, 1, 15)),
        (datetime(2026, 2, 1, 0, 0), date(2026, 2, 1)),
        (45658, date(2025, 1, 1)),
        ("45658", date(2025, 1, 1)),  # Excel serial stored as text in a CSV
    ],
)
def test_date_parses_complete_dates(raw, expected):
    assert parse_date(raw) == (expected, None)


@pytest.mark.parametrize("raw", ["12", "2026", "Jan", "Jan 2026", "TBD", "12/2026"])
def test_date_rejects_partial_dates(raw):
    value, issue = parse_date(raw)
    assert value is None and issue


def test_month_to_month_is_explained():
    assert parse_date("MTM") == (None, "month-to-month lease (no end date)")


# --- status --------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Occupied-NTV", "notice"),
        ("Occupied Notice", "notice"),
        ("Notice-Unrented", "notice"),
        ("Occupied No Notice", "occupied"),
        ("Current", "occupied"),
        ("Vacant-Leased", "vacant"),
        ("Vacant Unrented Ready", "vacant"),
        ("Model", "model"),
        ("Down", "down"),
        ("Employee Unit", "down"),
    ],
)
def test_status(raw, expected):
    assert parse_status(raw) == (expected, None)


def test_unknown_status_is_flagged():
    value, issue = parse_status("Eviction")
    assert value is None and "unknown status" in issue


# --- text, names, vacancy markers ---------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("O'BRIEN, SEAN", "O'Brien, Sean"),
        ("SMITH-JONES, AL", "Smith-Jones, Al"),
        ("ABC PLUMBING LLC", "Abc Plumbing LLC"),
        ("GARCIA, MARIA", "Garcia, Maria"),
        ("McDonald, Ann", "McDonald, Ann"),  # mixed case is left alone
    ],
)
def test_tidy_name(raw, expected):
    assert tidy_name(raw) == expected


@pytest.mark.parametrize("raw", ["VACANT", "Vacant - Ready", "*VACANT - UNRENTED*", "-vacant-", "Available"])
def test_vacant_markers(raw):
    assert is_vacant_marker(raw)


@pytest.mark.parametrize("raw", ["Lee, Jordan", "Vance, Alex", ""])
def test_not_vacant_markers(raw):
    assert not is_vacant_marker(raw)


def test_text_from_float_unit_number():
    assert parse_text(101.0) == ("101", None)


def test_text_flags_auto_converted_dates():
    value, issue = parse_text(datetime(2026, 1, 2))
    assert value is None and "auto-converted" in issue
