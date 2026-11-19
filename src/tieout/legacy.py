"""Read files saved with a .xls name.

A ".xls" from a property-management system is one of three things:

* a real Excel 97-2003 workbook (BIFF, an OLE file starting D0 CF 11 E0), read with xlrd;
* an HTML table that the system named .xls so Excel would open it (very common
  for "Export to Excel" buttons);
* an Excel 2003 XML Spreadsheet;
* occasionally, a modern .xlsx with the old extension.

The bytes decide, not the name.
"""

from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from defusedxml import ElementTree as SafeElementTree

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
MAX_LEGACY_CELLS = 2_000_000


class LegacyFormatError(ValueError):
    pass


Merge = tuple[int, int, int, int]  # (min_row, min_col, max_row, max_col), 0-based inclusive


def sniff(raw: bytes) -> str:
    head = raw[:2048].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if raw.startswith(OLE_MAGIC):
        return "biff"
    if raw.startswith(b"PK\x03\x04"):
        return "xlsx"  # a modern workbook saved with the old extension
    if head.startswith(b"<?xml") and b"urn:schemas-microsoft-com:office:spreadsheet" in raw[:8192]:
        return "spreadsheetml"
    if head.startswith((b"<", b"\xff\xfe<", b"\xfe\xff")) or b"<table" in raw[:65536].lower():
        return "html"
    return "unknown"


def read_xls(path: Path, sheet: str | None) -> tuple[list[list[Any]], list[Merge], str, list[str]]:
    """Rows, merges, the sheet read, and every sheet name."""
    raw = path.read_bytes()
    kind = sniff(raw)
    if kind == "biff":
        return _read_biff(raw, sheet)
    if kind == "spreadsheetml":
        return _read_spreadsheetml(raw, sheet)
    if kind == "html":
        rows, merges = read_html_table(_decode(raw))
        return rows, merges, path.stem, [path.stem]
    raise LegacyFormatError("This .xls file is not an Excel workbook, an HTML table or an XML spreadsheet.")


def _decode(raw: bytes) -> str:
    from tieout.ingest import decode_text

    text = decode_text(raw)
    m = re.search(r"<meta[^>]+charset=[\"']?([\w-]+)", text[:4096], re.I)
    if m and m.group(1).lower() not in {"utf-8", "utf8"}:
        try:
            return raw.decode(m.group(1))
        except (LookupError, UnicodeDecodeError):
            pass
    return text


# --- BIFF ---------------------------------------------------------------------


def _read_biff(raw: bytes, sheet: str | None) -> tuple[list[list[Any]], list[Merge], str, list[str]]:
    try:
        import xlrd
    except ImportError as e:  # pragma: no cover - xlrd is a core dependency
        raise LegacyFormatError("Reading .xls needs xlrd: pip install xlrd") from e
    try:
        wb = xlrd.open_workbook(file_contents=raw, formatting_info=True, on_demand=True)
    except xlrd.XLRDError as e:
        msg = str(e)
        if "encrypt" in msg.lower():
            raise LegacyFormatError("This .xls file is password-protected; remove the password and try again.") from e
        raise LegacyFormatError(f"Could not read this .xls file ({msg}).") from e
    except Exception as e:  # xlrd raises assorted errors on damaged files
        raise LegacyFormatError("Could not read this .xls file; it may be damaged.") from e
    names = wb.sheet_names()
    try:
        if sheet is not None:
            if sheet not in names:
                raise ValueError(f"Sheet {sheet!r} not found. Sheets: {', '.join(names)}")
            ws = wb.sheet_by_name(sheet)
        else:
            ws = max((wb.sheet_by_index(i) for i in range(wb.nsheets)), key=_biff_filled)
        if ws.nrows * ws.ncols > MAX_LEGACY_CELLS:
            raise LegacyFormatError("This sheet is too large to process safely.")
        rows = [[_biff_value(ws.cell(r, c), wb.datemode) for c in range(ws.ncols)] for r in range(ws.nrows)]
        merges = [(r0, c0, r1 - 1, c1 - 1) for r0, r1, c0, c1 in ws.merged_cells]
        return rows, merges, ws.name, names
    finally:
        wb.release_resources()


