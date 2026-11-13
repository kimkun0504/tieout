from datetime import date
from decimal import Decimal

from tieout import clean_file
from tieout.export import write_all
from tieout.mapping import TemplateStore
from tieout.models import Severity


def rules(result, severity=None):
    return [i.rule for i in result.issues if severity is None or i.severity is severity]


# --- stacked-header workbook: everything should tie out ---------------------

def test_finds_two_row_header_below_title_rows(stacked_xlsx):
    r = clean_file(stacked_xlsx)
    assert [x + 1 for x in r.header.header_rows] == [5, 6]
    fields = {m.header: m.field for m in r.mappings}
    assert fields["Lease Start"] == "lease_start"
    assert fields["Lease End"] == "lease_end"
    assert fields["Resident"] == "tenant"
    assert fields["Actual Rent"] == "current_rent"
    assert fields["Sq. Ft."] == "sqft"


def test_skips_sections_subtotals_and_repeated_header(stacked_xlsx):
    r = clean_file(stacked_xlsx)
    assert len(r.rows) == 5
    assert [row.section for row in r.rows] == ["Building A"] * 3 + ["Building B"] * 2
    assert r.skipped.get("repeated_header") == 1
    assert len(r.totals) == 3


def test_all_totals_tie_out(stacked_xlsx):
    r = clean_file(stacked_xlsx)
    assert r.ok, rules(r, Severity.ERROR)
    assert "total_ties_out" in rules(r)
    grand = r.totals[-1]
    assert grand.label == "Grand Total"
    assert len(grand.scope_rows) == 5


def test_values_are_typed_and_tidied(stacked_xlsx):
    r = clean_file(stacked_xlsx)
    first = r.rows[0]
    assert first.get("tenant") == "Garcia, Maria"
    assert first.get("market_rent") == Decimal("1450.00")
    assert first.get("lease_start") == date(2026, 2, 1)
    third = r.rows[2]
    assert third.get("lease_start") == date(2026, 3, 1)  # parsed from text "3/1/2026"
    b101 = r.rows[3]
    assert b101.get("unit") == "101"  # numeric 101 in Excel becomes text "101"
    assert b101.get("tenant") == "O'Brien, Sean"


def test_vacant_marker_in_tenant_column_becomes_status(stacked_xlsx):
    r = clean_file(stacked_xlsx)
    vacant = r.rows[1]
    assert vacant.get("tenant") is None
    assert vacant.get("status") == "vacant"
    assert vacant.values["status"].derived


def test_every_value_points_to_its_source_cell(stacked_xlsx):
    r = clean_file(stacked_xlsx)
    rent = r.rows[0].values["current_rent"]
    assert rent.source.cell == "F8"
    assert rent.raw == "$1,425.00"


def test_same_unit_number_in_different_buildings_is_not_a_duplicate(stacked_xlsx):
    r = clean_file(stacked_xlsx)
    assert "duplicate_unit" not in rules(r)


def test_summary(stacked_xlsx):
    s = clean_file(stacked_xlsx).summary()
    assert s["units"] == 5
    assert s["status_counts"] == {"occupied": 4, "vacant": 1}
    assert s["physical_occupancy"] == 0.8
    assert s["total_current_rent"] == 6775.0


# --- flat CSV with planted problems ----------------------------------------

def test_flat_csv_maps_alternate_names(flat_csv):
    r = clean_file(flat_csv)
    fields = {m.header: m.field for m in r.mappings}
    assert fields["Tenant"] == "tenant"
    assert fields["Rent"] == "current_rent"
    assert fields["Lease From"] == "lease_start"
    assert fields["Lease To"] == "lease_end"
    assert fields["Past Due"] is None


def test_catches_planted_problems(flat_csv):
    r = clean_file(flat_csv)
    errors = rules(r, Severity.ERROR)
    warnings = rules(r, Severity.WARNING)
    assert not r.ok
    assert "duplicate_unit" in errors
    assert "lease_dates_reversed" in errors
    assert "vacant_with_rent" in warnings
    assert "unparsed_value" in warnings


def test_total_off_by_fifty_is_reported(flat_csv):
    r = clean_file(flat_csv)
    tie = [i for i in r.issues if i.rule == "total_does_not_tie_out"]
    assert len(tie) == 1
    assert tie[0].field == "current_rent"
    assert "difference 50.00" in tie[0].message
    assert tie[0].refs[0].cell == "F7"  # the Total row


def test_status_words_normalized(flat_csv):
    r = clean_file(flat_csv)
    assert [row.get("status") for row in r.rows] == ["occupied", "vacant", "notice", "occupied", "occupied"]


def test_lease_expiry_needs_as_of(flat_csv):
    assert "lease_expired" not in rules(clean_file(flat_csv))
    assert "lease_expired" in rules(clean_file(flat_csv, as_of=date(2026, 11, 1)))


# --- templates and export ----------------------------------------------------

