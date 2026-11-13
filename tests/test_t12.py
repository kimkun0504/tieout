from datetime import date
from decimal import Decimal

import pytest

from samples import make_t12_xlsx
from tieout.ingest import read_grid
from tieout.t12 import categorize, is_t12, month_of, read_t12, tidy_rows, to_payload


def stmt(path):
    return read_t12(read_grid(path))


def test_clean_t12_ties_out_three_ways(tmp_path):
    s = stmt(make_t12_xlsx(tmp_path / "t12.xlsx"))
    assert s.ok, [i.message for i in s.issues]
    assert s.months[0] == date(2025, 11, 1) and s.months[-1] == date(2026, 10, 1)
    summary = s.summary()
    assert summary["line_items"] == 17 and summary["uncategorized"] == 0
    assert Decimal(summary["noi"]) == Decimal(summary["total_income"]) - Decimal(summary["total_expenses"])
    assert [ln.kind for ln in s.lines if ln.kind != "line"] == ["subtotal", "subtotal", "noi"]


def test_noi_error_is_found_and_located(tmp_path):
    s = stmt(make_t12_xlsx(tmp_path / "t12.xlsx", noi_off_by=250))
    [issue] = [i for i in s.issues if i.rule == "t12_noi_mismatch"]
    assert "Dec 2025" in issue.message and "difference 250.00" in issue.message
    assert issue.refs[0].cell == "D28"


def test_row_total_and_subtotal_errors(tmp_path):
    from openpyxl import load_workbook

    path = make_t12_xlsx(tmp_path / "t12.xlsx")
    wb = load_workbook(path)
    ws = wb.active
    ws["O6"] = ws["O6"].value + 100  # Gross Potential Rent's Total column
    ws["E7"] = ws["E7"].value - 40  # Loss to Lease, Jan 2026: breaks the row total and the income subtotal
    wb.save(path)
    s = stmt(path)
    rules = sorted({i.rule for i in s.issues if i.severity.value == "error"})
    assert rules == ["t12_row_total_mismatch", "t12_subtotal_mismatch"]
    sub = next(i for i in s.issues if i.rule == "t12_subtotal_mismatch")
    assert "Jan 2026" in sub.message and "difference 40.00" in sub.message


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Jan 2026", date(2026, 1, 1)),
        ("Jan-26", date(2026, 1, 1)),
        ("January 2026", date(2026, 1, 1)),
        ("01/2026", date(2026, 1, 1)),
        ("2026-01", date(2026, 1, 1)),
        ("Nov '25", date(2025, 11, 1)),
        ("Total", None),
        ("Account", None),
        ("13/2026", None),
    ],
)
def test_month_headers(raw, expected):
    assert month_of(raw) == expected


def test_csv_t12_with_text_months(tmp_path):
    months = ["Jan-26", "Feb-26", "Mar-26", "Apr-26", "May-26", "Jun-26"]
    lines = [
        ",".join(["Description", *months, "Total"]),
        "Revenue",
        ",".join(["Rental Income", *["10000"] * 6, "60000"]),
        ",".join(["Laundry", *["100"] * 6, "600"]),
        ",".join(["Total Revenue", *["10100"] * 6, "60600"]),
        "Expenses",
        ",".join(['"Repairs, General"', *['"1,000"'] * 6, '"6,000"']),
        ",".join(["Mystery Line", *["50"] * 6, "300"]),
        ",".join(["Total Expenses", *["1050"] * 6, "6300"]),
        ",".join(["Net Operating Income", *["9050"] * 6, "54300"]),
    ]
    path = tmp_path / "t12.csv"
    path.write_text("\n".join(lines) + "\n")
    grid = read_grid(path)
    assert is_t12(grid)
    s = read_t12(grid)
    assert s.ok
    assert [i.rule for i in s.issues if i.severity.value == "info"] == ["t12_not_twelve_months", "t12_uncategorized"]
    assert {ln.name: ln.category for ln in s.items()} == {
        "Rental Income": "gross_potential_rent",
        "Laundry": "other_income",
        "Repairs, General": "repairs_maintenance",
        "Mystery Line": None,
    }


def test_rent_roll_is_not_a_t12(stacked_xlsx):
    assert not is_t12(read_grid(stacked_xlsx))


def test_tidy_rows_and_payload(tmp_path):
    s = stmt(make_t12_xlsx(tmp_path / "t12.xlsx"))
    rows = tidy_rows(s)
    assert len(rows) == 17 * 12
    assert rows[0] == {
        "month": "2025-11",
        "section": "income",
        "category": "gross_potential_rent",
        "code": "4000",
        "line_item": "Gross Potential Rent",
        "amount": "52000.00",
        "source_cell": "C6",
        "source_row": 6,
    }
    payload = to_payload(s)
    assert payload["document_type"] == "t12" and len(payload["months"]) == 12


def test_categories_respect_sections():
    assert categorize("Water & Sewer", "expense") == "utilities"
    assert categorize("Utility Reimbursement", "income") == "other_income"
    assert categorize("Real Estate Taxes", "expense") == "real_estate_taxes"
    assert categorize("Parking", "expense") is None  # an income word in the expense section is not guessed


def test_cli_detects_a_t12(tmp_path, capsys):
    from tieout.cli import main

    path = make_t12_xlsx(tmp_path / "t12.xlsx", noi_off_by=100)
    code = main(["clean", str(path), "-o", str(tmp_path / "out"), "--strict"])
    out = capsys.readouterr().out
    assert code == 1 and "tieout T-12 report" in out and "t12_noi_mismatch" in out
    assert (tmp_path / "out" / "t12.t12.tidy.csv").exists()
