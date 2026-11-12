"""End-to-end: file in, clean rows + issues + summary out."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from tieout import validate
from tieout.detect import HeaderInfo, RowKind, classify_rows, detect_header
from tieout.ingest import Grid, read_grid
from tieout.mapping import ColumnMapping, HeaderMapper, TemplateStore, map_columns
from tieout.models import CleanRow, Issue, ReportedTotal, Severity, TracedValue
from tieout.normalize import is_vacant_marker, parse, tidy_name
from tieout.schema import FIELDS_BY_NAME, FieldType

_GRAND_WORDS = ("grand", "property", "portfolio", "report")


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

    @property
    def ok(self) -> bool:
        return not any(i.severity is Severity.ERROR for i in self.issues)

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
        return {
            "units": units,
            "status_counts": status_counts,
            "physical_occupancy": round(occupied / units, 4) if units else None,
            "total_current_rent": float(rent),
            "total_market_rent": float(market) if market else None,
            "total_sqft": sqft or None,
            "errors": sum(1 for i in self.issues if i.severity is Severity.ERROR),
            "warnings": sum(1 for i in self.issues if i.severity is Severity.WARNING),
        }


def clean_file(
    path: str | Path,
    sheet: str | None = None,
    templates: TemplateStore | None = None,
    mapper: HeaderMapper | None = None,
    as_of: date | None = None,
) -> CleanResult:
    grid = read_grid(path, sheet)
    header = detect_header(grid)

    mappings = templates.load(header.headers) if templates else None
    if mappings is None:
        mappings = map_columns(dict(header.headers), _samples(grid, header), mapper)

    col_for = {m.field: m.column for m in mappings if m.field}
    classified = classify_rows(grid, header, col_for.get("unit"))

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
        elif cr.kind is RowKind.TOTAL:
            label = cr.label or "Total"
            grand = any(w in label.lower() for w in _GRAND_WORDS) or (bool(totals) and not since_last_total)
            scope = list(all_data) if grand else list(since_last_total)
            totals.append(ReportedTotal(cr.index + 1, label, cr.section, scope, _total_amounts(grid, cr.index, col_for)))
            since_last_total = []
        else:
            skipped[cr.kind.value] = skipped.get(cr.kind.value, 0) + 1

    issues = validate.run_all(rows, totals, mappings, as_of)
    return CleanResult(grid.file, grid.sheet, header, mappings, rows, totals, issues, skipped)


def _build_row(grid: Grid, r: int, section: str | None, col_for: dict[str, int]) -> CleanRow:
    row = CleanRow(source_row=r + 1, section=section)
    for name, c in col_for.items():
        raw = grid.value(r, c)
        value, issue = parse(raw, FIELDS_BY_NAME[name].type)
        row.values[name] = TracedValue(value, raw, grid.ref(r, c), issue=issue)

    tenant = row.values.get("tenant")
    if tenant and isinstance(tenant.value, str):
        if is_vacant_marker(tenant.value):
            # "VACANT" in the tenant column is a status, not a person.
            tenant.value = None
            if row.get("status") is None and not (row.values.get("status") and row.values["status"].issue):
                row.values["status"] = TracedValue("vacant", tenant.raw, tenant.source, derived=True)
        else:
            tenant.value = tidy_name(tenant.value)

    status = row.values.get("status")
    if status is None or (status.value is None and not status.issue):
        has_tenant = bool(row.get("tenant"))
        src = row.values["tenant"].source if "tenant" in row.values else None
        row.values["status"] = TracedValue("occupied" if has_tenant else "vacant", None, src, derived=True)
    return row


def _total_amounts(grid: Grid, r: int, col_for: dict[str, int]) -> dict[str, TracedValue]:
    out = {}
    for name, c in col_for.items():
        if FIELDS_BY_NAME[name].type in (FieldType.MONEY, FieldType.NUMBER):
            raw = grid.value(r, c)
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
