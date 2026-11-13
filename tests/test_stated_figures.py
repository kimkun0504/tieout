from decimal import Decimal

import pytest

from tieout.ingest import Grid
from tieout.pipeline import clean_file

H = ["Unit", "Tenant", "Status", "Sq Ft", "Market Rent", "Current Rent"]
UNITS = [
    ["101", "Smith", "Occupied", 700, 1500, 1450],
    ["102", None, "Vacant", 700, 1500, 0],
    ["103", "Lee", "Notice", 900, 1800, 1750],
    ["104", "Park", "Occupied", 900, 1800, 1800],
]
TOTAL = ["Total", None, None, 3200, 6600, 5000]


def _run(*footer):
    return clean_file("x.csv", grid=Grid("x.csv", "Rent Roll", [H, *UNITS, TOTAL, [], *footer]))


def _rules(result):
    return [(i.severity.value, i.rule) for i in result.issues if i.rule.startswith("stated_")]


def test_footer_statistics_are_not_read_as_units():
    r = _run(
        ["Total Units", 4], ["Occupied Units:", 3], ["Vacant", 1], ["% Occupied", "75.00%"], ["Average Rent", 1250]
    )
    assert [row.get("unit") for row in r.rows] == ["101", "102", "103", "104"]
    assert r.skipped["summary"] == 5
    assert _rules(r) == [("info", "stated_figure_ties")] * 4  # Average Rent is recognised but not checked
    assert r.ok


@pytest.mark.parametrize(
    "stated, ties",
    [
        ("75%", True),
        ("75.0%", True),
        (0.75, True),  # an Excel percentage cell
        (75, True),
        ("74.6%", False),
        ("74.9", False),  # printed to one decimal, so 74.9 is not 75.0
        ("76%", False),
    ],
)
def test_occupancy_is_compared_at_the_precision_it_was_printed(stated, ties):
    r = _run(["Occupancy", stated])
    assert _rules(r) == [("info", "stated_figure_ties")] if ties else [("warning", "stated_figure_differs")]


def test_unit_count_mismatch_is_an_error_pointing_at_the_cell():
    r = _run(["Total Units", 5])
    (issue,) = [i for i in r.issues if i.rule == "stated_figure_differs"]
    assert issue.severity.value == "error" and issue.refs[0].cell == "B8"
    assert "5 units" in issue.message and "missing" in issue.message
    assert not r.ok


def test_occupied_count_mismatch_is_a_warning():
    r = _run(["Occupied Units", 2])
    assert _rules(r) == [("warning", "stated_figure_differs")]


def test_a_unit_row_with_words_in_it_is_still_a_unit():
    # unit codes have digits; a tenant called "Vacancy Partners" is a tenant, not a statistic
    rows = [
        H,
        ["201", "Vacancy Partners LLC", "Occupied", 800, 1600, 1600],
        ["PH", "Occupancy Co", "Occupied", 2000, 4000, 4000],
    ]
    r = clean_file("x.csv", grid=Grid("x.csv", "x", rows))
    assert [row.get("unit") for row in r.rows] == ["201", "PH"]
    assert r.rows[1].get("current_rent") == Decimal("4000.00")


def test_unit_missing_its_code_is_not_mistaken_for_a_vacancy_count():
    rows = [H, *UNITS, [None, "VACANT", None, 700, 1500]]
    r = clean_file("x.csv", grid=Grid("x.csv", "x", rows))
    assert not _rules(r)
