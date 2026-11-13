"""Trailing-12 operating statements (T-12s).

A T-12 lists income and expense line items with one column per month and a
Total column, grouped into sections with subtotals, ending in Net Operating
Income. Like rent rolls, the numbers must tie out, in three directions:

- across: each line's 12 months add up to its Total column;
- down: each subtotal equals the lines above it, month by month;
- through: NOI equals total income minus total expenses, month by month.

Line items are also mapped to standard underwriting categories (gross
potential rent, vacancy, payroll, taxes...) so statements from different
systems can be compared, and exported in a tidy long format (one row per
line per month) that analysis tools and AI pipelines can use directly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from itertools import pairwise
from typing import Any

from tieout.ingest import Grid, SourceRef
from tieout.models import Issue, Severity, TracedValue, jsonable
from tieout.normalize import parse_money

TOLERANCE = Decimal("1.00")  # statements are often rounded to whole dollars per month
MONTHS = {
    m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])
}
_TOTAL_RE = re.compile(r"^\s*(total|net\s+total)\b", re.I)
_NOI_RE = re.compile(r"\bnet\s+operating\s+income\b|^\s*noi\b", re.I)
_INCOME_RE = re.compile(r"\b(income|revenue|receipts)\b", re.I)
_EXPENSE_RE = re.compile(r"\b(expenses?|opex|operating\s+costs?)\b", re.I)

# Standard underwriting categories, first match wins. Order matters: specific before general.
CATEGORIES: list[tuple[str, str, str]] = [
    (
        "income",
        "gross_potential_rent",
        r"gross potential|\bgpr\b|scheduled rent|market rent|rental income|rent income|base rent",
    ),
    ("income", "loss_to_lease", r"loss.to.lease|gain.to.lease"),
    ("income", "vacancy", r"vacan"),
    ("income", "concessions", r"concession|discount|free rent|special"),
    ("income", "bad_debt", r"bad debt|write.?off|collection loss"),
    (
        "income",
        "other_income",
        r"parking|pet|late|fee|laundry|storage|utility reimb|rubs|application|admin fee|other income|misc",
    ),
    ("expense", "payroll", r"payroll|salar|wage|benefit|bonus|staff"),
    ("expense", "repairs_maintenance", r"repair|maint|r\s*&\s*m\b"),
    ("expense", "turnover", r"turnover|make.?ready|unit turn"),
    ("expense", "contract_services", r"contract|landscap|pest|snow|janitor|security|elevator|pool"),
    ("expense", "utilities", r"utilit|electric|water|sewer|\bgas\b|trash|refuse|cable|internet"),
    ("expense", "management_fee", r"management fee|mgmt fee|property management"),
    ("expense", "real_estate_taxes", r"real estate tax|property tax|\btaxes\b"),
    ("expense", "insurance", r"insurance"),
    ("expense", "marketing", r"marketing|advertis|promotion"),
    ("expense", "general_admin", r"general|admin|office|legal|professional|accounting|telephone|software"),
    ("expense", "replacement_reserves", r"reserve"),
]
_CATEGORY_RES = [(sec, cat, re.compile(rx, re.I)) for sec, cat, rx in CATEGORIES]


def month_of(v: Any) -> date | None:
    """A month header: a real date, 'Jan 2026', 'Jan-26', 'January 2026', '01/2026', '2026-01'."""
    if isinstance(v, datetime):
        return date(v.year, v.month, 1)
    if isinstance(v, date):
        return date(v.year, v.month, 1)
    if not isinstance(v, str):
        return None
    s = v.strip().lower()
    m = re.fullmatch(r"([a-z]{3})[a-z]*[\s\-/.']*(\d{2}|\d{4})", s)
    if m and m.group(1) in MONTHS:
        y = int(m.group(2))
        return date(y + 2000 if y < 100 else y, MONTHS[m.group(1)], 1)
    m = re.fullmatch(r"(\d{1,2})[/\-](\d{4})", s) or None
    if m and 1 <= int(m.group(1)) <= 12:
        return date(int(m.group(2)), int(m.group(1)), 1)
    m = re.fullmatch(r"(\d{4})[/\-](\d{1,2})", s)
    if m and 1 <= int(m.group(2)) <= 12:
        return date(int(m.group(1)), int(m.group(2)), 1)
    return None


@dataclass
class Line:
    source_row: int
    code: str | None
    name: str
    section: str  # "income" | "expense" | "other" | "below_noi"
    kind: str  # "line" | "subtotal" | "noi"
    amounts: list[TracedValue]
    total: TracedValue | None
    category: str | None = None

    def month_sum(self) -> Decimal:
        return sum((a.value for a in self.amounts if a.value is not None), Decimal(0))


@dataclass
class Statement:
    file: str
    sheet: str
    header_row: int  # 1-based
    months: list[date]
    lines: list[Line] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity is Severity.ERROR for i in self.issues)

    def items(self, section: str | None = None) -> list[Line]:
        return [ln for ln in self.lines if ln.kind == "line" and (section is None or ln.section == section)]

    def summary(self) -> dict[str, Any]:
        income = sum((ln.month_sum() for ln in self.items("income")), Decimal(0))
        expense = sum((ln.month_sum() for ln in self.items("expense")), Decimal(0))
        by_cat: dict[str, Decimal] = {}
        for ln in self.items():
            if ln.category:
                by_cat[ln.category] = by_cat.get(ln.category, Decimal(0)) + ln.month_sum()
        return {
            "period": f"{self.months[0]:%b %Y} to {self.months[-1]:%b %Y}" if self.months else None,
            "months": len(self.months),
            "line_items": len(self.items()),
            "total_income": str(income),
            "total_expenses": str(expense),
            "noi": str(income - expense),
            "expense_ratio": round(float(expense / income), 4) if income else None,
            "by_category": {k: str(v) for k, v in sorted(by_cat.items())},
            "uncategorized": sum(1 for ln in self.items() if not ln.category),
            "errors": sum(1 for i in self.issues if i.severity is Severity.ERROR),
            "warnings": sum(1 for i in self.issues if i.severity is Severity.WARNING),
        }


MIN_MONTHS = 3  # T-3 and T-6 statements are common too


def _consecutive(months: list[date]) -> bool:
    return all((b.year * 12 + b.month) - (a.year * 12 + a.month) == 1 for a, b in pairwise(months))


def find_month_header(grid: Grid, scan: int = 30) -> tuple[int, dict[int, date], int | None] | None:
    """(row, {column: month}, total column) for the first row with a run of 3+ consecutive month headers."""
    for r in range(min(scan, len(grid.rows))):
        months = {c: m for c in range(grid.width) if (m := month_of(grid.merged_value(r, c))) is not None}
        if len(months) >= MIN_MONTHS and _consecutive([months[c] for c in sorted(months)]):
            last = max(months)
            total_col = next(
                (
                    c
                    for c in range(last + 1, grid.width)
                    if re.search(r"total|ytd|t-?12|annual", str(grid.merged_value(r, c) or ""), re.I)
                ),
                None,
            )
            return r, months, total_col
    return None


def is_t12(grid: Grid) -> bool:
    return find_month_header(grid) is not None


def categorize(name: str, section: str) -> str | None:
    for sec, cat, rx in _CATEGORY_RES:
        if (section == sec or section == "other") and rx.search(name):
            return cat
    return None


def read_t12(grid: Grid) -> Statement:
    found = find_month_header(grid)
    if found is None:
        raise ValueError("No row of month columns found; this does not look like a T-12 statement.")
    header_row, month_cols, total_col = found
    cols = sorted(month_cols)
    first_amount_col = cols[0]
    stmt = Statement(grid.file, grid.sheet, header_row + 1, [month_cols[c] for c in cols])

    section = "other"
    seen_noi = False
    for r in range(header_row + 1, len(grid.rows)):
        texts = [
            (c, str(grid.value(r, c)).strip())
            for c in range(first_amount_col)
            if grid.value(r, c) not in (None, "") and str(grid.value(r, c)).strip()
        ]
        amounts = [_read_amount(grid, r, c) for c in cols]
        has_amounts = any(a.value is not None or a.issue for a in amounts)
        if not texts and not has_amounts:
            continue
        # The label is the longest text to the left of the amounts; a short numeric-ish one is a GL code.
        label = max((t for _, t in texts), key=len, default="")
        code = next((t for _, t in texts if t != label and re.fullmatch(r"[\d\-.]+", t)), None)
        if not has_amounts:
            if _INCOME_RE.search(label) and not _EXPENSE_RE.search(label):
                section = "income"
            elif _EXPENSE_RE.search(label):
                section = "expense"
            elif not seen_noi:
                section = "other"
            continue
        total = _read_amount(grid, r, total_col) if total_col is not None else None
        if _NOI_RE.search(label):
            kind, seen_noi = "noi", True
            line_section = "noi"
        elif _TOTAL_RE.match(label):
            kind = "subtotal"
            if seen_noi:
                line_section = "below_noi"  # capital expenditures, debt service: never operating totals
            elif _EXPENSE_RE.search(label):
                line_section = "expense"
            elif _INCOME_RE.search(label):
                line_section = "income"
            else:
                line_section = section
        else:
            kind = "line"
            line_section = "below_noi" if seen_noi else section
        line = Line(r + 1, code, label, line_section, kind, amounts, total)
        if kind == "line":
            line.category = categorize(label, line_section)
        stmt.lines.append(line)

    stmt.issues = _validate(stmt)
    return stmt


def _read_amount(grid: Grid, r: int, c: int) -> TracedValue:
    raw = grid.value(r, c)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return TracedValue(None, raw, grid.ref(r, c))
    value, issue = parse_money(raw)
    if grid.is_uncomputed(r, c):
        issue = "cell is a formula with no saved result; open the file in Excel and save it again"
    return TracedValue(value, raw, grid.ref(r, c), issue=issue)


def _month_total(lines: list[Line], i: int) -> Decimal:
    return sum((x.amounts[i].value or Decimal(0) for x in lines), Decimal(0))


def _ties(subtotal: Line, lines: list[Line], n: int) -> bool:
    """Every month the subtotal reports equals the sum of these lines."""
    return all(
        subtotal.amounts[i].value is None or abs(subtotal.amounts[i].value - _month_total(lines, i)) <= TOLERANCE
        for i in range(n)
    )


def _refs(tv: TracedValue) -> list[SourceRef]:
    return [tv.source] if tv.source is not None else []


def _m(d: Decimal) -> str:
    return f"{d:,.2f}"


def _validate(stmt: Statement) -> list[Issue]:
    issues: list[Issue] = []
    n = len(stmt.months)

    # Months must be consecutive.
    for prev, nxt in pairwise(stmt.months):
        if (nxt.year * 12 + nxt.month) - (prev.year * 12 + prev.month) != 1:
            issues.append(Issue(Severity.WARNING, "t12_month_gap", f"Months jump from {prev:%b %Y} to {nxt:%b %Y}."))
    if n != 12:
        issues.append(Issue(Severity.INFO, "t12_not_twelve_months", f"The statement has {n} months, not 12."))

    for ln in stmt.lines:
        for a in ln.amounts:
            if a.issue:
                issues.append(
                    Issue(
                        Severity.WARNING,
                        "t12_unparsed_amount",
                        f"{ln.name}: {a.issue}",
                        ln.source_row,
                        None,
                        [a.source] if a.source else [],
                    )
                )
        # Across: the months add up to the Total column.
        if ln.total is not None and ln.total.value is not None:
            gap = ln.total.value - ln.month_sum()
            if abs(gap) > TOLERANCE:
                issues.append(
                    Issue(
                        Severity.ERROR,
                        "t12_row_total_mismatch",
                        f"{ln.name}: Total column says {_m(ln.total.value)} but the months add up to "
                        f"{_m(ln.month_sum())} (difference {_m(gap)}).",
                        ln.source_row,
                        None,
                        [ln.total.source] if ln.total.source else [],
                    )
                )
        if ln.kind == "line" and not ln.category and ln.section in ("income", "expense"):
            issues.append(
                Issue(
                    Severity.INFO,
                    "t12_uncategorized",
                    f"'{ln.name}' was not matched to a standard category.",
                    ln.source_row,
                )
            )

    # Down: a subtotal must equal either the lines since the previous subtotal (a partial
    # total such as "Total Rental Income") or every line of its section so far (the section
    # total, such as "Total Income" after several partial totals).
    pending: list[Line] = []
    open_lines: dict[str, list[Line]] = {}
    section_totals: dict[str, Line] = {}
    last_subtotal: dict[str, Line] = {}
    for ln in stmt.lines:
        if ln.kind == "line":
            pending.append(ln)
            open_lines.setdefault(ln.section, []).append(ln)
            continue
        if ln.kind != "subtotal":
            continue
        last_subtotal[ln.section] = ln  # the broadest total a section reports comes last
        partial = [x for x in pending if x.section == ln.section] or pending
        whole = open_lines.get(ln.section, [])
        if whole and _ties(ln, whole, n):
            # Covers everything in its section so far: the latest such subtotal is the section total.
            section_totals[ln.section] = ln
        elif not (partial and _ties(ln, partial, n)):
            group = partial or whole
            for i in range(n):
                reported = ln.amounts[i].value
                if reported is None:
                    continue
                computed = _month_total(group, i)
                if abs(reported - computed) > TOLERANCE:
                    issues.append(
                        Issue(
                            Severity.ERROR,
                            "t12_subtotal_mismatch",
                            f"'{ln.name}' for {stmt.months[i]:%b %Y} is {_m(reported)}, but its "
                            f"{len(group)} lines add up to {_m(computed)} "
                            f"(difference {_m(reported - computed)}).",
                            ln.source_row,
                            None,
                            _refs(ln.amounts[i]),
                        )
                    )
        pending = []

    # Through: NOI = income - expenses, month by month. It ties if it matches the line
    # items or the reported section totals, so one wrong line or one wrong subtotal is
    # reported once, by its own check, rather than also breaking NOI.
    for noi in (x for x in stmt.lines if x.kind == "noi"):
        for i in range(n):
            reported = noi.amounts[i].value
            if reported is None:
                continue
            inc = _section_month(stmt, section_totals, "income", i)
            exp = _section_month(stmt, section_totals, "expense", i)
            by_totals = _reported_month(last_subtotal, "income", i), _reported_month(last_subtotal, "expense", i)
            if (
                by_totals[0] is not None
                and by_totals[1] is not None
                and abs(reported - (by_totals[0] - by_totals[1])) <= TOLERANCE
            ):
                continue
            if abs(reported - (inc - exp)) > TOLERANCE:
                issues.append(
                    Issue(
                        Severity.ERROR,
                        "t12_noi_mismatch",
                        f"NOI for {stmt.months[i]:%b %Y} is {_m(reported)}, but income {_m(inc)} "
                        f"minus expenses {_m(exp)} is {_m(inc - exp)} (difference {_m(reported - (inc - exp))}).",
                        noi.source_row,
                        None,
                        _refs(noi.amounts[i]),
                    )
                )
    order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    issues.sort(key=lambda i: (order[i.severity], i.row or 0))
    return issues


def _reported_month(totals: dict[str, Line], section: str, i: int) -> Decimal | None:
    sub = totals.get(section)
    return Decimal(sub.amounts[i].value) if sub is not None and sub.amounts[i].value is not None else None


def _section_month(stmt: Statement, totals: dict[str, Line], section: str, i: int) -> Decimal:
    """A section's amount for month i, from its line items.

    Lines, not reported subtotals, so a wrong subtotal is reported once (by the
    subtotal check) instead of also breaking NOI. A statement with no line detail
    falls back to its section total.
    """
    items = stmt.items(section)
    if items:
        return _month_total(items, i)
    sub = totals.get(section)
    if sub is not None and sub.amounts[i].value is not None:
        return Decimal(sub.amounts[i].value)
    return Decimal(0)


def to_payload(stmt: Statement) -> dict[str, Any]:
    def ref(s: SourceRef | None) -> str | None:
        return s.cell if s else None

    return {
        "document_type": "t12",
        "source": {"file": stmt.file, "sheet": stmt.sheet, "header_row": stmt.header_row},
        "ok": stmt.ok,
        "months": [m.isoformat()[:7] for m in stmt.months],
        "summary": stmt.summary(),
        "lines": [
            {
                "source_row": ln.source_row,
                "code": ln.code,
                "name": ln.name,
                "section": ln.section,
                "kind": ln.kind,
                "category": ln.category,
                "amounts": [jsonable(a.value) for a in ln.amounts],
                "cells": [ref(a.source) for a in ln.amounts],
                "total": jsonable(ln.total.value) if ln.total else None,
                "total_cell": ref(ln.total.source) if ln.total else None,
                "month_sum": str(ln.month_sum()),
            }
            for ln in stmt.lines
        ],
        "issues": [i.to_dict() for i in stmt.issues],
    }


def tidy_rows(stmt: Statement) -> list[dict[str, Any]]:
    """Long format: one row per line item per month, with the source cell."""
    out = []
    for ln in stmt.items():
        for m, a in zip(stmt.months, ln.amounts, strict=True):
            out.append(
                {
                    "month": m.isoformat()[:7],
                    "section": ln.section,
                    "category": ln.category or "",
                    "code": ln.code or "",
                    "line_item": ln.name,
                    "amount": jsonable(a.value),
                    "source_cell": a.source.cell if a.source else "",
                    "source_row": ln.source_row,
                }
            )
    return out


def render_report(stmt: Statement) -> str:
    s = stmt.summary()
    lines = [
        f"# tieout T-12 report: {stmt.file}",
        "",
        f"Sheet **{stmt.sheet}**, months on row {stmt.header_row}, {s['period']}.",
        "",
        f"**{'PASS' if stmt.ok else 'NEEDS REVIEW'}**: {s['errors']} errors, {s['warnings']} warnings.",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Total income | {Decimal(s['total_income']):,.2f} |",
        f"| Total expenses | {Decimal(s['total_expenses']):,.2f} |",
        f"| Net operating income | {Decimal(s['noi']):,.2f} |",
    ]
    if s["expense_ratio"] is not None:
        lines.append(f"| Expense ratio | {s['expense_ratio']:.1%} |")
    lines += ["", "## By category", "", "| Category | Total |", "| --- | --- |"]
    lines += [f"| {k.replace('_', ' ')} | {Decimal(v):,.2f} |" for k, v in s["by_category"].items()]
    lines += ["", "## Issues", ""]
    lines += [f"- **{i.severity.value}** `{i.rule}`: {i.message.replace('|', chr(92) + '|')}" for i in stmt.issues] or [
        "None."
    ]
    return "\n".join(lines) + "\n"


def write_outputs(stmt: Statement, out_dir: Any) -> dict[str, Any]:
    """JSON payload, tidy CSV, Excel workbook and report for a T-12."""
    import csv
    import json
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(stmt.file).stem
    paths = {
        "json": out / f"{stem}.t12.json",
        "csv": out / f"{stem}.t12.tidy.csv",
        "xlsx": out / f"{stem}.t12.xlsx",
        "report": out / f"{stem}.t12.report.md",
    }
    paths["json"].write_text(json.dumps(to_payload(stmt), indent=2, default=str))
    rows = tidy_rows(stmt)
    with paths["csv"].open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["month"])
        w.writeheader()
        for row in rows:
            w.writerow(
                {
                    k: ("'" + v if isinstance(v, str) and v[:1] in "=+-@" and k != "amount" else v)
                    for k, v in row.items()
                }
            )
    write_xlsx(stmt, paths["xlsx"])
    paths["report"].write_text(render_report(stmt))
    return paths


def write_xlsx(stmt: Statement, path: Any) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Statement"
    ws.append(["Code", "Line item", "Section", "Category", *[f"{m:%b %Y}" for m in stmt.months], "Total"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for ln in stmt.lines:
        ws.append(
            [
                ln.code,
                ln.name,
                ln.section,
                ln.category or ("(" + ln.kind + ")" if ln.kind != "line" else ""),
                *[float(a.value) if a.value is not None else None for a in ln.amounts],
                float(ln.total.value) if ln.total and ln.total.value is not None else None,
            ]
        )
        if ln.kind != "line":
            for cell in ws[ws.max_row]:
                cell.font = Font(bold=True)
        for cell in ws[ws.max_row][4:]:
            cell.number_format = "#,##0.00;(#,##0.00)"
    tidy = wb.create_sheet("Tidy")
    rows = tidy_rows(stmt)
    if rows:
        tidy.append(list(rows[0]))
        for row in rows:
            tidy.append([float(v) if k == "amount" and v is not None else v for k, v in row.items()])
    issues = wb.create_sheet("Issues")
    issues.append(["severity", "rule", "row", "cells", "message"])
    for i in stmt.issues:
        issues.append([i.severity.value, i.rule, i.row, " ".join(r.cell for r in i.refs), i.message])
    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    cell.data_type = "s"
    wb.save(path)
