from datetime import date, datetime

import pytest

from samples import make_stacked_header_xlsx
from tieout.detect import detect_header, find_report_date
from tieout.ingest import Grid
from tieout.pipeline import clean_file

HEADER = ["Unit", "Tenant", "Sq Ft", "Market Rent", "Current Rent", "Lease End"]
ROW = ["101", "Smith", 700, 1500, 1450, "12/31/2026"]


def _grid(*title_rows: list[object]) -> Grid:
    return Grid("x.xlsx", "Sheet1", [*map(list, title_rows), HEADER, ROW, ["102", *ROW[1:]]])


def _found(*title_rows: list[object]) -> date | None:
    g = _grid(*title_rows)
    rd = find_report_date(g, detect_header(g))
    return rd.value if rd else None


@pytest.mark.parametrize(
    "rows, expected",
    [
        ([["Rent Roll as of 10/31/2026"]], date(2026, 10, 31)),
        ([["As Of = 10/31/2026"]], date(2026, 10, 31)),  # Yardi
        ([["Report Date: October 31, 2026"]], date(2026, 10, 31)),
        ([["As of Date:", None, datetime(2026, 9, 30)]], date(2026, 9, 30)),  # label cell, date cell
        ([["Period ending 2026-06-30"]], date(2026, 6, 30)),
        ([["As-of 31 Oct 2026"]], date(2026, 10, 31)),
        # a printed/run date is when the report was generated, not what it covers
        ([["Printed 11/03/2026 as of 10/31/2026"]], None),
        ([["Run date: 11/03/2026"]], None),
        # "as of" outranks "report date"; disagreeing "as of" dates give no answer
        ([["Report date 11/03/2026"], ["As of 10/31/2026"]], date(2026, 10, 31)),
        ([["As of 10/31/2026"], ["As of 09/30/2026"]], None),
        ([["Maple Court"], ["Rent Roll"]], None),
        ([["As of 13/45/2026"]], None),
    ],
)
def test_find_report_date(rows, expected):
    assert _found(*rows) == expected


def test_dates_below_the_header_are_not_report_dates():
    g = Grid("x.csv", "x", [HEADER, ["101", "As of 10/31/2026", 700, 1500, 1450, "12/31/2026"], ROW])
    assert find_report_date(g, detect_header(g)) is None


def test_file_date_is_used_when_none_is_given(tmp_path):
    result = clean_file(make_stacked_header_xlsx(tmp_path / "m.xlsx"))
    assert result.as_of == date(2026, 10, 31)
    assert result.report_date and result.report_date.ref.cell == "A3"
    assert not [i for i in result.issues if i.rule == "report_date_differs"]


def test_given_date_wins_but_a_mismatch_is_flagged(tmp_path):
    result = clean_file(make_stacked_header_xlsx(tmp_path / "m.xlsx"), as_of=date(2026, 11, 30))
    assert result.as_of == date(2026, 11, 30)
    (issue,) = [i for i in result.issues if i.rule == "report_date_differs"]
    assert issue.refs[0].cell == "A3"
