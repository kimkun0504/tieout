"""Write a CleanResult to disk: CSV for spreadsheets, JSON with provenance, issues, and a readable report."""

from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from tieout import __version__
from tieout.models import jsonable
from tieout.pipeline import CleanResult
from tieout.schema import FIELDS_BY_NAME, OUTPUT_FIELDS, FieldType
from tieout.validate import row_amount

COLUMNS = list(OUTPUT_FIELDS)


def write_all(result: CleanResult, out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(result.source_file).stem
    paths = {
        "csv": out / f"{stem}.clean.csv",
        "json": out / f"{stem}.clean.json",
        "issues": out / f"{stem}.issues.csv",
        "report": out / f"{stem}.report.md",
        "xlsx": out / f"{stem}.clean.xlsx",
    }
    write_xlsx(result, paths["xlsx"])
    write_csv(result, paths["csv"])
    write_json(result, paths["json"])
    write_issues(result, paths["issues"])
    paths["report"].write_text(render_report(result))
    return paths


def write_csv(result: CleanResult, path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([*COLUMNS, "section", "source_row"])
        for row in result.rows:
            w.writerow([_csv_value(row.get(c)) for c in COLUMNS] + [_safe(row.section or ""), row.source_row])


def to_payload(result: CleanResult) -> dict[str, Any]:
    """Everything about a run as JSON-safe data: the contract shared by the JSON export and the API."""
    return {
        "tieout_version": __version__,
        "source": {
            "file": result.source_file,
            "sheet": result.sheet,
            "sheets": result.sheets,
            "header_rows": [r + 1 for r in result.header.header_rows],
        },
        "ok": result.ok,
        "summary": result.summary(),
        "metrics": result.metrics(),
        "fields": [
            {"name": f, "type": FIELDS_BY_NAME[f].type.value, "description": FIELDS_BY_NAME[f].description}
            for f in COLUMNS
        ],
        "mappings": [
            {
                "column": m.column + 1,
                "header": m.header,
                "field": m.field,
                "confidence": m.confidence,
                "method": m.method,
            }
            for m in result.mappings
        ],
        "rows": [
            {
                "source_row": r.source_row,
                "section": r.section,
                "fields": {k: v.to_dict() for k, v in r.values.items()},
                "charges": [c.to_dict() for c in r.charges],
            }
            for r in result.rows
        ],
        "totals": [
            {
                "row": t.row,
                "label": t.label,
                "section": t.section,
                "covers_rows": t.scope_rows,
                "amounts": {k: v.to_dict() for k, v in t.amounts.items()},
                "computed": {k: _computed_total(result, t.scope_rows, k) for k in t.amounts},
            }
            for t in result.totals
        ],
        "issues": [i.to_dict() for i in result.issues],
        "skipped": result.skipped,
        "review": result.review.to_dict(),
    }


def _computed_total(result: CleanResult, scope: list[int], name: str) -> str:
    by_row = {r.source_row: r for r in result.rows}
    total = sum((row_amount(by_row[r], name) for r in scope if r in by_row), Decimal(0))
    return str(total)


def write_json(result: CleanResult, path: Path) -> None:
    path.write_text(json.dumps(to_payload(result), indent=2, default=str))


def write_issues(result: CleanResult, path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "severity", "status", "rule", "row", "field", "cells", "message", "note"])
        for i in result.issues:
            note = i.acknowledgment.note if i.acknowledgment else ""
            w.writerow(
                [
                    i.id,
                    i.severity.value,
                    "open" if i.open else "accepted",
                    i.rule,
                    i.row or "",
                    i.field or "",
                    " ".join(r.cell for r in i.refs),
                    _safe(i.message),
                    _safe(note),
                ]
            )


def render_report(result: CleanResult) -> str:
    s = result.summary()
    occ = f"{s['physical_occupancy']:.1%}" if s["physical_occupancy"] is not None else "n/a"
    lines = [
        f"# tieout report: {result.source_file}",
        "",
        f"Sheet **{result.sheet}**, header on row(s) {', '.join(str(r + 1) for r in result.header.header_rows)}.",
        "",
        f"**{'PASS' if result.ok else 'NEEDS REVIEW'}**: {s['errors']} errors, {s['warnings']} warnings.",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Units | {s['units']} |",
        f"| Status | {', '.join(f'{k} {v}' for k, v in sorted(s['status_counts'].items()))} |",
        f"| Physical occupancy | {occ} |",
        f"| Total current rent | {Decimal(s['total_current_rent']):,.2f} |",
    ]
    if s["total_market_rent"]:
        lines.append(f"| Total market rent | {Decimal(s['total_market_rent']):,.2f} |")
    if s["total_sqft"]:
        lines.append(f"| Total sq ft | {s['total_sqft']:,} |")
    met = result.metrics()
    if met.get("economic_occupancy") is not None:
        lines.append(f"| Economic occupancy | {met['economic_occupancy']:.1%} |")
    if met.get("loss_to_lease") is not None:
        lines.append(f"| Loss to lease | {Decimal(met['loss_to_lease']):,.2f} |")
    if s.get("corrections"):
        lines.append(f"| Reviewer corrections | {s['corrections']} |")
    if s.get("acknowledged"):
        lines.append(f"| Accepted issues | {s['acknowledged']} |")
    if result.skipped:
        lines.append(f"| Rows skipped | {', '.join(f'{k} {v}' for k, v in sorted(result.skipped.items()))} |")

    lines += [
        "",
        "## Column mapping",
        "",
        "| Source column | Field | Confidence | Method |",
        "| --- | --- | --- | --- |",
    ]
    for m in result.mappings:
        lines.append(f"| {_md(m.header)} | {m.field or '(not used)'} | {m.confidence:.2f} | {m.method} |")

    lines += ["", "## Issues", ""]
    if not result.issues:
        lines.append("None.")
    for i in result.issues:
        where = f" (row {i.row})" if i.row else ""
        accepted = f" _(accepted: {_md(i.acknowledgment.note)})_" if i.acknowledgment else ""
        lines.append(f"- **{i.severity.value}** `{i.rule}`{where}: {_md(i.message)}{accepted}")
    return "\n".join(lines) + "\n"


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _safe(text: str) -> str:
    """Stop spreadsheet apps from running cell text as a formula (CSV injection, OWASP).

    A tenant name like '=HYPERLINK(...)' is written as "'=HYPERLINK(...)".
    """
    return "'" + text if text.startswith(_FORMULA_START) else text


def _csv_value(v: object) -> object:
    """Money as exact two-decimal text (1300.00, -100.00), dates as ISO, text made formula-safe."""
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, str):
        return _safe(v)
    return jsonable(v)


