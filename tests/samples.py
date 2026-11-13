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
    ws.append(["Unit", "Unit Type", "Sq. Ft.", "Resident", "Market Rent", "Actual Rent", "Deposit", "Lease", None, "Move In"])
    ws.append([None, None, None, None, None, None, None, "Start", "End", None])
    ws.merge_cells("H5:I5")

    ws.append(["Building A"])
    ws.append(["101", "1x1", 650, "GARCIA, MARIA", "$1,450.00", "$1,425.00", 500, datetime(2026, 2, 1), datetime(2027, 1, 31), datetime(2024, 2, 1)])
    ws.append(["102", "1x1", 650, "VACANT", "$1,450.00", "0.00", None, None, None, None])
    ws.append(["103", "2x2", 980, "NGUYEN, DAVID", "1,895.00", "1,850.00", 750, "3/1/2026", "2/28/2027", "3/1/2025"])
    ws.append(["Total Building A", None, 2280, None, "$4,795.00", "$3,275.00", 1250])

    ws.append(["Unit", "Unit Type", "Sq. Ft.", "Resident", "Market Rent", "Actual Rent", "Deposit", "Start", "End", "Move In"])
    ws.append(["Building B"])
    ws.append([101, "2x1", 875, "O'BRIEN, SEAN", 1650, 1600, 600, datetime(2025, 11, 15), datetime(2026, 11, 14), datetime(2023, 11, 15)])
    ws.append([102, "2x2", 990, "Patel, Anika", 1900, 1900, 750, datetime(2026, 6, 1), datetime(2027, 5, 31), datetime(2026, 6, 1)])
    ws.append(["Total Building B", None, 1865, None, 3550, 3500, 1350])
    ws.append(["Grand Total", None, 4145, None, 8345, 6775, 2600])
    wb.save(path)
    return path


def make_flat_csv_with_problems(path: Path) -> Path:
    """Flat export with different column names, a status column, an unmapped
    column, and planted problems: a duplicate unit, reversed lease dates, an
    unreadable date, vacant-with-rent, and a total that is off by 50."""
    rows = [
        ["Unit", "Tenant", "Status", "Sq Ft", "Market Rent", "Rent", "Deposit", "Move-in", "Lease From", "Lease To", "Past Due"],
        ["1A", "Lee, Jordan", "Current", "720", "1,300.00", "1,275.00", "500.00", "01/15/2024", "01/15/2026", "01/14/2027", "0.00"],
        ["1B", "", "Vacant-Unrented", "720", "1,300.00", "1,300.00", "", "", "", "", ""],
        ["1C", "Brooks, Taylor", "Notice-Unrented", "810", "1,450.00", "1,400.00", "600.00", "06/01/2023", "06/01/2026", "05/31/2026", "125.00"],
        ["1C", "Kim, Alex", "Current", "810", "1,450.00", "1,425.00", "600.00", "08/01/2025", "08/01/2025", "07/31/2026", "0.00"],
        ["2A", "Rivera, Sam", "Current", "905", "1,600.00", "1,575.00", "650.00", "TBD", "02/01/2026", "01/31/2027", "0.00"],
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
    ws.append(["Unit", "Unit Type", "Sq Ft", "Resident", "Status", "Market Rent", "Charge Code", "Amount", "Lease From", "Lease To"])
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
