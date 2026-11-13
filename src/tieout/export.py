"""Write a CleanResult to disk: CSV for spreadsheets, JSON with provenance, issues, and a readable report."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from tieout import __version__
from tieout.models import Severity, jsonable
from tieout.pipeline import CleanResult, override_keys
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
        "jsonl": out / f"{stem}.records.jsonl",
        "datapackage": out / f"{stem}.datapackage.json",
    }
    write_jsonl(result, paths["jsonl"])
    write_xlsx(result, paths["xlsx"])
    write_csv(result, paths["csv"])
    write_json(result, paths["json"])
    write_issues(result, paths["issues"])
    paths["report"].write_text(render_report(result), encoding="utf-8")
    write_datapackage(result, paths["datapackage"], paths["csv"].name, paths["issues"].name)
    return paths


def write_csv(result: CleanResult, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([*COLUMNS, "section", "source_row"])
        for row in result.rows:
            w.writerow([_csv_value(row.get(c)) for c in COLUMNS] + [_safe(row.section or ""), row.source_row])


def to_payload(result: CleanResult) -> dict[str, Any]:
    """Everything about a run as JSON-safe data: the contract shared by the JSON export and the API."""
    keys = override_keys(result.mappings)
    return {
        "document_type": "rent_roll",
        "tieout_version": __version__,
        "source": {
            "file": result.source_file,
            "sheet": result.sheet,
            "sheets": result.sheets,
            "header_rows": [r + 1 for r in result.header.header_rows],
        },
        "as_of": result.as_of.isoformat() if result.as_of else None,
        "report_date": (
            {
                "value": result.report_date.value.isoformat(),
                "cell": result.report_date.ref.to_dict(),
                "text": result.report_date.text,
            }
            if result.report_date
            else None
        ),
        "stated_figures": [
            {"stat": f.stat, "label": f.label, "stated": jsonable(f.raw), "cell": f.ref.to_dict()}
            for f in result.stated
        ],
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
                "key": keys[m.column],
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
    path.write_text(json.dumps(to_payload(result), indent=2, default=str, ensure_ascii=False), encoding="utf-8")


_TABLE_TYPES = {
    FieldType.TEXT: "string",
    FieldType.STATUS: "string",
    FieldType.MONEY: "number",
    FieldType.NUMBER: "number",
    FieldType.DATE: "date",
}


def to_datapackage(result: CleanResult, csv_name: str, issues_name: str) -> dict[str, Any]:
    """A Frictionless Data Package describing the clean CSV and the issues CSV.

    Lets pandas, DuckDB, Frictionless, CKAN and data catalogs load the files with
    the right types instead of guessing, and records where the data came from.
    """
    from tieout.schema import STATUS_VALUES

    def field(name: str) -> dict[str, Any]:
        spec = FIELDS_BY_NAME[name]
        f: dict[str, Any] = {"name": name, "type": _TABLE_TYPES[spec.type], "description": spec.description}
        if spec.type is FieldType.MONEY:
            f["description"] += " (USD, two decimals)"
        if name == "unit":  # every unit row has one; rent may be blank (vacant units)
            f["constraints"] = {"required": True}
        if spec.type is FieldType.STATUS:
            f["constraints"] = {"enum": list(STATUS_VALUES)}
        return f

    s = result.summary()
    stem = Path(csv_name).name.split(".")[0]
    slug = "".join(ch if ch.isalnum() else "-" for ch in stem.lower()).strip("-") or "rent-roll"
    return {
        "profile": "tabular-data-package",
        "name": slug,
        "title": f"Rent roll: {result.source_file}",
        "created": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "sources": [{"title": result.source_file, "path": result.source_file}],
        "tieout": {
            "version": __version__,
            "sheet": result.sheet,
            "as_of": result.as_of.isoformat() if result.as_of else None,
            "ties_out": result.ok,
            "open_errors": s["errors"],
            "open_warnings": s["warnings"],
            "accepted": s["acknowledged"],
            "corrections": s["corrections"],
        },
        "resources": [
            {
                "name": "units",
                "path": csv_name,
                "profile": "tabular-data-resource",
                "format": "csv",
                "mediatype": "text/csv",
                "encoding": "utf-8",
                "schema": {
                    "fields": [
                        *(field(c) for c in COLUMNS),
                        {"name": "section", "type": "string", "description": "Section or building label"},
                        {
                            "name": "source_row",
                            "type": "integer",
                            "description": "Row in the original file this unit came from",
                            "constraints": {"required": True, "minimum": 1},
                        },
                    ],
                    "missingValues": [""],
                    "primaryKey": ["source_row"],
                },
            },
            {
                "name": "issues",
                "path": issues_name,
                "profile": "tabular-data-resource",
                "format": "csv",
                "mediatype": "text/csv",
                "encoding": "utf-8",
                "schema": {
                    "fields": [
                        {"name": "id", "type": "string"},
                        {"name": "severity", "type": "string", "constraints": {"enum": ["error", "warning", "info"]}},
                        {"name": "status", "type": "string", "constraints": {"enum": ["open", "accepted"]}},
                        {"name": "rule", "type": "string"},
                        {"name": "row", "type": "integer"},
                        {"name": "field", "type": "string"},
                        {"name": "cells", "type": "string", "description": "Source cells, space separated"},
                        {"name": "message", "type": "string"},
                        {"name": "note", "type": "string", "description": "Reviewer's note when accepted"},
                    ],
                    "missingValues": [""],
                    "primaryKey": ["id"],
                },
            },
        ],
    }


def write_datapackage(result: CleanResult, path: Path, csv_name: str, issues_name: str) -> None:
    path.write_text(
        json.dumps(to_datapackage(result, csv_name, issues_name), indent=2, ensure_ascii=False), encoding="utf-8"
    )


def write_issues(result: CleanResult, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
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


def _report_date_line(result: CleanResult) -> str:
    rd = result.report_date
    if result.as_of is None:
        return "Report date: not stated in the file and not given; lease-expiry checks were skipped."
    if rd and rd.value == result.as_of:
        return f"Report date: {result.as_of:%m/%d/%Y}, read from cell {rd.ref.cell} ({_md(rd.text)})."
    if rd:
        return f"Report date: {result.as_of:%m/%d/%Y}, set by the reviewer (the file says {rd.value:%m/%d/%Y})."
    return f"Report date: {result.as_of:%m/%d/%Y}, set by the reviewer."


def render_report(result: CleanResult) -> str:
    s = result.summary()
    occ = f"{s['physical_occupancy']:.1%}" if s["physical_occupancy"] is not None else "n/a"
    lines = [
        f"# tieout report: {result.source_file}",
        "",
        f"Sheet **{result.sheet}**, header on row(s) {', '.join(str(r + 1) for r in result.header.header_rows)}.",
        "",
        _report_date_line(result),
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
                i.message,
                i.acknowledgment.note if i.acknowledgment else None,
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
    summary.append(["source_file", result.source_file])
    summary.append(["as_of", result.as_of])
    summary.append(["generated_by", f"tieout {__version__}"])

    fields = wb.create_sheet("Fields")
    fields.append(["column", "type", "description"])
    for cell in fields[1]:
        cell.font = _HEADER_FONT
    for name in COLUMNS:
        spec = FIELDS_BY_NAME[name]
        fields.append([name, spec.type.value, spec.description])
    fields.append(["section", "text", "Section or building label above the unit"])
    fields.append(["source_row", "number", "Row in the original file this unit came from"])
    fields.append([])
    fields.append(["Shading on the Rent Roll sheet: blue = filled in by tieout, amber = corrected by a reviewer."])
    fields.column_dimensions["A"].width = 18
    fields.column_dimensions["C"].width = 70
    _text_never_formula(wb)
    wb.save(path)


def _money_words(v: Any) -> str:
    return f"${Decimal(v):,.2f}" if v is not None else ""


def _date_words(v: Any) -> str:
    return f"{v:%b} {v.day}, {v.year}" if isinstance(v, date) else ""


def unit_text(row: Any, redact: bool) -> str:
    """One unit as plain sentences an LLM can retrieve and quote."""
    g = row.get
    unit = g("unit") or f"row {row.source_row}"
    bits = [str(x) for x in (g("unit_type"), f"{g('sqft'):,} sq ft" if g("sqft") else None) if x]
    head = f"Unit {unit}" + (f" ({', '.join(bits)})" if bits else "") + (f" in {row.section}" if row.section else "")
    status = g("status") or "status unknown"
    tenant = g("tenant")
    who = f", leased to {tenant}" if tenant and not redact else (", leased" if tenant else "")
    if status == "future":
        signer = f" with {tenant}" if tenant and not redact else ""
        parts = [f"{head} has a future lease{signer} that has not started yet."]
    else:
        parts = [f"{head} is {status}{who}."]
    if g("current_rent") is not None:
        rent = f"Rent is {_money_words(g('current_rent'))} per month"
        if g("market_rent") is not None:
            rent += f" against market rent of {_money_words(g('market_rent'))}"
        parts.append(rent + ".")
    extras = [
        f"{label} {_money_words(g(f))}"
        for f, label in (("concessions", "concessions"), ("other_charges", "other charges"), ("deposit", "deposit"))
        if g(f) is not None
    ]
    if extras:
        parts.append("Also: " + ", ".join(extras) + ".")
    if g("lease_start") or g("lease_end"):
        parts.append(f"Lease runs {_date_words(g('lease_start')) or '?'} to {_date_words(g('lease_end')) or '?'}.")
    if g("move_in"):
        parts.append(f"Moved in {_date_words(g('move_in'))}.")
    return " ".join(parts)


def to_jsonl_records(result: CleanResult, redact_tenants: bool = False) -> list[dict[str, Any]]:
    """Retrieval-ready records: one per unit plus a property summary.

    Each record has `text` (plain sentences for embedding), `fields` (typed
    values) and `metadata` (source file, row, provenance flags, review state)
    so an answer generated from a record can be traced back to its cell.
    """
    open_rows = {i.row for i in result.open_issues if i.row is not None and i.severity is not Severity.INFO}
    base = {
        "source_file": result.source_file,
        "sheet": result.sheet,
        "tieout_version": __version__,
        "as_of": result.as_of.isoformat() if result.as_of else None,
        "file_ok": result.ok,
    }
    records: list[dict[str, Any]] = []
    for row in result.rows:
        fields = {k: jsonable(v.value) for k, v in row.values.items()}
        if redact_tenants:
            fields.pop("tenant", None)
        records.append(
            {
                "id": f"{result.source_file}#row-{row.source_row}",
                "type": "unit",
                "text": unit_text(row, redact_tenants),
                "fields": fields,
                "metadata": {
                    **base,
                    "source_row": row.source_row,
                    "section": row.section,
                    "cells": {k: v.source.cell for k, v in row.values.items() if v.source and k in fields},
                    "derived_fields": sorted(k for k, v in row.values.items() if v.derived and k in fields),
                    "corrected_fields": sorted(k for k, v in row.values.items() if v.correction and k in fields),
                    "has_open_issues": row.source_row in open_rows,
                },
            }
        )
    m = result.metrics()
    summary = (
        f"{result.source_file}: {m['units']} units, {m['occupied_units']} occupied "
        f"({(m['physical_occupancy'] or 0):.1%} physical occupancy). In-place rent {_money_words(m['in_place_rent'])} "
        f"per month."
        + (f" Gross potential rent {_money_words(m['gross_potential_rent'])}." if m["gross_potential_rent"] else "")
        + (f" Loss to lease {_money_words(m['loss_to_lease'])}." if m["loss_to_lease"] else "")
        + ("" if result.ok else " Some totals or values still need review.")
    )
    records.append(
        {
            "id": f"{result.source_file}#summary",
            "type": "property_summary",
            "text": summary,
            "fields": {k: v for k, v in m.items() if not isinstance(v, (list, dict))},
            "metadata": base,
        }
    )
    return records


def write_jsonl(result: CleanResult, path: Path, redact_tenants: bool = False) -> None:
    with path.open("w", encoding="utf-8") as f:
        for rec in to_jsonl_records(result, redact_tenants):
            f.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")


def _text_never_formula(wb: Workbook) -> None:
    """openpyxl stores any string starting with "=" as a formula. Every value here is
    data, so force those cells back to text: exact, and never executed."""
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    cell.data_type = "s"
