"""Validation rules. Each rule looks at cleaned rows and returns issues.

The rule that gives the project its name: reported totals must tie out to the
sum of the rows they cover.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from statistics import median

from tieout.mapping import ColumnMapping
from tieout.models import CleanRow, Issue, ReportedTotal, Severity
from tieout.schema import FIELDS_BY_NAME

_LABELS = {"current_rent": "rent", "sqft": "sq ft", "charge_amount": "charges", "market_rent": "market rent"}


def label(name: str | None) -> str:
    """Field name as a reviewer would say it: current_rent -> 'rent'."""
    if name is None:
        return ""
    return _LABELS.get(name, name.replace("_", " "))


def show(value: object) -> str:
    """Amounts with thousands separators; dates as 'May 31, 2026'."""
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,}"
    if isinstance(value, date):
        return f"{value:%b} {value.day}, {value.year}"
    return str(value)


TIE_OUT_TOLERANCE = Decimal("0.01")
RENT_DEVIATION_LIMIT = Decimal("0.40")  # flag rent more than 40% away from market


def run_all(
    rows: list[CleanRow],
    totals: list[ReportedTotal],
    mappings: list[ColumnMapping],
    as_of: date | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    issues += check_mapping(mappings)
    issues += check_parse_issues(rows)
    issues += check_duplicates(rows)
    issues += check_row_rules(rows, as_of)
    issues += check_outliers(rows)
    issues += check_tie_out(rows, totals)
    order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    issues.sort(key=lambda i: (order[i.severity], i.row or 0))
    return issues


def check_mapping(mappings: list[ColumnMapping]) -> list[Issue]:
    issues = []
    mapped = {m.field for m in mappings if m.field}
    if {"charge_code", "charge_amount"} <= mapped:
        mapped = mapped | {"current_rent"}  # rolled up from rent charge lines
    for spec in FIELDS_BY_NAME.values():
        if spec.required and spec.name not in mapped:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "required_column_missing",
                    f"No column found for {label(spec.name)}, which is required.",
                )
            )
    if "status" not in mapped:
        source = "tenant names" if "tenant" in mapped else "rent amounts" if "current_rent" in mapped else None
        msg = (
            f"No status column: occupancy is inferred from {source}; please confirm."
            if source
            else "No status, tenant or rent column: occupancy cannot be determined."
        )
        issues.append(Issue(Severity.INFO if source else Severity.WARNING, "status_inferred", msg, field="status"))
    for m in mappings:
        if m.field and m.confidence < 0.9:
            issues.append(
                Issue(
                    Severity.INFO,
                    "low_confidence_mapping",
                    f"Column '{m.header}' is read as {label(m.field)}, but only with confidence {m.confidence:.0%} "
                    "; please confirm.",
                    field=m.field,
                )
            )
        if not m.field and m.header:
            issues.append(
                Issue(Severity.INFO, "unmapped_column", f"Column '{m.header}' was not mapped and is not in the output.")
            )
    return issues


def check_parse_issues(rows: list[CleanRow]) -> list[Issue]:
    issues = []
    for row in rows:
        for name, tv in row.values.items():
            if tv.issue:
                issues.append(
                    Issue(
                        Severity.WARNING,
                        "unparsed_value",
                        f"{label(name).capitalize()}: {tv.issue}",
                        row.source_row,
                        name,
                        [tv.source] if tv.source else [],
                    )
                )
    return issues


def check_duplicates(rows: list[CleanRow]) -> list[Issue]:
    seen: dict[str, list[CleanRow]] = defaultdict(list)
    for row in rows:
        unit = row.get("unit")
        if unit:
            # Same unit number in different buildings is legitimate.
            seen[f"{row.section or ''}::{str(unit).strip().lower()}"].append(row)
    issues = []
    for dup_rows in seen.values():
        if len(dup_rows) > 1:
            unit = dup_rows[0].get("unit")
            src = [str(r.source_row) for r in dup_rows]
            issues.append(
                Issue(
                    Severity.ERROR,
                    "duplicate_unit",
                    f"Unit '{unit}' appears {len(dup_rows)} times (rows {', '.join(src)}).",
                    dup_rows[1].source_row,
                    "unit",
                )
            )
    return issues


def check_row_rules(rows: list[CleanRow], as_of: date | None) -> list[Issue]:
    issues = []
    for row in rows:
        r = row.source_row
        unit = row.get("unit")
        status = row.get("status")
        rent = row.get("current_rent")
        market = row.get("market_rent")
        start, end = row.get("lease_start"), row.get("lease_end")

        if not unit:
            issues.append(Issue(Severity.ERROR, "missing_unit", "Row has data but no unit identifier.", r, "unit"))
        if status == "vacant" and rent and rent > 0:
            issues.append(
                Issue(
                    Severity.WARNING,
                    "vacant_with_rent",
                    f"Unit {unit} is vacant but shows rent of {show(rent)}.",
                    r,
                    "current_rent",
                )
            )
        if status in ("occupied", "notice") and "tenant" in row.values and not row.get("tenant"):
            issues.append(
                Issue(
                    Severity.WARNING,
                    "occupied_without_tenant",
                    f"Unit {unit} is {status} but has no tenant name.",
                    r,
                    "tenant",
                )
            )
        if status in ("occupied", "notice") and (rent is None or rent == 0):
            issues.append(
                Issue(
                    Severity.WARNING,
                    "occupied_without_rent",
                    f"Unit {unit} is {status} but has no rent.",
                    r,
                    "current_rent",
                )
            )
        if rent is not None and rent < 0:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "negative_rent",
                    f"Unit {unit} has negative rent of {show(rent)}.",
                    r,
                    "current_rent",
                )
            )
        if start and end and end < start:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "lease_dates_reversed",
                    f"Unit {unit}: lease ends {show(end)}, before it starts on {show(start)}.",
                    r,
                    "lease_end",
                )
            )
        if market and rent and market > 0 and status != "vacant":
            deviation = abs(rent - market) / market
            if deviation > RENT_DEVIATION_LIMIT:
                issues.append(
                    Issue(
                        Severity.WARNING,
                        "rent_far_from_market",
                        f"Unit {unit}: rent of {show(rent)} is {deviation:.0%} away from "
                        f"market rent of {show(market)}.",
                        r,
                        "current_rent",
                    )
                )
        move_in = row.get("move_in")
        if as_of and move_in and move_in > as_of and status in ("occupied", "notice"):
            issues.append(
                Issue(
                    Severity.WARNING,
                    "move_in_after_report_date",
                    f"Unit {unit} is {status} but its move-in date {show(move_in)} is after the report date "
                    f"{show(as_of)}.",
                    r,
                    "move_in",
                )
            )
        if as_of and end and end < as_of and status in ("occupied", "notice"):
            issues.append(
                Issue(
                    Severity.INFO,
                    "lease_expired",
                    f"Unit {unit}: lease ended {show(end)} but the unit is {status} (month to month?).",
                    r,
                    "lease_end",
                )
            )
    return issues


OUTLIER_LIMIT = Decimal("0.50")  # rent per sq ft more than 50% from its unit type's median
OUTLIER_MIN_GROUP = 5


def check_outliers(rows: list[CleanRow]) -> list[Issue]:
    """Flag rent per sq ft far from the median of comparable units.

    A misplaced decimal (145.00 for 1,450.00) or a rent typed into the wrong
    unit usually passes every other rule; against its peers it stands out.
    Units are compared within their unit type, and only in groups of five or
    more, so small or mixed properties don't produce noise.
    """
    groups: dict[str, list[tuple[CleanRow, Decimal]]] = defaultdict(list)
    for row in rows:
        rent, sqft = row.get("current_rent"), row.get("sqft")
        if row.get("status") in ("occupied", "notice") and rent and rent > 0 and sqft and sqft > 0:
            groups[str(row.get("unit_type") or "")].append((row, rent / Decimal(str(sqft))))
    issues = []
    for unit_type, members in groups.items():
        if len(members) < OUTLIER_MIN_GROUP:
            continue
        mid = Decimal(str(median(float(v) for _, v in members)))
        if mid <= 0:
            continue
        for row, per_sf in members:
            deviation = abs(per_sf - mid) / mid
            if deviation > OUTLIER_LIMIT:
                peers = f"{unit_type} units" if unit_type else "comparable units"
                issues.append(
                    Issue(
                        Severity.WARNING,
                        "rent_per_sqft_outlier",
                        f"Unit {row.get('unit')}: {show(per_sf.quantize(Decimal('0.01')))} per sq ft is "
                        f"{deviation:.0%} away from the median of {show(mid.quantize(Decimal('0.01')))} for {peers}.",
                        row.source_row,
                        "current_rent",
                    )
                )
    return issues


def check_tie_out(rows: list[CleanRow], totals: list[ReportedTotal]) -> list[Issue]:
    by_row = {r.source_row: r for r in rows}
    issues = []
    for total in totals:
        for name, reported in total.amounts.items():
            if reported.value is None:
                if reported.issue:
                    issues.append(
                        Issue(
                            Severity.ERROR,
                            "total_not_checkable",
                            f"'{total.label}' {label(name)} could not be checked: {reported.issue}.",
                            total.row,
                            name,
                            [reported.source] if reported.source else [],
                        )
                    )
                continue
            spec = FIELDS_BY_NAME.get(name)
            if spec is None or spec.type.value not in ("money", "number"):
                continue
            computed = sum(
                (row_amount(by_row[r], name) for r in total.scope_rows if r in by_row),
                Decimal("0"),
            )
            diff = Decimal(str(reported.value)) - computed
            if abs(diff) > TIE_OUT_TOLERANCE:
                issues.append(
                    Issue(
                        Severity.ERROR,
                        "total_does_not_tie_out",
                        f"'{total.label}' reports {label(name)} of {show(reported.value)}, "
                        f"but the {len(total.scope_rows)} units "
                        f"it covers add up to {show(computed)} (difference {show(diff)}).",
                        total.row,
                        name,
                        [reported.source] if reported.source else [],
                    )
                )
            else:
                issues.append(
                    Issue(
                        Severity.INFO,
                        "total_ties_out",
                        f"'{total.label}' {label(name)} of {show(reported.value)} ties out "
                        f"to its {len(total.scope_rows)} units.",
                        total.row,
                        name,
                    )
                )
    return issues


def row_amount(row: CleanRow, name: str) -> Decimal:
    """A row's contribution to a reported total. Charge-line totals add every line.

    Uses reviewer-corrected values: when a cell was misread, correcting it is
    exactly what should make the total tie out.
    """
    if name == "charge_amount":
        return sum((ch.amount.value for ch in row.charges if ch.amount.value is not None), Decimal("0"))
    value = row.get(name)
    return Decimal(str(value)) if value is not None else Decimal("0")
