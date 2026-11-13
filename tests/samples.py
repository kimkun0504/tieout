"""Synthetic messy rent rolls for tests and demos.

All property, tenant and unit data here is invented. The layouts imitate common
problems in real exports, not any specific vendor's format.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook


def make_stacked_header_xlsx(path: Path) -> Path:
    """Title rows, a two-row merged header, building sections with subtotals,
    a repeated header, ALL-CAPS names, money as text, mixed date types.
    Every total ties out, so this file should produce no errors."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Rent Roll"
    ws.append(["Maple Court Apartments"])
    ws.append(["Rent Roll with Lease Charges"])
    ws.append(["As of 10/31/2026"])
    ws.append([])
    ws.append(
        ["Unit", "Unit Type", "Sq. Ft.", "Resident", "Market Rent", "Actual Rent", "Deposit", "Lease", None, "Move In"]
    )
    ws.append([None, None, None, None, None, None, None, "Start", "End", None])
    ws.merge_cells("H5:I5")

    ws.append(["Building A"])
    ws.append(
        [
            "101",
            "1x1",
            650,
            "GARCIA, MARIA",
            "$1,450.00",
            "$1,425.00",
            500,
            datetime(2026, 2, 1),
            datetime(2027, 1, 31),
            datetime(2024, 2, 1),
        ]
    )
    ws.append(["102", "1x1", 650, "VACANT", "$1,450.00", "0.00", None, None, None, None])
    ws.append(["103", "2x2", 980, "NGUYEN, DAVID", "1,895.00", "1,850.00", 750, "3/1/2026", "2/28/2027", "3/1/2025"])
    ws.append(["Total Building A", None, 2280, None, "$4,795.00", "$3,275.00", 1250])

    ws.append(
        ["Unit", "Unit Type", "Sq. Ft.", "Resident", "Market Rent", "Actual Rent", "Deposit", "Start", "End", "Move In"]
    )
    ws.append(["Building B"])
    ws.append(
        [
            101,
            "2x1",
            875,
            "O'BRIEN, SEAN",
            1650,
            1600,
            600,
            datetime(2025, 11, 15),
            datetime(2026, 11, 14),
            datetime(2023, 11, 15),
        ]
    )
    ws.append(
        [
            102,
            "2x2",
            990,
            "Patel, Anika",
            1900,
            1900,
            750,
            datetime(2026, 6, 1),
            datetime(2027, 5, 31),
            datetime(2026, 6, 1),
        ]
    )
    ws.append(["Total Building B", None, 1865, None, 3550, 3500, 1350])
    ws.append(["Grand Total", None, 4145, None, 8345, 6775, 2600])
    wb.save(path)
    return path


def make_flat_csv_with_problems(path: Path) -> Path:
    """Flat export with different column names, a status column, an unmapped
    column, and planted problems: a duplicate unit, reversed lease dates, an
    unreadable date, vacant-with-rent, and a total that is off by 50."""
    rows = [
        [
            "Unit",
            "Tenant",
            "Status",
            "Sq Ft",
            "Market Rent",
            "Rent",
            "Deposit",
            "Move-in",
            "Lease From",
            "Lease To",
            "Past Due",
        ],
        [
            "1A",
            "Lee, Jordan",
            "Current",
            "720",
            "1,300.00",
            "1,275.00",
            "500.00",
            "01/15/2024",
            "01/15/2026",
            "01/14/2027",
            "0.00",
        ],
        ["1B", "", "Vacant-Unrented", "720", "1,300.00", "1,300.00", "", "", "", "", ""],
        [
            "1C",
            "Brooks, Taylor",
            "Notice-Unrented",
            "810",
            "1,450.00",
            "1,400.00",
            "600.00",
            "06/01/2023",
            "06/01/2026",
            "05/31/2026",
            "125.00",
        ],
        [
            "1C",
            "Kim, Alex",
            "Current",
            "810",
            "1,450.00",
            "1,425.00",
            "600.00",
            "08/01/2025",
            "08/01/2025",
            "07/31/2026",
            "0.00",
        ],
        [
            "2A",
            "Rivera, Sam",
            "Current",
            "905",
            "1,600.00",
            "1,575.00",
            "650.00",
            "TBD",
            "02/01/2026",
            "01/31/2027",
            "0.00",
        ],
        ["Total", "", "", "3965", "7,100.00", "7,025.00", "2,350.00", "", "", "", "125.00"],
    ]
    with path.open("w", newline="") as f:
        csv.writer(f).writerows(rows)
    return path


