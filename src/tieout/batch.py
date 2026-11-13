"""Clean a folder of rent rolls and T-12s in one run.

Each file gets its own output folder; a summary CSV lists every file with
its document type, size, open errors and whether it ties out. A file that
fails to read is recorded with its error and the batch carries on.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from tieout.ingest import SUPPORTED_SUFFIXES
from tieout.mapping import TemplateStore

SUMMARY_FIELDS = [
    "file",
    "document_type",
    "status",
    "as_of",
    "units_or_lines",
    "errors",
    "warnings",
    "acknowledged",
    "occupancy",
    "total_current_rent",
    "noi",
    "output",
    "message",
]


@dataclass
class BatchEntry:
    file: Path
    document_type: str = ""
    status: str = ""  # "ties out" | "needs review" | "failed"
    as_of: date | None = None
    units_or_lines: int | None = None
    errors: int = 0
    warnings: int = 0
    acknowledged: int = 0
    occupancy: float | None = None
    total_current_rent: str | None = None
    noi: str | None = None
    output: Path | None = None
    message: str = ""

    def row(self, root: Path) -> dict[str, Any]:
        def rel(p: Path | None) -> str:
            if p is None:
                return ""
            try:
                return str(p.relative_to(root))
            except ValueError:
                return str(p)

        return {
            "file": rel(self.file),
            "document_type": self.document_type,
            "status": self.status,
            "as_of": self.as_of.isoformat() if self.as_of else "",
            "units_or_lines": "" if self.units_or_lines is None else self.units_or_lines,
            "errors": self.errors,
            "warnings": self.warnings,
            "acknowledged": self.acknowledged,
            "occupancy": "" if self.occupancy is None else self.occupancy,
            "total_current_rent": self.total_current_rent or "",
            "noi": self.noi or "",
            "output": str(self.output) if self.output else "",
            "message": self.message,
        }


@dataclass
class BatchResult:
    root: Path
    entries: list[BatchEntry] = field(default_factory=list)

    @property
    def failed(self) -> list[BatchEntry]:
        return [e for e in self.entries if e.status == "failed"]

    @property
    def needs_review(self) -> list[BatchEntry]:
        return [e for e in self.entries if e.status == "needs review"]

    @property
    def ok(self) -> bool:
        return not self.failed and not self.needs_review


def find_files(root: Path, recursive: bool = False) -> list[Path]:
    """Supported files under `root`, sorted, skipping hidden files and Office lock files (~$x.xlsx)."""
    pattern = "**/*" if recursive else "*"
    out = []
    for p in root.glob(pattern):
        if not p.is_file() or p.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        rel_parts = p.relative_to(root).parts
        if any(part.startswith(".") for part in rel_parts) or p.name.startswith("~$"):
            continue
        out.append(p)
    return sorted(out, key=lambda p: str(p.relative_to(root)).lower())


def _slug(path: Path, root: Path, taken: set[str]) -> str:
    rel = path.relative_to(root)
    base = "__".join([*rel.parent.parts, rel.stem]) or "file"
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-.") or "file"
    slug, n = base, 2
    while slug.lower() in taken:  # case-insensitive filesystems
        slug, n = f"{base}-{n}", n + 1
    taken.add(slug.lower())
    return slug


def run_batch(
    root: Path,
    out: Path,
    *,
    recursive: bool = False,
    templates: TemplateStore | None = None,
    as_of: date | None = None,
    mapper: Any = None,
) -> BatchResult:
    from tieout.export import write_all
    from tieout.ingest import read_grid
    from tieout.pipeline import clean_file
    from tieout.t12 import is_t12, read_t12
    from tieout.t12 import write_outputs as write_t12

    root = root.resolve()
    out.mkdir(parents=True, exist_ok=True)
    result = BatchResult(root=root)
    taken: set[str] = set()
    for path in find_files(root, recursive):
        entry = BatchEntry(file=path)
        result.entries.append(entry)
        dest = out / _slug(path, root, taken)
        try:
            grid = read_grid(path)
            if is_t12(grid):
                stmt = read_t12(grid)
                write_t12(stmt, dest)
                s = stmt.summary()
                entry.document_type = "t12"
                entry.units_or_lines = s["line_items"]
                entry.noi = s["noi"]
                entry.errors, entry.warnings, entry.acknowledged = s["errors"], s["warnings"], s["acknowledged"]
                ok = stmt.ok
            else:
                res = clean_file(path, templates=templates, mapper=mapper, as_of=as_of, grid=grid)
                write_all(res, dest)
                s = res.summary()
                entry.document_type = "rent_roll"
                entry.as_of = res.as_of
                entry.units_or_lines = s["units"]
                entry.occupancy = s["physical_occupancy"]
                entry.total_current_rent = s["total_current_rent"]
                entry.errors, entry.warnings = s["errors"], s["warnings"]
                entry.acknowledged = sum(1 for i in res.issues if not i.open)
                ok = res.ok
            entry.status = "ties out" if ok else "needs review"
            entry.output = dest
        except Exception as e:  # one unreadable file must not sink the batch
            entry.status = "failed"
            entry.message = f"{type(e).__name__}: {e}"[:500]
    write_summary(result, out / "summary.csv")
    return result


def write_summary(result: BatchResult, path: Path) -> Path:
    from tieout.export import _safe

    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=SUMMARY_FIELDS)
        w.writeheader()
        for e in result.entries:
            row = e.row(result.root)
            for k in ("file", "message", "output"):  # free text; numbers stay numbers
                row[k] = _safe(row[k])
            w.writerow(row)
    tmp.replace(path)
    return path


def render_summary(result: BatchResult) -> str:
    n = len(result.entries)
    lines = [f"{n} file{'s' if n != 1 else ''} in {result.root}"]
    width = max((len(str(e.file.relative_to(result.root))) for e in result.entries), default=0)
    for e in result.entries:
        name = str(e.file.relative_to(result.root)).ljust(width)
        if e.status == "failed":
            lines.append(f"  {name}  failed        {e.message}")
            continue
        what = "units" if e.document_type == "rent_roll" else "lines"
        detail = f"{e.units_or_lines} {what}, {e.errors} errors, {e.warnings} warnings"
        lines.append(f"  {name}  {e.status:<12}  {e.document_type:<9}  {detail}")
    lines.append(
        f"{n - len(result.failed) - len(result.needs_review)} tie out, "
        f"{len(result.needs_review)} need review, {len(result.failed)} failed"
    )
    return "\n".join(lines)
