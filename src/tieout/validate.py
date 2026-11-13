"""Validation rules. Each rule looks at cleaned rows and returns issues.

The rule that gives the project its name: reported totals must tie out to the
sum of the rows they cover.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from tieout.mapping import ColumnMapping
from tieout.models import CleanRow, Issue, ReportedTotal, Severity
from tieout.schema import FIELDS_BY_NAME

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
    issues += check_tie_out(rows, totals)
    order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    issues.sort(key=lambda i: (order[i.severity], i.row or 0))
    return issues


def check_mapping(mappings: list[ColumnMapping]) -> list[Issue]:
    issues = []
    mapped = {m.field for m in mappings if m.field}
    for spec in FIELDS_BY_NAME.values():
        if spec.required and spec.name not in mapped:
            issues.append(Issue(Severity.ERROR, "required_column_missing", f"No column found for required field '{spec.name}'."))
    for m in mappings:
        if m.field and m.confidence < 0.9:
            issues.append(
                Issue(Severity.INFO, "low_confidence_mapping",
                      f"Column '{m.header}' mapped to '{m.field}' with confidence {m.confidence:.2f} ({m.method}); please confirm.",
                      field=m.field)
            )
        if not m.field and m.header:
            issues.append(Issue(Severity.INFO, "unmapped_column", f"Column '{m.header}' was not mapped and is not in the output."))
    return issues


def check_parse_issues(rows: list[CleanRow]) -> list[Issue]:
    issues = []
    for row in rows:
        for name, tv in row.values.items():
            if tv.issue:
                issues.append(Issue(Severity.WARNING, "unparsed_value", f"{name}: {tv.issue}", row.source_row, name,
                                    [tv.source] if tv.source else []))
    return issues


def check_duplicates(rows: list[CleanRow]) -> list[Issue]:
    seen: dict[str, list[CleanRow]] = defaultdict(list)
    for row in rows:
        unit = row.get("unit")
        if unit:
            # Same unit number in different buildings is legitimate.
            seen[f"{row.section or ''}::{str(unit).strip().lower()}"].append(row)
    issues = []
    for key, dup_rows in seen.items():
        if len(dup_rows) > 1:
            unit = dup_rows[0].get("unit")
            src = [str(r.source_row) for r in dup_rows]
            issues.append(Issue(Severity.ERROR, "duplicate_unit", f"Unit '{unit}' appears {len(dup_rows)} times (rows {', '.join(src)}).",
                                dup_rows[1].source_row, "unit"))
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
            issues.append(Issue(Severity.WARNING, "vacant_with_rent", f"Unit {unit} is vacant but shows rent {rent}.", r, "current_rent"))
        if status in ("occupied", "notice") and not row.get("tenant"):
            issues.append(Issue(Severity.WARNING, "occupied_without_tenant", f"Unit {unit} is {status} but has no tenant name.", r, "tenant"))
        if status in ("occupied", "notice") and (rent is None or rent == 0):
            issues.append(Issue(Severity.WARNING, "occupied_without_rent", f"Unit {unit} is {status} but has no rent.", r, "current_rent"))
        if rent is not None and rent < 0:
            issues.append(Issue(Severity.ERROR, "negative_rent", f"Unit {unit} has negative rent {rent}.", r, "current_rent"))
        if start and end and end < start:
            issues.append(Issue(Severity.ERROR, "lease_dates_reversed", f"Unit {unit}: lease ends {end} before it starts {start}.", r, "lease_end"))
        if market and rent and market > 0 and status != "vacant":
            deviation = abs(rent - market) / market
            if deviation > RENT_DEVIATION_LIMIT:
                issues.append(Issue(Severity.WARNING, "rent_far_from_market",
                                    f"Unit {unit}: rent {rent} is {deviation:.0%} away from market {market}.", r, "current_rent"))
        if as_of and end and end < as_of and status in ("occupied", "notice"):
            issues.append(Issue(Severity.INFO, "lease_expired", f"Unit {unit}: lease ended {end} but unit is {status} (month-to-month?).", r, "lease_end"))
    return issues


def check_tie_out(rows: list[CleanRow], totals: list[ReportedTotal]) -> list[Issue]:
    by_row = {r.source_row: r for r in rows}
    issues = []
    for total in totals:
        for name, reported in total.amounts.items():
            if reported.value is None:
                if reported.issue:
                    issues.append(Issue(Severity.ERROR, "total_not_checkable",
                                        f"'{total.label}' {name} could not be checked: {reported.issue}.",
                                        total.row, name, [reported.source] if reported.source else []))
                continue
            spec = FIELDS_BY_NAME.get(name)
            if spec is None or spec.type.value not in ("money", "number"):
                continue
            computed = sum(
                (Decimal(str(by_row[r].get(name))) for r in total.scope_rows if r in by_row and by_row[r].get(name) is not None),
                Decimal("0"),
            )
            diff = Decimal(str(reported.value)) - computed
            if abs(diff) > TIE_OUT_TOLERANCE:
                issues.append(Issue(
                    Severity.ERROR, "total_does_not_tie_out",
                    f"'{total.label}' reports {name} = {reported.value}, but the {len(total.scope_rows)} rows it covers sum to {computed} (difference {diff}).",
                    total.row, name, [reported.source] if reported.source else []))
            else:
                issues.append(Issue(Severity.INFO, "total_ties_out",
                                    f"'{total.label}' {name} = {reported.value} ties out to its {len(total.scope_rows)} rows.",
                                    total.row, name))
    return issues