def _md(text: str) -> str:
    """Escape characters that would break a Markdown table or list."""
    return text.replace("|", "\\|").replace("\n", " ")


_HEADER_FONT = Font(bold=True)
_DERIVED_FILL = PatternFill("solid", fgColor="EEF2FF")
_CORRECTED_FILL = PatternFill("solid", fgColor="FEF3C7")


def write_xlsx(result: CleanResult, path: Path) -> None:
    """A workbook an analyst can drop into an underwriting model.

    Money is written as real numbers with an accounting format, dates as real
    dates. Cells filled by tieout are tinted blue, reviewer corrections amber.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Rent Roll"
    ws.append([*COLUMNS, "section", "source_row"])
    for cell in ws[1]:
        cell.font = _HEADER_FONT
    for row in result.rows:
        values: list[Any] = []
        for c in COLUMNS:
            v = row.get(c)
            if isinstance(v, Decimal):
                v = float(v)  # Excel stores numbers as doubles; the format keeps two decimals
            elif isinstance(v, str):
                v = _safe(v)
            values.append(v)
        ws.append([*values, row.section, row.source_row])
        r = ws.max_row
        for j, c in enumerate(COLUMNS, start=1):
            tv = row.values.get(c)
            cell = ws.cell(r, j)
            if FIELDS_BY_NAME[c].type is FieldType.MONEY:
                cell.number_format = "#,##0.00;(#,##0.00)"
            elif FIELDS_BY_NAME[c].type is FieldType.DATE and isinstance(cell.value, date):
                cell.number_format = "yyyy-mm-dd"
            if tv is not None and tv.correction is not None:
                cell.fill = _CORRECTED_FILL
            elif tv is not None and tv.derived:
                cell.fill = _DERIVED_FILL
    ws.freeze_panes = "B2"
    for j, c in enumerate([*COLUMNS, "section", "source_row"], start=1):
        ws.column_dimensions[get_column_letter(j)].width = max(10, min(28, len(c) + 4))

    issues = wb.create_sheet("Issues")
    issues.append(["severity", "status", "rule", "row", "field", "cells", "message", "note"])
    for cell in issues[1]:
        cell.font = _HEADER_FONT
    for i in result.issues:
        issues.append(
            [
                i.severity.value,
                "open" if i.open else "accepted",
                i.rule,
                i.row,
                i.field,
                " ".join(r.cell for r in i.refs),
                _safe(i.message),
                _safe(i.acknowledgment.note) if i.acknowledgment else None,
            ]
        )

    summary = wb.create_sheet("Summary")
    summary.append(["metric", "value"])
    for cell in summary[1]:
        cell.font = _HEADER_FONT
    for k, v in {**result.summary(), **result.metrics()}.items():
        if isinstance(v, (dict, list)):
            continue
        summary.append([k, v])
    summary.append(["source_file", _safe(result.source_file)])
    summary.append(["generated_by", f"tieout {__version__}"])
    wb.save(path)
