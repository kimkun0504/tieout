"""Write a CleanResult to disk: CSV for spreadsheets, JSON with provenance, issues, and a readable report."""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

from tieout.models import jsonable
from tieout.pipeline import CleanResult
from tieout.schema import RENT_ROLL_FIELDS

COLUMNS = [f.name for f in RENT_ROLL_FIELDS]


def write_all(result: CleanResult, out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(result.source_file).stem
    paths = {
        "csv": out / f"{stem}.clean.csv",
        "json": out / f"{stem}.clean.json",
        "issues": out / f"{stem}.issues.csv",
        "report": out / f"{stem}.report.md",
    }
    write_csv(result, paths["csv"])
    write_json(result, paths["json"])
    write_issues(result, paths["issues"])
    paths["report"].write_text(render_report(result))
    return paths


def write_csv(result: CleanResult, path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS + ["section", "source_row"])
        for row in result.rows:
            w.writerow([_csv_value(row.get(c)) for c in COLUMNS] + [_safe(row.section or ""), row.source_row])


def write_json(result: CleanResult, path: Path) -> None:
    payload = {
        "source": {"file": result.source_file, "sheet": result.sheet, "header_rows": [r + 1 for r in result.header.header_rows]},
        "summary": result.summary(),
        "mappings": [
            {"column": m.column + 1, "header": m.header, "field": m.field, "confidence": m.confidence, "method": m.method}
            for m in result.mappings
        ],
        "rows": [
            {"source_row": r.source_row, "section": r.section, "fields": {k: v.to_dict() for k, v in r.values.items()}}
            for r in result.rows
        ],
        "totals": [
            {"row": t.row, "label": t.label, "section": t.section, "covers_rows": t.scope_rows,
             "amounts": {k: v.to_dict() for k, v in t.amounts.items()}}
            for t in result.totals
        ],
        "issues": [i.to_dict() for i in result.issues],
    }
    path.write_text(json.dumps(payload, indent=2, default=str))


def write_issues(result: CleanResult, path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["severity", "rule", "row", "field", "cells", "message"])
        for i in result.issues:
            w.writerow([i.severity.value, i.rule, i.row or "", i.field or "", " ".join(r.cell for r in i.refs), _safe(i.message)])


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
    if result.skipped:
        lines.append(f"| Rows skipped | {', '.join(f'{k} {v}' for k, v in sorted(result.skipped.items()))} |")

    lines += ["", "## Column mapping", "", "| Source column | Field | Confidence | Method |", "| --- | --- | --- | --- |"]
    for m in result.mappings:
        lines.append(f"| {_md(m.header)} | {m.field or '(not used)'} | {m.confidence:.2f} | {m.method} |")

    lines += ["", "## Issues", ""]
    if not result.issues:
        lines.append("None.")
    for i in result.issues:
        where = f" (row {i.row})" if i.row else ""
        lines.append(f"- **{i.severity.value}** `{i.rule}`{where}: {_md(i.message)}")
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
