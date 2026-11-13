from decimal import Decimal

import pytest

from tieout.ingest import Grid
from tieout.normalize import parse_status
from tieout.pipeline import clean_file
from tieout.review import Review

H = ["Unit", "Unit Type", "Sq Ft", "Resident", "Status", "Market Rent", "Actual Rent", "Lease End"]
CURRENT = [
    ["Current/Notice/Vacant Residents"],
    ["101", "1x1", 700, "Smith", "Occupied", 1500, 1450, "12/31/2026"],
    ["102", "1x1", 700, "Lee", "Notice", 1500, 1400, "11/30/2026"],
    ["103", "2x2", 900, None, "Vacant-Leased", 1800, 0, None],
    ["Total", None, 2300, None, None, 4800, 2850, None],
]
FUTURE = [
    ["Future Residents/Applicants"],
    ["102", "1x1", 700, "Park", "Applicant", 1500, 1550, "11/30/2027"],
    ["103", "2x2", 900, "Kim", "Occupied", 1800, 1800, "12/31/2027"],  # section decides
    ["Total Future", None, 1600, None, None, 3300, 3350, None],
]


def _run(*sections, review=None):
    rows = [H]
    for sec in sections:
        rows += sec
    return clean_file("x.csv", grid=Grid("x.csv", "Rent Roll", rows), review=review)


@pytest.mark.parametrize(
    "text, status",
    [
        ("Applicant", "future"),
        ("Future", "future"),
        ("Pending", "future"),
        ("Pre-leased", "future"),
        ("Vacant-Leased", "vacant"),
        ("Occupied", "occupied"),
    ],
)
def test_future_status_words(text, status):
    assert parse_status(text)[0] == status


def test_future_leases_are_kept_but_not_counted_as_units():
    r = _run(CURRENT, FUTURE)
    s = r.summary()
    assert s["units"] == 3 and s["future_leases"] == 2
    assert s["physical_occupancy"] == pytest.approx(2 / 3, abs=1e-4)
    assert s["total_current_rent"] == "2850.00"
    assert [row.get("status") for row in r.rows][-2:] == ["future", "future"]
    tv = r.rows[-1].values["status"]
    assert tv.derived and tv.original == "occupied"  # the section overrode the cell, visibly
    assert not [i for i in r.issues if "duplicate" in i.rule]
    assert [i.rule for i in r.issues if i.rule == "future_leases"]
    assert r.ok
    totals = [i for i in r.issues if i.rule == "total_ties_out"]
    assert len(totals) == 6  # both totals still tie out over their own rows


def test_future_rows_dont_feed_footer_checks():
    r = _run(CURRENT, FUTURE, [["Total Units", 3]])
    assert [i.severity.value for i in r.issues if i.rule.startswith("stated_")] == ["info"]


def test_reviewer_correction_beats_the_section():
    from tieout.models import Correction

    review = Review(corrections=[Correction(source_row=9, field="status", value="occupied", reason="moved in early")])
    r = _run(CURRENT, FUTURE, review=review)
    assert r.summary()["units"] == 4 and r.rows[-1].get("status") == "occupied"
    assert r.rows[-1].get("current_rent") == Decimal("1800.00")


def test_future_lease_reads_naturally_for_ai_records():
    from tieout.export import unit_text

    row = _run(CURRENT, FUTURE).rows[-1]
    assert "has a future lease with Kim that has not started yet." in unit_text(row, False)
    assert "Kim" not in unit_text(row, True)


def test_derived_status_explains_itself():
    row = _run(CURRENT, FUTURE).rows[-1]
    assert row.values["status"].to_dict()["note"].startswith('Listed under "Future Residents/Applicants"')
