"""Read a source file into a grid of cells that remember where they came from."""

from __future__ import annotations

import csv
import io
import zipfile
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
    sheets: list[str] = field(default_factory=list)  # every sheet in the workbook
    row_sheets: list[str] = field(default_factory=list)  # PDFs: the page each row came from
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
        sheet = self.row_sheets[r] if r < len(self.row_sheets) else self.sheet
        return SourceRef(self.file, sheet, r + 1, c + 1)


class UnsupportedFormat(ValueError):
    pass


SUPPORTED_SUFFIXES = {".xlsx", ".xlsm", ".xls", ".csv", ".tsv", ".txt", ".pdf"}


def read_grid(path: str | Path, sheet: str | None = None, name: str | None = None) -> Grid:
    """Read a file. `name` is the display name used in provenance (defaults to the file's own name)."""
    path = Path(path)
    suffix = path.suffix.lower()
    grid: Grid
    if suffix in {".xlsx", ".xlsm"}:
        grid = _read_excel(path, sheet)
    elif suffix == ".xls":
        grid = _read_legacy(path, sheet)
    elif suffix in {".csv", ".tsv", ".txt"}:
        grid = _read_delimited(path)
        if name:
            grid.sheet = Path(name).stem
    elif suffix == ".pdf":
        from tieout.pdf import read_pdf_rows

        rows, pages = read_pdf_rows(path)
        grid = Grid(file=path.name, sheet="PDF", rows=_trim(rows), row_sheets=pages)
    else:
        grid = _unsupported(suffix)
    if name:
        grid.file = name
    return grid


def _read_legacy(path: Path, sheet: str | None) -> Grid:
    from tieout.legacy import LegacyFormatError, read_xls, sniff

    with path.open("rb") as fh:
        if sniff(fh.read(8192)) == "xlsx":
            return _read_excel(path, sheet)
    try:
        rows, merges, sheet_name, sheets = read_xls(path, sheet)
    except LegacyFormatError as e:
        raise UnsupportedFormat(str(e)) from e
    return Grid(file=path.name, sheet=sheet_name, rows=_trim(rows), merges=merges, sheets=sheets)


def _unsupported(suffix: str) -> Grid:
    raise UnsupportedFormat(f"Unsupported file type: {suffix or '(none)'}")


MAX_EXPANDED_BYTES = 400 * 1024 * 1024
MAX_COMPRESSION_RATIO = 250


def check_xlsx(path: Path) -> None:
    """Refuse files that are not real workbooks or would expand to an unsafe size (zip bombs)."""
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
    except zipfile.BadZipFile as e:
        raise UnsupportedFormat("This is not a valid .xlsx file (it may be damaged or password-protected).") from e
    expanded = sum(i.file_size for i in infos)
    packed = sum(i.compress_size for i in infos) or 1
    if expanded > MAX_EXPANDED_BYTES or expanded / packed > MAX_COMPRESSION_RATIO:
        raise UnsupportedFormat(
            f"This workbook expands to {expanded // (1024 * 1024)} MB, which is too large to process safely."
        )


def _read_excel(path: Path, sheet: str | None) -> Grid:
    check_xlsx(path)
    # data_only=True returns the cached results of formulas instead of the formula text.
    # A file object, not the path: openpyxl rejects a workbook whose name doesn't end .xlsx/.xlsm.
    with path.open("rb") as fh:
        wb = load_workbook(fh, data_only=True)
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
    # read_only streams the sheet; this second pass only needs raw cell text.
    formula_fh = path.open("rb")
    formula_wb = load_workbook(formula_fh, data_only=False, read_only=True)
    try:
        for r, frow in enumerate(formula_wb[ws.title].iter_rows(values_only=True)):
            for c, fv in enumerate(frow):
                if (
                    isinstance(fv, str)
                    and fv.startswith("=")
                    and (r >= len(rows) or c >= len(rows[r]) or rows[r][c] is None)
                ):
                    uncomputed.add((r, c))
    finally:
        formula_wb.close()
        formula_fh.close()

    return Grid(
        file=path.name,
        sheet=ws.title,
        rows=_trim(rows),
        merges=merges,
        uncomputed=uncomputed,
        sheets=list(wb.sheetnames),
    )


def decode_text(raw: bytes) -> str:
    """Decode a delimited text export.

    Excel's "Unicode Text" export is UTF-16 (often without telling anyone);
    read as cp1252 it becomes text full of NUL characters. Detect it by its
    byte-order mark, or by NULs in every other byte, before trying UTF-8 and
    the Windows code page. Any stray NULs left are removed: they are never
    data, and older Python csv readers refuse them.
    """
    sample = raw[:4096]
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    elif len(sample) >= 4 and sample[1::2].count(0) > len(sample) // 4:
        text = raw.decode("utf-16-le", errors="replace")
    elif len(sample) >= 4 and sample[0::2].count(0) > len(sample) // 4:
        text = raw.decode("utf-16-be", errors="replace")
    else:
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    return text.replace("\x00", "")


def _read_delimited(path: Path) -> Grid:
    text = decode_text(path.read_bytes())

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
