from datetime import date
from decimal import Decimal

import pytest

from tieout import clean_file
from tieout.models import Severity
from tieout.review import Review


def rules(result, severity=None):
    return [i.rule for i in result.open_issues if severity is None or i.severity is severity]


# --- charge lines ------------------------------------------------------------------

def test_charge_lines_roll_up_per_unit(charges_xlsx):
    r = clean_file(charges_xlsx)
    assert [x.get("unit") for x in r.rows] == ["A101", "A102", "A103", "A104"]
    a101 = r.rows[0]
    assert [c.code.value for c in a101.charges] == ["RENT", "PARK", "PET"]
    assert a101.get("current_rent") == Decimal("1450.00")
    assert a101.get("other_charges") == Decimal("110.00")
    assert a101.get("total_charges") == Decimal("1560.00")
    assert a101.values["current_rent"].derived
    assert [s.cell for s in a101.values["other_charges"].sources] == ["H5", "H6"]


def test_concession_lines_are_separated(charges_xlsx):
    a102 = clean_file(charges_xlsx).rows[1]
    assert a102.get("current_rent") == Decimal("1500.00")
    assert a102.get("concessions") == Decimal("-100.00")
    assert a102.get("total_charges") == Decimal("1400.00")
    assert a102.get("status") == "notice"


def test_total_ties_out_against_every_charge_line(charges_xlsx):
    r = clean_file(charges_xlsx)
    assert r.ok, rules(r, Severity.ERROR)
    tie = [i for i in r.issues if i.rule == "total_ties_out" and i.field == "charge_amount"]
    assert tie, "the Amount column total should be checked against all charge lines"


def test_vacant_unit_without_charges(charges_xlsx):
    a103 = clean_file(charges_xlsx).rows[2]
    assert a103.get("status") == "vacant"
    assert a103.charges == []


