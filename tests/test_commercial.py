from decimal import Decimal

from tieout.ingest import Grid
from tieout.pipeline import clean_file

H = ["Suite", "Tenant", "RSF", "Lease Exp.", "Annual Base Rent", "Base Rent $/SF/Yr", "Monthly Base Rent"]


def _run(*units, header=H, total=None):
    rows = [["Commerce Plaza"], ["As of 9/30/2026"], [], header, *units]
    if total:
        rows.append(total)
    return clean_file("x.csv", grid=Grid("x.csv", "Rent Roll", rows))


def _rules(r, rule):
    return [i for i in r.issues if i.rule == rule]


def test_commercial_headers_map_with_full_confidence():
    r = _run(["100", "Starbucks", 1800, "12/31/2029", 72000, "$40.00", 6000])
    fields = {m.header: (m.field, m.confidence) for m in r.mappings}
    assert fields["Base Rent $/SF/Yr"] == ("rent_psf", 1.0)
    assert fields["Monthly Base Rent"] == ("current_rent", 1.0)
    assert fields["Annual Base Rent"] == ("annual_rent", 1.0)
    assert r.rows[0].get("rent_psf") == Decimal("40.00")
    assert not _rules(r, "rent_psf_mismatch")


def test_rate_that_disagrees_with_rent_and_area_is_flagged():
    r = _run(["120", "H&R Block", 1500, "2/28/2027", 45000, 33.00, 3750])
    (issue,) = _rules(r, "rent_psf_mismatch")
    assert issue.field == "rent_psf" and "30.00/SF" in issue.message


def test_rate_rounded_to_the_cent_is_not_flagged():
    # 41,000 / 1,234 = 33.2252...; printed as 33.23
    r = _run(["130", "Tenant", 1234, "1/31/2028", 41000, 33.23, None])
    assert not _rules(r, "rent_psf_mismatch")


def test_monthly_rate_becomes_annual_and_is_marked_derived():
    header = ["Suite", "Tenant", "SF", "Monthly Rent", "Rent/SF/Mo"]
    r = _run(["200", "Dentist", 1000, 2500, 2.50], header=header)
    tv = r.rows[0].values["rent_psf"]
    assert tv.value == Decimal("30.00") and tv.derived and tv.source.cell == "E5"
    assert "rent_psf_monthly" not in r.rows[0].values
    assert not _rules(r, "rent_psf_mismatch")


def test_a_total_rows_average_rate_is_not_tied_out_as_a_sum():
    r = _run(
        ["100", "A", 1000, "1/1/2030", 30000, 30.00, 2500],
        ["110", "B", 1000, "1/1/2030", 40000, 40.00, 3333.33],
        total=["Total", None, 2000, None, 70000, 35.00, 5833.33],
    )
    assert "rent_psf" not in r.totals[0].amounts
    assert r.ok, [i.message for i in r.open_issues]