def make_charge_lines_xlsx(path: Path) -> Path:
    """Charge-line layout: each unit's first row carries the unit and its first
    charge; extra charges (parking, pet, concessions) follow on rows with no
    unit. The total row reports the sum of every charge line."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Rent Roll"
    ws.append(["Birch Point Residences - Rent Roll with Lease Charges"])
    ws.append([])
    ws.append(
        [
            "Unit",
            "Unit Type",
            "Sq Ft",
            "Resident",
            "Status",
            "Market Rent",
            "Charge Code",
            "Amount",
            "Lease From",
            "Lease To",
        ]
    )
    ws.append(["A101", "1x1", 700, "Chen, Lily", "Occupied", 1500, "RENT", 1450, "1/1/2026", "12/31/2026"])
    ws.append([None, None, None, None, None, None, "PARK", 75])
    ws.append([None, None, None, None, None, None, "PET", 35])
    ws.append(["A102", "1x1", 700, "Okafor, Ben", "Occupied-NTV", 1500, "RENT", 1500, "3/1/2025", "2/28/2026"])
    ws.append([None, None, None, None, None, None, "CONC", -100])
    ws.append(["A103", "2x2", 1050, "VACANT", "Vacant", 2100])
    ws.append(["A104", "2x2", 1050, "Diaz, Rosa", "Occupied", 2100, "RENT", 2050, "7/1/2026", "6/30/2027"])
    ws.append(["Total", None, 3500, None, None, 7200, None, 5010])
    wb.save(path)
    return path


def make_pdf_rent_roll(path: Path, ruled: bool = True) -> Path:
    """A two-page PDF export: title, a table split across pages with the
    header repeated, page footers, and a grand total. `ruled=False` draws no
    grid lines, like many property-management PDF exports."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle

    header = ["Unit", "Type", "Sq Ft", "Resident", "Status", "Market Rent", "Rent", "Lease From", "Lease To"]
    units = [
        ["C101", "1x1", "680", "Novak, Petra", "Occupied", "1,525.00", "1,500.00", "02/01/2026", "01/31/2027"],
        ["C102", "1x1", "680", "VACANT", "Vacant", "1,525.00", "0.00", "", ""],
        ["C103", "2x1", "910", "Haddad, Omar", "Occupied", "1,875.00", "1,850.00", "05/01/2026", "04/30/2027"],
        ["C104", "2x2", "1,020", "Lindqvist, Mia", "Notice", "2,050.00", "1,995.00", "09/01/2025", "08/31/2026"],
        ["C105", "2x2", "1,020", "Osei, Kwame", "Occupied", "2,050.00", "2,050.00", "11/01/2026", "10/31/2027"],
        ["C106", "1x1", "680", "Reyes, Ana", "Occupied", "1,525.00", "1,475.00", "07/15/2026", "07/14/2027"],
    ]
    total = ["Total", "", "4,990", "", "", "10,550.00", "8,870.00", "", ""]
    style = getSampleStyleSheet()
    ts = [("FONTSIZE", (0, 0), (-1, -1), 9), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    if ruled:
        ts.append(("GRID", (0, 0), (-1, -1), 0.5, colors.grey))

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(36, 20, f"Page {doc.page} of 2")

    doc = SimpleDocTemplate(str(path), pagesize=landscape(letter))
    story = [
        Paragraph("Cedar Row Apartments - Rent Roll", style["Title"]),
        Table([header, *units[:3]], style=TableStyle(ts)),
        PageBreak(),
        Table([header, *units[3:], total], style=TableStyle(ts)),
    ]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return path


def make_t12_xlsx(path: Path, noi_off_by: int = 0) -> Path:
    """A trailing-12 operating statement: title rows, GL codes, month columns
    as real dates, Income and Expense sections with subtotals, NOI.
    `noi_off_by` plants an error in the December NOI."""
    from datetime import date as _date

    wb = Workbook()
    ws = wb.active
    ws.title = "T12"
    months = [_date(2025, m, 1) if m >= 11 else _date(2026, m - 0, 1) for m in (11, 12)] + [
        _date(2026, m, 1) for m in range(1, 11)
    ]
    ws.append(["Maple Court Apartments"])
    ws.append(["12 Month Statement - Nov 2025 through Oct 2026"])
    ws.append([])
    ws.append(["Account", "Description", *months, "Total"])
    lines = {
        "income": [
            ("4000", "Gross Potential Rent", 52000),
            ("4100", "Loss to Lease", -1500),
            ("4200", "Vacancy Loss", -2600),
            ("4300", "Concessions", -400),
            ("4500", "Parking Income", 900),
            ("4600", "Pet Fees", 350),
            ("4800", "Late Fees", 220),
        ],
        "expense": [
            ("6000", "Payroll & Benefits", 6200),
            ("6100", "Repairs & Maintenance", 2100),
            ("6200", "Contract Services - Landscaping", 800),
            ("6300", "Utilities - Electric", 1400),
            ("6310", "Water & Sewer", 1150),
            ("6400", "Management Fees", 1450),
            ("6500", "Real Estate Taxes", 5200),
            ("6600", "Property Insurance", 1900),
            ("6700", "Marketing & Advertising", 300),
            ("6800", "General & Administrative", 450),
        ],
    }

    def amounts(base: int, code: str) -> list[int]:
        # deterministic month-to-month variation
        return [base + ((int(code) // 10 + i * 37) % 9 - 4) * (abs(base) // 100) for i in range(12)]

    totals: dict[str, list[int]] = {}
    for section, title, total_label in (
        ("income", "INCOME", "Total Income"),
        ("expense", "OPERATING EXPENSES", "Total Operating Expenses"),
    ):
        ws.append([None, title])
        sums = [0] * 12
        for code, name, base in lines[section]:
            a = amounts(base, code)
            sums = [x + y for x, y in zip(sums, a, strict=True)]
            ws.append([code, name, *a, sum(a)])
        ws.append([None, total_label, *sums, sum(sums)])
        totals[section] = sums
        ws.append([])
    noi = [i - e for i, e in zip(totals["income"], totals["expense"], strict=True)]
    noi[1] += noi_off_by
    ws.append([None, "Net Operating Income", *noi, sum(noi)])
    wb.save(path)
    return path