def _biff_filled(ws: Any) -> int:
    import xlrd

    return sum(1 for r in range(ws.nrows) for t in ws.row_types(r) if t not in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK))


def _biff_value(cell: Any, datemode: int) -> Any:
    import xlrd

    t, v = cell.ctype, cell.value
    if t in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
        return None
    if t == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate.xldate_as_datetime(v, datemode)
        except (xlrd.xldate.XLDateError, OverflowError, ValueError):
            return v
    if t == xlrd.XL_CELL_BOOLEAN:
        return bool(v)
    if t == xlrd.XL_CELL_NUMBER and float(v).is_integer() and abs(v) < 2**53:
        return int(v)
    return v


# --- HTML ---------------------------------------------------------------------


class _TableParser(HTMLParser):
    """Collect every <table> as rows of cell text, honouring colspan and rowspan.

    Each open table keeps its own current row and cell, so a table nested inside
    a cell doesn't disturb the cell around it.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[tuple[list[list[Any]], list[Merge]]] = []
        self._stack: list[dict[str, Any]] = []
        self._skip = 0  # inside <script>/<style>

    @staticmethod
    def _new_table() -> dict[str, Any]:
        return {"rows": [], "merges": [], "pending": set(), "row": None, "col": 0, "cell": None, "span": (1, 1)}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "table":
            self._stack.append(self._new_table())
        elif not self._stack:
            return
        elif tag == "tr":
            self._end_row()
            t = self._stack[-1]
            t["row"], t["col"] = [], 0
        elif tag in ("td", "th"):
            t = self._stack[-1]
            self._end_cell()
            if t["row"] is None:
                t["row"], t["col"] = [], 0
            a = dict(attrs)
            t["cell"] = []
            t["span"] = (_span(a.get("rowspan")), _span(a.get("colspan")))
        elif tag == "br" and self._stack[-1]["cell"] is not None:
            self._stack[-1]["cell"].append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif not self._stack:
            return
        elif tag in ("td", "th"):
            self._end_cell()
        elif tag == "tr":
            self._end_row()
        elif tag == "table":
            self._end_row()
            t = self._stack.pop()
            self.tables.append((t["rows"], t["merges"]))

    def handle_data(self, data: str) -> None:
        if self._stack and self._stack[-1]["cell"] is not None and not self._skip:
            self._stack[-1]["cell"].append(data)

    def _end_cell(self) -> None:
        if not self._stack or self._stack[-1]["cell"] is None:
            return
        t = self._stack[-1]
        text = re.sub(r"\s+", " ", "".join(t["cell"]).replace("\xa0", " ")).strip()
        t["cell"] = None
        rowspan, colspan = t["span"]
        r = len(t["rows"])
        col = self._skip_pending(t, r, t["col"])
        row: list[Any] = t["row"]
        row.append(text or None)
        row.extend([None] * (colspan - 1))
        if rowspan > 1 or colspan > 1:
            t["merges"].append((r, col, r + rowspan - 1, col + colspan - 1))
            for rr in range(r + 1, r + rowspan):
                for cc in range(col, col + colspan):
                    t["pending"].add((rr, cc))
        t["col"] = col + colspan
        if len(row) * (r + 1) > MAX_LEGACY_CELLS or len(t["pending"]) > MAX_LEGACY_CELLS:
            raise LegacyFormatError("This table is too large to process safely.")

    @staticmethod
    def _skip_pending(t: dict[str, Any], r: int, col: int) -> int:
        """Step over cells that a rowspan from an earlier row already covers."""
        row = t["row"]
        while len(row) < col:
            row.append(None)
        while (r, col) in t["pending"]:
            t["pending"].discard((r, col))
            row.append(None)
            col += 1
        return col

    def _end_row(self) -> None:
        self._end_cell()
        if not self._stack:
            return
        t = self._stack[-1]
        if t["row"] is not None:
            r = len(t["rows"])
            t["col"] = self._skip_pending(t, r, t["col"])  # trailing cells covered by a rowspan
            t["rows"].append(t["row"])
            t["row"] = None


def _span(v: str | None) -> int:
    try:
        return max(1, min(int(str(v).strip()), 1000))
    except (TypeError, ValueError):
        return 1


def read_html_table(html: str) -> tuple[list[list[Any]], list[Merge]]:
    """The biggest table in an HTML document (by filled cells)."""
    p = _TableParser()
    p.feed(html)
    p.close()
    while p._stack:  # unclosed tables in sloppy exports
        p.handle_endtag("table")
    if not p.tables:
        raise LegacyFormatError("No table found in this file.")
    rows, merges = max(p.tables, key=lambda t: sum(1 for row in t[0] for v in row if v not in (None, "")))
    return rows, merges


# --- Excel 2003 XML -----------------------------------------------------------

_SS = "{urn:schemas-microsoft-com:office:spreadsheet}"


def _read_spreadsheetml(raw: bytes, sheet: str | None) -> tuple[list[list[Any]], list[Merge], str, list[str]]:
    if re.search(rb"<!(DOCTYPE|ENTITY)", raw[:65536], re.I):
        raise LegacyFormatError("XML spreadsheets with DOCTYPE or ENTITY declarations are refused.")
    try:
        root = SafeElementTree.fromstring(raw)
    except ElementTree.ParseError as e:
        raise LegacyFormatError("Could not read this XML spreadsheet; it may be damaged.") from e
    sheets = root.findall(f"{_SS}Worksheet")
    names = [ws.get(f"{_SS}Name") or f"Sheet{i + 1}" for i, ws in enumerate(sheets)]
    if not sheets:
        raise LegacyFormatError("This XML spreadsheet has no worksheets.")
    parsed = [_ssml_sheet(ws) for ws in sheets]
    if sheet is not None:
        if sheet not in names:
            raise ValueError(f"Sheet {sheet!r} not found. Sheets: {', '.join(names)}")
        i = names.index(sheet)
    else:
        i = max(range(len(parsed)), key=lambda k: sum(1 for row in parsed[k][0] for v in row if v is not None))
    return parsed[i][0], parsed[i][1], names[i], names


def _ssml_sheet(ws: ElementTree.Element) -> tuple[list[list[Any]], list[Merge]]:
    rows: list[list[Any]] = []
    merges: list[Merge] = []
    table = ws.find(f"{_SS}Table")
    if table is None:
        return rows, merges
    r = -1
    for row_el in table.findall(f"{_SS}Row"):
        idx = row_el.get(f"{_SS}Index")
        r = int(idx) - 1 if idx else r + 1
        while len(rows) <= r:
            rows.append([])
        c = -1
        for cell in row_el.findall(f"{_SS}Cell"):
            cidx = cell.get(f"{_SS}Index")
            c = int(cidx) - 1 if cidx else c + 1
            row = rows[r]
            while len(row) <= c:
                row.append(None)
            data = cell.find(f"{_SS}Data")
            row[c] = _ssml_value(data) if data is not None else None
            across = int(cell.get(f"{_SS}MergeAcross") or 0)
            down = int(cell.get(f"{_SS}MergeDown") or 0)
            if across or down:
                merges.append((r, c, r + down, c + across))
            c += across
        if len(rows) * max((len(x) for x in rows), default=0) > MAX_LEGACY_CELLS:
            raise LegacyFormatError("This sheet is too large to process safely.")
    return rows, merges


def _ssml_value(data: ElementTree.Element) -> Any:
    text = "".join(data.itertext())
    kind = data.get(f"{_SS}Type")
    if kind == "Number":
        try:
            f = float(text)
            return int(f) if f.is_integer() and abs(f) < 2**53 else f
        except ValueError:
            return text
    if kind == "DateTime":
        try:
            return datetime.fromisoformat(text.rstrip("Z")[:26])
        except ValueError:
            return text
    if kind == "Boolean":
        return text.strip() == "1"
    return text if text.strip() else None