def test_saved_template_is_reused(stacked_xlsx, tmp_path):
    store = TemplateStore(tmp_path / "templates")
    first = clean_file(stacked_xlsx)
    store.save(first.header.headers, first.mappings, "maple-court")
    second = clean_file(stacked_xlsx, templates=store)
    assert {m.method for m in second.mappings if m.field} == {"template"}
    assert [m.field for m in second.mappings] == [m.field for m in first.mappings]


def test_writes_all_outputs(flat_csv, tmp_path):
    paths = write_all(clean_file(flat_csv), tmp_path / "out")
    for p in paths.values():
        assert p.exists() and p.stat().st_size > 0
    assert paths["csv"].read_text().splitlines()[0].startswith("unit,unit_type,sqft,tenant")
    assert "NEEDS REVIEW" in paths["report"].read_text()


# --- regression tests for review findings ------------------------------------------

def _xlsx(tmp_path, rows, merges=(), name="t.xlsx"):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    for m in merges:
        ws.merge_cells(m)
    path = tmp_path / name
    wb.save(path)
    return path


def test_merged_section_label_is_not_a_unit(tmp_path):
    """Finding 2: a section label merged across the row used to fill every column and become a unit."""
    path = _xlsx(tmp_path, [
        ["Unit", "Tenant", "Market Rent", "Rent", "Lease Start", "Lease End"],
        ["Building A"],
        ["101", "Lee", 1000, 1000, None, None],
        ["Total", None, 1000, 1000],
    ], merges=["A2:F2"])
    r = clean_file(path)
    assert [x.get("unit") for x in r.rows] == ["101"]
    assert r.rows[0].section == "Building A"
    assert r.ok


def test_uncomputed_formula_total_is_an_error_not_a_silent_pass(tmp_path):
    """Finding 7: formulas with no saved result read as empty and skipped the tie-out."""
    path = _xlsx(tmp_path, [["Unit", "Tenant", "Rent"], ["101", "A", 1000], ["102", "B", 2000], ["Total", None, "=SUM(C2:C3)"]])
    r = clean_file(path)
    assert not r.ok
    issue = next(i for i in r.issues if i.rule == "total_not_checkable")
    assert issue.refs[0].cell == "C4"


def test_csv_quoted_field_keeps_its_line_break(tmp_path):
    """Finding 13: splitlines() glued multi-line quoted fields together."""
    path = tmp_path / "ml.csv"
    path.write_text('Unit,Tenant,Rent\n101,"Lee, Jordan\nc/o Jane Lee",1000\n102,Kim,1100\n', newline="")
    r = clean_file(path)
    assert [x.get("unit") for x in r.rows] == ["101", "102"]
    assert r.rows[0].get("tenant") == "Lee, Jordan c/o Jane Lee"  # whitespace collapsed, words kept apart


def test_tenant_named_total_stays_a_unit(tmp_path):
    """Finding 3: 'Total Wine & More' deleted unit 101 and became a fake subtotal."""
    path = _xlsx(tmp_path, [["Unit", "Tenant", "Rent"], ["101", "Total Wine & More", 5000], ["102", "Acme", 3000], ["Total", None, 8000]])
    r = clean_file(path)
    assert [x.get("unit") for x in r.rows] == ["101", "102"]
    assert [t.label for t in r.totals] == ["Total"]
    assert r.ok


def test_repeated_header_with_total_column_is_not_a_subtotal(tmp_path):
    """Finding 4: 'Total Charges' in a repeated header reset the subtotal scope."""
    h = ["Unit", "Tenant", "Rent", "Total Charges"]
    path = _xlsx(tmp_path, [h, ["101", "A", 1000, 1000], h, ["102", "B", 2000, 2000], ["Total", None, 3000, 3000]])
    r = clean_file(path)
    assert r.skipped.get("repeated_header") == 1
    assert len(r.totals) == 1 and len(r.totals[0].scope_rows) == 2
    assert r.ok


def test_page_footer_does_not_hide_duplicates(tmp_path):
    """Finding 12: 'Page 2 of 2' became a section, so duplicates across pages were missed."""
    path = _xlsx(tmp_path, [["Unit", "Tenant", "Rent"], ["101", "A", 1000], ["Page 2 of 2"], ["101", "A", 1000]])
    r = clean_file(path)
    assert {x.section for x in r.rows} == {None}
    assert "duplicate_unit" in rules(r, Severity.ERROR)


def test_second_total_line_reuses_the_same_rows(tmp_path):
    """Two consecutive total rows for one group (rent line, then deposit line)."""
    path = _xlsx(tmp_path, [
        ["Unit", "Tenant", "Rent", "Deposit"],
        ["101", "A", 1000, 500], ["102", "B", 2000, 700],
        ["Total", None, 3000, None],
        ["Total", None, None, 1200],
    ])
    r = clean_file(path)
    assert [len(t.scope_rows) for t in r.totals] == [2, 2]
    assert r.ok
