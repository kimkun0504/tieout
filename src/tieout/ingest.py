"""Read a source file into a grid of cells that remember where they came from."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter


@dataclass(frozen=True)
class SourceRef:
    """Location of a value in the original file. Rows and columns are 1-based."""

    file: str
    sheet: str
    row: int
    col: int

    @property
    def cell(self) -> str:
        return f"{get_column_letter(self.col)}{self.row}"

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "sheet": self.sheet, "cell": self.cell, "row": self.row, "col": self.col}


@dataclass
class Grid:
    """A rectangular sheet of raw values. rows[i][j] is file row i+1, column j+1."""

    file: str
    sheet: str
    rows: list[list[Any]]

    @property
    def width(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    def value(self, r: int, c: int) -> Any:
        """0-based access that returns None outside the data."""
        if r < 0 or r >= len(self.rows):
            return None
        row = self.rows[r]
        return row[c] if 0 <= c < len(row) else None

    def ref(self, r: int, c: int) -> SourceRef:
        return SourceRef(self.file, self.sheet, r + 1, c + 1)


class UnsupportedFormat(ValueError):
    pass


SUPPORTED_SUFFIXES = {".xlsx", ".xlsm", ".csv", ".tsv", ".txt"}


def read_grid(path: str | Path, sheet: str | None = None) -> Grid:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return _read_excel(path, sheet)
    if suffix in {".csv", ".tsv", ".txt"}:
        return _read_delimited(path)
    if suffix == ".pdf":
        raise UnsupportedFormat(
            "PDF input is not wired up yet. Planned: parse with Docling, then feed tables through this pipeline."
        )
    if suffix == ".xls":
        raise UnsupportedFormat("Legacy .xls is not supported; re-save the file as .xlsx.")
    raise UnsupportedFormat(f"Unsupported file type: {suffix or '(none)'}")


def _read_excel(path: Path, sheet: str | None) -> Grid:
    # data_only=True returns the cached results of formulas instead of the formula text.
    wb = load_workbook(path, data_only=True)
    if sheet is not None:
        if sheet not in wb.sheetnames:
            raise ValueError(f"Sheet {sheet!r} not found. Sheets: {', '.join(wb.sheetnames)}")
        ws = wb[sheet]
    else:
        ws = max(wb.worksheets, key=_filled_cell_count)

    rows: list[list[Any]] = [list(r) for r in ws.iter_rows(values_only=True)]

    # Merged cells only store a value in their top-left cell. Copy it across the
    # range so a header like "Lease" merged over "Start | End" reaches both columns.
    for merged in ws.merged_cells.ranges:
        top_left = rows[merged.min_row - 1][merged.min_col - 1] if merged.min_row - 1 < len(rows) else None
        for r in range(merged.min_row - 1, min(merged.max_row, len(rows))):
            for c in range(merged.min_col - 1, merged.max_col):
                while len(rows[r]) <= c:
                    rows[r].append(None)
                rows[r][c] = top_left

    return Grid(file=path.name, sheet=ws.title, rows=_trim(rows))


def _read_delimited(path: Path) -> Grid:
    raw = path.read_bytes()
    text = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    assert text is not None  # latin-1 never fails

    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel
    rows = [[(c if c.strip() != "" else None) for c in row] for row in csv.reader(text.splitlines(), dialect)]
    return Grid(file=path.name, sheet=path.stem, rows=_trim(rows))


def _filled_cell_count(ws: Any) -> int:
    return sum(1 for row in ws.iter_rows(values_only=True) for v in row if v not in (None, ""))


def _trim(rows: list[list[Any]]) -> list[list[Any]]:
    """Drop trailing empty cells so widths reflect real content. Keeps row positions intact."""
    out = []
    for row in rows:
        row = list(row)
        while row and (row[-1] is None or (isinstance(row[-1], str) and not row[-1].strip())):
            row.pop()
        out.append(row)
    while out and not out[-1]:
        out.pop()
    return out
