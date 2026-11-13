"""Validation rules. Each rule looks at cleaned rows and returns issues.

The rule that gives the project its name: reported totals must tie out to the
sum of the rows they cover.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from statistics import median

from tieout.mapping import ColumnMapping
from tieout.models import CleanRow, Issue, ReportedTotal, Severity, StatedFigure
from tieout.schema import FIELDS_BY_NAME

_LABELS = {
    "current_rent": "rent",
    "sqft": "sq ft",
    "charge_amount": "charges",
    "market_rent": "market rent",
    "annual_rent": "annual rent",
}


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
    current = [r for r in rows if r.current]
    future = [r for r in rows if not r.current]
    issues += check_duplicates(current) + check_duplicates(future)  # a future lease repeats its unit
    issues += check_row_rules(rows, as_of)
    issues += check_outliers(current)
    issues += check_cross_fields(rows)
    issues += check_tie_out(rows, totals)
    order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    issues.sort(key=lambda i: (order[i.severity], i.row or 0))
    return issues


def check_mapping(mappings: list[ColumnMapping]) -> list[Issue]:
    issues = []
    mapped = {m.field for m in mappings if m.field}
    if {"charge_code", "charge_amount"} <= mapped or "annual_rent" in mapped:
        mapped = mapped | {"current_rent"}  # rolled up from rent charge lines, or annual / 12
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


_UNIT_PREFIX = re.compile(r"^(?:apt\.?|apartment|unit|suite|ste\.?|no\.?|space|#)\s*#?\s*", re.I)


def unit_key(unit: object) -> str:
    """Loose identity for a unit code: "Apt 101", "Unit #101", "#101" and "101" are the same unit;
    so are "A-101", "A 101" and "a101"; leading zeros in a number don't count ("0101")."""
    text = str(unit).strip().lower()
    while True:
        stripped = _UNIT_PREFIX.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped
    text = re.sub(r"[\s\-_./]+", "", text)
    return re.sub(r"(?<![0-9])0+(?=\d)", "", text) or text


