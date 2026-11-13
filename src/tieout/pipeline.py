"""End-to-end: file (+ optional reviewer decisions) in, clean rows + issues + metrics out.

Stages, in order:
  read grid -> detect header -> map columns (template / rules / overrides)
  -> classify rows -> build rows (parse, roll up charge lines)
  -> apply corrections -> infer missing status -> validate -> attach acknowledgments
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from tieout import validate
from tieout.detect import HeaderInfo, RowKind, classify_rows, detect_header
from tieout.ingest import Grid, read_grid
from tieout.mapping import ColumnMapping, HeaderMapper, TemplateStore, map_columns
from tieout.metrics import compute_metrics
from tieout.models import Charge, CleanRow, Issue, ReportedTotal, Severity, TracedValue
from tieout.normalize import is_vacant_marker, parse, tidy_name
from tieout.review import Review
from tieout.schema import CONCESSION_CODE_RE, FIELDS_BY_NAME, RENT_CODE_RE, FieldType

UNCOMPUTED_FORMULA = "cell is a formula with no saved result; open the file in Excel and save it again"
_GRAND_WORDS = ("grand", "property", "portfolio", "report")
_RENT_CODE = re.compile(RENT_CODE_RE, re.I)
_CONCESSION_CODE = re.compile(CONCESSION_CODE_RE, re.I)


@dataclass
class CleanResult:
    source_file: str
    sheet: str
    header: HeaderInfo
    mappings: list[ColumnMapping]
    rows: list[CleanRow]
    totals: list[ReportedTotal]
    issues: list[Issue]
    skipped: dict[str, int] = dc_field(default_factory=dict)  # row kind -> count
    review: Review = dc_field(default_factory=Review)
    as_of: date | None = None
    sheets: list[str] = dc_field(default_factory=list)

    @property
    def open_issues(self) -> list[Issue]:
        return [i for i in self.issues if i.open]

    @property
    def ok(self) -> bool:
        """True when no error-level issue is left open."""
        return not any(i.severity is Severity.ERROR for i in self.open_issues)

    def summary(self) -> dict[str, Any]:
        units = len(self.rows)
        status_counts: dict[str, int] = {}
        for r in self.rows:
            s = r.get("status") or "unknown"
            status_counts[s] = status_counts.get(s, 0) + 1
        occupied = status_counts.get("occupied", 0) + status_counts.get("notice", 0)
        rent = sum((r.get("current_rent") or Decimal(0) for r in self.rows), Decimal(0))
        market = sum((r.get("market_rent") or Decimal(0) for r in self.rows), Decimal(0))
        sqft = sum((r.get("sqft") or 0 for r in self.rows), 0)
        open_ = self.open_issues
        return {
            "units": units,
            "status_counts": status_counts,
            "physical_occupancy": round(occupied / units, 4) if units else None,
            "total_current_rent": str(rent.quantize(Decimal("0.01"))),
            "total_market_rent": str(market.quantize(Decimal("0.01"))) if market else None,
            "total_sqft": sqft or None,
            "errors": sum(1 for i in open_ if i.severity is Severity.ERROR),
            "warnings": sum(1 for i in open_ if i.severity is Severity.WARNING),
            "acknowledged": sum(1 for i in self.issues if not i.open),
            "corrections": len(self.review.corrections),
        }

    def metrics(self) -> dict[str, Any]:
        return compute_metrics(self.rows, self.as_of)


def clean_file(
    path: str | Path,
    sheet: str | None = None,
    templates: TemplateStore | None = None,
    mapper: HeaderMapper | None = None,
    as_of: date | None = None,
    review: Review | None = None,
    source_name: str | None = None,
    grid: Grid | None = None,
) -> CleanResult:
    """Clean one rent roll. Pass `grid` to reuse an already-read source (it is never modified)."""
    review = review or Review()
    if grid is None:
        grid = read_grid(path, sheet, source_name)
    header = detect_header(grid)

    mappings = templates.load(header.headers) if templates else None
    if mappings is None:
        mappings = map_columns(dict(header.headers), _samples(grid, header), mapper)
    mappings = _apply_overrides(mappings, review.mapping_overrides)
    mappings = _reconcile_charge_columns(mappings)

    col_for = {m.field: m.column for m in mappings if m.field}
    charge_cols = tuple(col_for[f] for f in ("charge_code", "charge_amount") if f in col_for)
    classified = classify_rows(grid, header, col_for.get("unit"), charge_cols)

    rows: list[CleanRow] = []
    totals: list[ReportedTotal] = []
    skipped: dict[str, int] = {}
    since_last_total: list[int] = []
    all_data: list[int] = []

    for cr in classified:
        if cr.kind is RowKind.DATA:
            row = _build_row(grid, cr.index, cr.section, col_for)
            rows.append(row)
            since_last_total.append(row.source_row)
            all_data.append(row.source_row)
        elif cr.kind is RowKind.CHARGE:
            charge = _read_charge(grid, cr.index, col_for)
            if charge is not None:
                rows[-1].charges.append(charge)
        elif cr.kind is RowKind.TOTAL:
            label = cr.label or "Total"
            scope = _total_scope(label, totals, since_last_total, all_data)
            totals.append(
                ReportedTotal(cr.index + 1, label, cr.section, scope, _total_amounts(grid, cr.index, col_for))
            )
            since_last_total = []
        else:
            skipped[cr.kind.value] = skipped.get(cr.kind.value, 0) + 1

    extra_issues: list[Issue] = []
    by_source_row = {r.source_row: r for r in rows}
    for row in rows:
        _roll_up_charges(row, col_for)
        _derive_monthly_from_annual(row, col_for)
        _clean_tenant(row)
        _apply_corrections(row, review)
        _ensure_status(row, "tenant" in col_for)
    for c in review.corrections:
        if c.source_row not in by_source_row:
            extra_issues.append(
                Issue(
                    Severity.WARNING,
                    "correction_orphaned",
                    f"A correction targets row {c.source_row}, which is no longer a unit row.",
                    c.source_row,
                    c.field,
                )
            )

    issues = validate.run_all(rows, totals, mappings, as_of) + extra_issues
    for issue in issues:
        issue.acknowledgment = review.ack_for(issue.id)
    return CleanResult(
        grid.file, grid.sheet, header, mappings, rows, totals, issues, skipped, review, as_of, list(grid.sheets)
    )


# --- mapping ------------------------------------------------------------------------


def _apply_overrides(mappings: list[ColumnMapping], overrides: dict[str, str | None]) -> list[ColumnMapping]:
    """Reviewer overrides win. A field moved to a new column is removed from its old one."""
    if not overrides:
        return mappings
    forced = {m.column: overrides[m.header] for m in mappings if m.header in overrides}
    forced_fields = {f for f in forced.values() if f}
    out = []
    for m in mappings:
        if m.column in forced:
            f = forced[m.column]
            out.append(ColumnMapping(m.column, m.header, f, 1.0 if f else 0.0, "override" if f else "unmapped"))
        elif m.field in forced_fields:
            out.append(ColumnMapping(m.column, m.header, None, 0.0, "unmapped"))
        else:
            out.append(m)
    return out


def _reconcile_charge_columns(mappings: list[ColumnMapping]) -> list[ColumnMapping]:
    """Charge code and amount only make sense together.

    An "Amount"/"Charges" column with no charge-code column is a per-unit total,
    so it becomes total_charges; a lone charge-code column is dropped.
    """
    fields = {m.field for m in mappings}
    has_code, has_amount = "charge_code" in fields, "charge_amount" in fields
    if has_code == has_amount:
        return mappings
    out = []
    for m in mappings:
        if m.field == "charge_amount" and "total_charges" not in fields:
            out.append(ColumnMapping(m.column, m.header, "total_charges", m.confidence, m.method))
        elif m.field in ("charge_amount", "charge_code"):
            out.append(ColumnMapping(m.column, m.header, None, 0.0, "unmapped"))
        else:
            out.append(m)
    return out


# --- rows -----------------------------------------------------------------------------


def _total_scope(label: str, previous: list[ReportedTotal], since_last: list[int], all_data: list[int]) -> list[int]:
    """Which data rows a total row should add up.

    - "Grand Total", "Property Total": every data row.
    - New data since the last total: a subtotal of those rows.
    - Right after two or more subtotals: a total of all of them.
    - Right after a single total: a second line of that same total
      (e.g. one row for rent, another for charges), so the same rows.
    """
    if any(w in label.lower() for w in _GRAND_WORDS):
        return list(all_data)
    if since_last:
        return list(since_last)
    if not previous:
        return []
    subtotals = [t for t in previous if set(t.scope_rows) != set(all_data)]
    if len(subtotals) >= 2:
        return list(all_data)
    return list(previous[-1].scope_rows)


def _build_row(grid: Grid, r: int, section: str | None, col_for: dict[str, int]) -> CleanRow:
    row = CleanRow(source_row=r + 1, section=section)
    for name, c in col_for.items():
        if name in ("charge_code", "charge_amount"):
            continue
        row.values[name] = _read(grid, r, c, FIELDS_BY_NAME[name].type)
    charge = _read_charge(grid, r, col_for)
    if charge is not None:
        row.charges.append(charge)
    return row


def _read(grid: Grid, r: int, c: int, ftype: FieldType) -> TracedValue:
    raw = grid.value(r, c)
    value, issue = parse(raw, ftype)
    if grid.is_uncomputed(r, c):
        issue = UNCOMPUTED_FORMULA
    return TracedValue(value, raw, grid.ref(r, c), issue=issue)


def _read_charge(grid: Grid, r: int, col_for: dict[str, int]) -> Charge | None:
    if "charge_code" not in col_for or "charge_amount" not in col_for:
        return None
    code = _read(grid, r, col_for["charge_code"], FieldType.TEXT)
    amount = _read(grid, r, col_for["charge_amount"], FieldType.MONEY)
    if code.value is None and amount.value is None and not amount.issue:
        return None
    return Charge(code, amount, _charge_category(code.value))


def _charge_category(code: str | None) -> str:
    if not code:
        return "other"
    if _CONCESSION_CODE.search(code):
        return "concession"
    if _RENT_CODE.search(code):
        return "rent"
    return "other"


def _roll_up_charges(row: CleanRow, col_for: dict[str, int]) -> None:
    """Fill current_rent / concessions / other_charges / total_charges from charge lines.

    A value read from its own column always wins; roll-ups only fill fields the
    file does not provide directly, and are marked derived with every source cell.
    """
    if not row.charges:
        return
    sums: dict[str, Decimal] = {"rent": Decimal(0), "concession": Decimal(0), "other": Decimal(0)}
    cells: dict[str, list[Any]] = {"rent": [], "concession": [], "other": []}
    unreadable = [ch for ch in row.charges if ch.amount.value is None and ch.amount.issue]
    for ch in row.charges:
        if ch.amount.value is not None:
            sums[ch.category] += ch.amount.value
            if ch.amount.source:
                cells[ch.category].append(ch.amount.source)
    issue = f"{len(unreadable)} charge line(s) could not be read" if unreadable else None

    def put(name: str, amount: Decimal, srcs: list[Any]) -> None:
        if name in col_for:
            return
        row.values[name] = TracedValue(amount, None, srcs[0] if srcs else None, derived=True, issue=issue, sources=srcs)

    if cells["rent"] or not any(cells.values()):
        put("current_rent", sums["rent"], cells["rent"])
    elif "current_rent" not in col_for:
        row.values["current_rent"] = TracedValue(
            None, None, None, derived=True, issue="no charge line looks like rent; check the charge codes"
        )
    if cells["concession"]:
        put("concessions", sums["concession"], cells["concession"])
    if cells["other"]:
        put("other_charges", sums["other"], cells["other"])
    put("total_charges", sum(sums.values(), Decimal(0)), cells["rent"] + cells["concession"] + cells["other"])


def _derive_monthly_from_annual(row: CleanRow, col_for: dict[str, int]) -> None:
    """Commercial rent rolls often state annual rent only. Monthly = annual / 12, marked derived."""
    annual = row.values.get("annual_rent")
    if annual is None or annual.value is None or "current_rent" in col_for:
        return
    if row.get("current_rent") is not None:
        return  # already rolled up from charge lines
    monthly = (annual.value / 12).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    row.values["current_rent"] = TracedValue(
        monthly, None, annual.source, derived=True, sources=[annual.source] if annual.source else []
    )


def _clean_tenant(row: CleanRow) -> None:
    tenant = row.values.get("tenant")
    if not (tenant and isinstance(tenant.value, str)):
        return
    if is_vacant_marker(tenant.value):
        # "VACANT" in the tenant column is a status, not a person.
        tenant.value = None
        status = row.values.get("status")
        if status is None or (status.value is None and not status.issue):
            row.values["status"] = TracedValue("vacant", tenant.raw, tenant.source, derived=True)
    else:
        tenant.value = tidy_name(tenant.value)


def _apply_corrections(row: CleanRow, review: Review) -> None:
    for c in review.corrections_for(row.source_row):
        spec = FIELDS_BY_NAME[c.field]
        value, _ = parse(c.value, spec.type) if c.value is not None else (None, None)
        current = row.values.get(c.field)
        row.values[c.field] = TracedValue(
            value,
            current.raw if current else None,
            current.source if current else None,
            derived=False,
            issue=None,
            correction=c,
            original=current.value if current else None,
            sources=current.sources if current else [],
        )


def _ensure_status(row: CleanRow, has_tenant_column: bool) -> None:
    status = row.values.get("status")
    if status is None or (status.value is None and not status.issue and status.correction is None):
        row.values["status"] = _infer_status(row, has_tenant_column)


def _infer_status(row: CleanRow, has_tenant_column: bool) -> TracedValue:
    """Status when the file doesn't state it. Never assume vacancy from a missing column."""
    if has_tenant_column:
        tenant = row.values["tenant"]
        return TracedValue("occupied" if row.get("tenant") else "vacant", None, tenant.source, derived=True)
    rent = row.values.get("current_rent")
    if rent is not None and rent.value is not None:
        # No tenant or status column: charged rent is the only evidence of occupancy.
        return TracedValue("occupied" if rent.value > 0 else "vacant", None, rent.source, derived=True)
    return TracedValue(None, None, None, derived=True)


def _total_amounts(grid: Grid, r: int, col_for: dict[str, int]) -> dict[str, TracedValue]:
    out = {}
    for name, c in col_for.items():
        if FIELDS_BY_NAME[name].type in (FieldType.MONEY, FieldType.NUMBER):
            raw = grid.value(r, c)
            if grid.is_uncomputed(r, c):
                out[name] = TracedValue(None, raw, grid.ref(r, c), issue=UNCOMPUTED_FORMULA)
                continue
            value, _ = parse(raw, FIELDS_BY_NAME[name].type)
            if value is not None:
                out[name] = TracedValue(value, raw, grid.ref(r, c))
    return out


def _samples(grid: Grid, header: HeaderInfo, n: int = 5) -> dict[int, list[str]]:
    start = max(header.header_rows) + 1
    out: dict[int, list[str]] = {c: [] for c in header.headers}
    for r in range(start, min(start + 30, len(grid.rows))):
        for c in header.headers:
            v = grid.value(r, c)
            if v not in (None, "") and len(out[c]) < n:
                out[c].append(str(v))
    return out