def test_amount_column_without_charge_codes_is_total_charges(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    for row in [["Unit", "Tenant", "Rent", "Charges"], ["101", "A", 1000, 1100]]:
        wb.active.append(row)
    wb.save(tmp_path / "c.xlsx")
    r = clean_file(tmp_path / "c.xlsx")
    assert {m.header: m.field for m in r.mappings}["Charges"] == "total_charges"
    assert r.rows[0].get("total_charges") == Decimal("1100.00")


# --- corrections ----------------------------------------------------------------------

def test_correction_overrides_value_and_keeps_original(flat_csv):
    review = Review()
    review.correct(6, "move_in", "02/01/2026", "Confirmed with property manager", author="kun")
    r = clean_file(flat_csv, review=review)
    row = next(x for x in r.rows if x.source_row == 6)
    tv = row.values["move_in"]
    assert tv.value == date(2026, 2, 1)
    assert tv.raw == "TBD" and tv.original is None
    assert tv.correction.author == "kun"
    assert "unparsed_value" not in rules(r)


def test_correction_can_make_a_total_tie_out(flat_csv):
    # The CSV's total says 7,025 but the rows sum to 6,975: unit 2A was really 1,625.
    review = Review()
    review.correct(6, "current_rent", "1,625.00", "Rent increase not yet in system")
    r = clean_file(flat_csv, review=review)
    assert "total_does_not_tie_out" not in rules(r)


def test_correction_rejects_unparseable_values_and_missing_reasons():
    review = Review()
    with pytest.raises(ValueError, match="Invalid value"):
        review.correct(2, "current_rent", "about 1000", "guess")
    with pytest.raises(ValueError, match="reason"):
        review.correct(2, "current_rent", "1000", "  ")
    with pytest.raises(ValueError, match="cannot be corrected"):
        review.correct(2, "charge_code", "RENT", "x")


def test_correction_on_missing_row_is_reported(flat_csv):
    review = Review()
    review.correct(99, "tenant", "Ghost", "test")
    assert "correction_orphaned" in rules(clean_file(flat_csv, review=review))


def test_corrected_tenant_drives_inferred_status(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    for row in [["Unit", "Tenant", "Rent"], ["101", "VACANT", 0]]:
        wb.active.append(row)
    wb.save(tmp_path / "t.xlsx")
    review = Review()
    review.correct(2, "tenant", "Lee, Jordan", "Moved in last week")
    review.correct(2, "current_rent", "1200", "Moved in last week")
    r = clean_file(tmp_path / "t.xlsx", review=review)
    # status was derived "vacant" from the VACANT marker; a corrected tenant doesn't silently change it
    assert r.rows[0].get("tenant") == "Lee, Jordan"


# --- mapping overrides --------------------------------------------------------------------

def test_mapping_override_moves_a_field(flat_csv):
    review = Review()
    review.override_mapping("Past Due", "other_charges")
    review.override_mapping("Deposit", None)
    r = clean_file(flat_csv, review=review)
    m = {x.header: (x.field, x.method) for x in r.mappings}
    assert m["Past Due"] == ("other_charges", "override")
    assert m["Deposit"] == (None, "unmapped")
    assert r.rows[2].get("other_charges") == Decimal("125.00")


def test_override_to_unknown_field_is_rejected():
    with pytest.raises(ValueError):
        Review().override_mapping("Rent", "rent_amount")


# --- acknowledgments and persistence --------------------------------------------------------

def test_acknowledging_errors_changes_ok_but_keeps_the_issue(flat_csv):
    first = clean_file(flat_csv)
    review = Review()
    for i in first.issues:
        if i.severity is Severity.ERROR:
            review.acknowledge(i.id, "Known issue in source system")
    second = clean_file(flat_csv, review=review)
    assert second.ok
    accepted = [i for i in second.issues if not i.open]
    assert len(accepted) == len([i for i in first.issues if i.severity is Severity.ERROR])
    assert second.summary()["acknowledged"] == len(accepted)


def test_issue_ids_are_stable_across_runs(flat_csv):
    assert [i.id for i in clean_file(flat_csv).issues] == [i.id for i in clean_file(flat_csv).issues]


def test_review_round_trips_and_audits(tmp_path):
    review = Review()
    review.override_mapping("Past Due", "other_charges", author="kun")
    review.correct(3, "tenant", "Lee, Jordan", "typo", author="kun")
    review.acknowledge("abc123", "fine", author="kun")
    path = tmp_path / "review.json"
    review.save(path)
    loaded = Review.load(path)
    assert loaded.to_dict() == review.to_dict()
    assert [e.action for e in loaded.audit] == ["override_mapping", "correct", "acknowledge"]
    assert Review.load(tmp_path / "missing.json").to_dict()["corrections"] == []


# --- metrics -------------------------------------------------------------------------------

def test_metrics_follow_underwriting_definitions(charges_xlsx):
    m = clean_file(charges_xlsx, as_of=date(2026, 11, 1)).metrics()
    assert m["units"] == 4 and m["occupied_units"] == 3
    assert m["physical_occupancy"] == 0.75
    assert m["gross_potential_rent"] == "7200.00"
    assert m["in_place_rent"] == "5000.00"                # 1450 + 1500 + 2050
    assert m["loss_to_lease"] == "100.00"                 # (1500-1450) + 0 + (2100-2050)
    assert m["vacancy_loss"] == "2100.00"
    assert m["economic_occupancy"] == round(5000 / 7200, 4)
    assert m["concessions"] == "-100.00"
    exp = m["lease_expirations"]
    assert exp["expired_or_mtm"] == 1                     # A102 ended 2026-02-28
    assert next(x for x in exp["by_month"] if x["month"] == "2026-12")["units"] == 1
    mix = {u["unit_type"]: u for u in m["unit_mix"]}
    assert mix["2x2"]["units"] == 2 and mix["2x2"]["occupied"] == 1