def check_duplicates(rows: list[CleanRow]) -> list[Issue]:
    """Exact repeats of a unit code are errors; codes that differ only in spelling are warnings."""
    exact: dict[str, list[CleanRow]] = defaultdict(list)
    loose: dict[str, list[CleanRow]] = defaultdict(list)
    for row in rows:
        unit = row.get("unit")
        if unit:
            # Same unit number in different buildings is legitimate.
            scope = row.section or ""
            exact[f"{scope}::{str(unit).strip().lower()}"].append(row)
            loose[f"{scope}::{unit_key(unit)}"].append(row)
    issues = []
    for dup_rows in exact.values():
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
    for dup_rows in loose.values():
        spellings = {str(r.get("unit")).strip().lower() for r in dup_rows}
        if len(spellings) > 1:
            names = ", ".join(f"'{r.get('unit')}' (row {r.source_row})" for r in dup_rows)
            issues.append(
                Issue(
                    Severity.WARNING,
                    "possible_duplicate_unit",
                    f"These unit codes may be the same unit written differently: {names}.",
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


CROSS_CHECK_TOLERANCE = Decimal("1.00")


def check_cross_fields(rows: list[CleanRow]) -> list[Issue]:
    """When a file states the same number two ways, the two must agree."""
    issues = []
    for row in rows:
        unit, r = row.get("unit"), row.source_row
        rent_tv = row.values.get("current_rent")
        rent = row.get("current_rent")
        annual = row.get("annual_rent")
        if annual is not None and rent is not None and rent_tv is not None and not rent_tv.derived:
            gap = annual - rent * 12
            if abs(gap) > CROSS_CHECK_TOLERANCE:
                issues.append(
                    Issue(
                        Severity.WARNING,
                        "annual_monthly_mismatch",
                        f"Unit {unit}: annual rent {show(annual)} is not 12 x monthly rent {show(rent)} "
                        f"(difference {show(gap)}).",
                        r,
                        "annual_rent",
                    )
                )
        psf_tv = row.values.get("rent_psf")
        psf, sqft = row.get("rent_psf"), row.get("sqft")
        yearly = annual if annual is not None else (rent * 12 if rent is not None else None)
        if psf_tv is not None and psf is not None and sqft and yearly is not None and yearly > 0 and psf > 0:
            expected = psf * Decimal(str(sqft))
            # A rate printed to the cent can be off by half a cent per foot (x12 if it was monthly).
            tolerance = Decimal("0.005") * Decimal(str(sqft)) * (12 if psf_tv.derived else 1) + Decimal(1)
            if abs(expected - yearly) > tolerance:
                issues.append(
                    Issue(
                        Severity.WARNING,
                        "rent_psf_mismatch",
                        f"Unit {unit}: {show(psf)}/SF x {sqft:,} SF is {show(expected)} a year, but its rent is "
                        f"{show(yearly)} a year ({show(yearly / Decimal(str(sqft)))}/SF).",
                        r,
                        "rent_psf",
                    )
                )
        rent_lines = [c.amount.value for c in row.charges if c.category == "rent" and c.amount.value is not None]
        if (
            rent_lines
            and rent is not None
            and rent_tv is not None
            and not rent_tv.derived
            and rent_tv.correction is None
        ):
            charged = sum(rent_lines, Decimal(0))
            if abs(charged - rent) > CROSS_CHECK_TOLERANCE:
                issues.append(
                    Issue(
                        Severity.WARNING,
                        "rent_charge_mismatch",
                        f"Unit {unit}: the rent column says {show(rent)} but its rent charge lines add up to "
                        f"{show(charged)}.",
                        r,
                        "current_rent",
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
            future = [r for r in total.scope_rows if r in by_row and not by_row[r].current]
            if abs(diff) > TIE_OUT_TOLERANCE and future and len(future) < len(total.scope_rows):
                # A grand total usually covers today's units only, not the future leases listed below them.
                current = computed - sum((row_amount(by_row[r], name) for r in future), Decimal("0"))
                if abs(Decimal(str(reported.value)) - current) <= TIE_OUT_TOLERANCE:
                    issues.append(
                        Issue(
                            Severity.INFO,
                            "total_ties_out",
                            f"'{total.label}' {label(name)} of {show(reported.value)} ties out to its "
                            f"{len(total.scope_rows) - len(future)} current units (future leases not included).",
                            total.row,
                            name,
                        )
                    )
                    continue
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


_STAT_NAMES = {
    "total_units": "unit count",
    "occupied_units": "occupied units",
    "vacant_units": "vacant units",
    "occupancy": "occupancy",
}


def _stated_number(raw: object) -> tuple[Decimal, int, bool] | None:
    """(value, decimal places, had a % sign) for a stated figure, or None if it isn't one."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return Decimal(raw), 0, False
    if isinstance(raw, float):
        if raw != raw or raw in (float("inf"), float("-inf")):
            return None
        d = Decimal(repr(raw))
        exp = d.as_tuple().exponent
        return d, max(0, -exp) if isinstance(exp, int) else 0, False
    text = str(raw).strip().replace(",", "")
    pct = text.endswith("%")
    text = text.rstrip("%").strip()
    if not re.fullmatch(r"-?\d+(\.\d+)?", text):
        return None
    d = Decimal(text)
    places = len(text.split(".")[1]) if "." in text else 0
    return d, places, pct


def check_stated_figures(rows: list[CleanRow], stated: list[StatedFigure]) -> list[Issue]:
    """Footer statistics ("Total Units 120", "Occupancy 95.0%") must agree with the units read.

    A unit count that disagrees means rows were lost or invented (error). Occupancy and
    occupied/vacant counts can differ by how a system counts notice, model or down units, so
    those are warnings. Occupancy is compared to the precision it was printed with.
    """
    issues: list[Issue] = []
    if not stated:
        return issues
    rows = [r for r in rows if r.current]
    counts: dict[str, int] = {}
    for r in rows:
        s = r.get("status") or "unknown"
        counts[s] = counts.get(s, 0) + 1
    units = len(rows)
    occupied = counts.get("occupied", 0) + counts.get("notice", 0)
    actual: dict[str, int] = {"total_units": units, "occupied_units": occupied, "vacant_units": counts.get("vacant", 0)}

    for f in stated:
        parsed = _stated_number(f.raw)
        name = _STAT_NAMES.get(f.stat, f.stat)
        if parsed is None:
            continue
        value, places, pct = parsed
        if f.stat == "occupancy":
            if not units:
                continue
            percent = value if (pct or value > 1) else value * 100
            places = places if (pct or value > 1) else max(0, places - 2)
            computed = Decimal(occupied * 100) / Decimal(units)
            tolerance = Decimal(5) / (Decimal(10) ** (places + 1)) + Decimal("0.0001")
            if abs(computed - percent) <= tolerance:
                issues.append(
                    Issue(
                        Severity.INFO,
                        "stated_figure_ties",
                        f"Stated occupancy of {percent}% agrees with the units ({occupied} of {units} occupied).",
                        refs=[f.ref],
                    )
                )
            else:
                issues.append(
                    Issue(
                        Severity.WARNING,
                        "stated_figure_differs",
                        f"The report states occupancy of {percent}% ({f.ref.cell}), but {occupied} of {units} units "
                        f"read as occupied ({computed.quantize(Decimal('0.1'))}%). Check unit statuses, or whether the "
                        "report counts notice, model or down units differently.",
                        refs=[f.ref],
                    )
                )
            continue
        if value != value.to_integral_value() or f.stat not in actual:
            continue
        want, got = int(value), actual[f.stat]
        if want == got:
            issues.append(
                Issue(
                    Severity.INFO,
                    "stated_figure_ties",
                    f"Stated {name} of {want} agrees with the units read.",
                    refs=[f.ref],
                )
            )
            continue
        if f.stat == "total_units":
            message = f"The report states {want} units ({f.ref.cell}), but {got} unit rows were read. " + (
                "Some unit rows may be missing or were skipped."
                if got < want
                else "Some rows read as units may not be units (notes, summaries or duplicates)."
            )
            severity = Severity.ERROR
        else:
            message = (
                f"The report states {want} {name} ({f.ref.cell}), but {got} units read as {name.split()[0]}. "
                "Check unit statuses, or whether the report counts notice, model or down units differently."
            )
            severity = Severity.WARNING
        issues.append(Issue(severity, "stated_figure_differs", message, refs=[f.ref]))
    return issues
