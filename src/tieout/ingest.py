"""Read a source file into a grid of cells that remember where they came from."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
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
    """A sheet of raw values. rows[i][j] is file row i+1, column j+1 (0-based access).

    Values are stored exactly as read: a merged range keeps its value only in its
    top-left cell. Header detection asks for merged_value() so a header like
    "Lease" merged over "Start | End" reaches both columns, while data rows keep
    raw values so a merged section label stays one cell instead of filling every
    column.
    """

    file: str
    sheet: str
    rows: list[list[Any]]
    # (min_row, min_col, max_row, max_col), 0-based inclusive
    merges: list[tuple[int, int, int, int]] = field(default_factory=list)
    # cells that hold a formula whose result was never calculated and saved
    uncomputed: set[tuple[int, int]] = field(default_factory=set)
    _width: int = field(default=-1, repr=False)

    @property
    def width(self) -> int:
        if self._width < 0:
            self._width = max((len(r) for r in self.rows), default=0)
        return self._width

    def value(self, r: int, c: int) -> Any:
        """Raw value; None outside the data."""
        if r < 0 or r >= len(self.rows):
            return None
        row = self.rows[r]
        return row[c] if 0 <= c < len(row) else None

    def merged_value(self, r: int, c: int) -> Any:
        """Value of the merged range covering (r, c), or the raw value if not merged."""
        for r0, c0, r1, c1 in self.merges:
            if r0 <= r <= r1 and c0 <= c <= c1:
                return self.value(r0, c0)
        return self.value(r, c)

    def is_uncomputed(self, r: int, c: int) -> bool:
        return (r, c) in self.uncomputed

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
    merges = [(m.min_row - 1, m.min_col - 1, m.max_row - 1, m.max_col - 1) for m in ws.merged_cells.ranges]

    # data_only hides formulas. A formula whose result was never calculated (files
    # written by scripts or some exporters) reads as an empty cell, which would
    # silently skip a total's tie-out check. Find those cells so we can flag them.
    uncomputed: set[tuple[int, int]] = set()
    formulas = load_workbook(path, data_only=False)[ws.title]
    for r, frow in enumerate(formulas.iter_rows(values_only=True)):
        for c, fv in enumerate(frow):
            if isinstance(fv, str) and fv.startswith("=") and (r >= len(rows) or c >= len(rows[r]) or rows[r][c] is None):
                uncomputed.add((r, c))

    return Grid(file=path.name, sheet=ws.title, rows=_trim(rows), merges=merges, uncomputed=uncomputed)


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
    # Read from a stream, not splitlines(): quoted fields may contain line breaks.
    reader = csv.reader(io.StringIO(text, newline=""), dialect)
    rows: list[list[Any]] = [[(c if c.strip() != "" else None) for c in row] for row in reader]
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
