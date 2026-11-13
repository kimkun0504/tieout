"""Find the header row(s) in a grid and classify the rows beneath it.

Real exports put report titles, property names and run dates above the table,
split headers over two rows ("Lease" over "Start | End"), insert section
labels ("Building A") and subtotal rows, and repeat the header on each page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date, datetime
from enum import Enum
from typing import Any

from tieout.ingest import Grid, SourceRef
from tieout.mapping import MIN_CONFIDENCE, norm_header, score_header
from tieout.normalize import parse_date
from tieout.schema import RENT_ROLL_FIELDS

SCAN_ROWS = 40
_TOTAL_RE = re.compile(r"^\s*(grand\s+)?(sub\s*-?\s*)?totals?\b|^\s*summary\b|\btotals?\s*:?\s*$", re.I)


class RowKind(str, Enum):
    DATA = "data"
    TOTAL = "total"
    SECTION = "section"
    REPEATED_HEADER = "repeated_header"
    BLANK = "blank"
    NOTE = "note"
    CHARGE = "charge"  # extra charge line belonging to the unit above
    SUMMARY = "summary"  # a report statistic such as "Occupied Units 95" or "Occupancy 95.0%"


@dataclass
class HeaderInfo:
    header_rows: list[int]  # 0-based grid rows that make up the header
    headers: dict[int, str]  # column -> header text (joined across header rows)
    score: int  # number of columns that matched a schema field


@dataclass
class ClassifiedRow:
    index: int  # 0-based grid row
    kind: RowKind
    section: str | None = None
    label: str | None = None
    notes: list[str] = dc_field(default_factory=list)
    stat: str | None = None  # for SUMMARY rows tieout can check: total_units, occupied_units, ...
    stat_col: int | None = None  # where the stated figure is


def _text(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _best_match(h: str) -> float:
    n = norm_header(h)
    return max((score_header(n, f) for f in RENT_ROLL_FIELDS), default=0.0)


def _looks_like_header_cell(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip()) and not _is_number_like(v)


def _is_number_like(s: str) -> bool:
    return bool(re.fullmatch(r"[\s$€£(),.\-\d%]+", s)) and any(ch.isdigit() for ch in s)


def _looks_like_unit_code(s: str) -> bool:
    return len(s) <= 8 and " " not in s.strip() and any(ch.isdigit() for ch in s)


# Statistics printed in a report's footer, which tieout checks against the units it read.
_STATS: dict[str, re.Pattern[str]] = {
    "total_units": re.compile(
        r"^(?:total\s+)?(?:#\s*of\s+|number\s+of\s+|no\.?\s+of\s+)?units?(?:\s+count)?$|^unit\s+count$"
    ),
    "occupied_units": re.compile(r"^(?:total\s+)?(?:#\s*of\s+|number\s+of\s+)?occupied(?:\s+units?)?$"),
    "vacant_units": re.compile(r"^(?:total\s+)?(?:#\s*of\s+|number\s+of\s+)?vacant(?:\s+units?)?$"),
    "occupancy": re.compile(
        r"^(?:physical\s+)?occupancy(?:\s*%|\s+percent(?:age)?|\s+rate)?$|^(?:%|percent)\s+occupied$"
    ),
}
# Other footer statistics: recognised so they are not read as units, but not checked.
_SUMMARY_WORDS = re.compile(
    r"\b(?:units|occupan\w*|occupied|vacan\w*|leased|pre-?leased|average|avg|percent|rate|summary|"
    r"statistics|potential|loss\s+to\s+lease|on\s+notice|count)\b|%",
    re.I,
)


def _stat_label(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().rstrip(":=").strip()).lower()


def _summary_row(filled: list[tuple[int, Any]], unit_col: int, unit_text: str) -> tuple[str | None, int] | None:
    """(stat, value column) when this row is a report statistic rather than a unit; None otherwise.

    A statistic is the row's leftmost cell, sitting in or before the unit column, a text label
    with no digits (unit codes have them), followed by at most a few figures.
    """
    c0, v0 = filled[0]
    label_cell = (c0, _text(v0))
    if c0 > unit_col or _is_number_like(label_cell[1]) or any(ch.isdigit() for ch in label_cell[1]):
        return None
    if unit_text and unit_text != label_cell[1]:
        return None  # the unit column holds something else: this is a unit row
    figures = [c for c, v in filled if c > label_cell[0] and (isinstance(v, (int, float)) or _is_number_like(_text(v)))]
    if not figures or len(filled) > 4:
        return None
    label = _stat_label(label_cell[1])
    stat = next((k for k, pat in _STATS.items() if pat.match(label)), None)
    if stat is None and not _SUMMARY_WORDS.search(label):
        return None
    return stat, figures[0]


def detect_header(grid: Grid) -> HeaderInfo:
    """Score each early row (alone, and joined with the row above) and keep the best."""
    best: HeaderInfo | None = None
    for r in range(min(SCAN_ROWS, len(grid.rows))):
        if sum(1 for c in range(grid.width) if _looks_like_header_cell(grid.merged_value(r, c))) < 2:
            continue
        for use_above in (False, True):
            if use_above and r == 0:
                continue
            headers: dict[int, str] = {}
            matched = 0
            for c in range(grid.width):
                cur_v, above_v = grid.merged_value(r, c), grid.merged_value(r - 1, c)
                cur = _text(cur_v) if _looks_like_header_cell(cur_v) else ""
                above = _text(above_v) if use_above and _looks_like_header_cell(above_v) else ""
                text = f"{above} {cur}".strip() if use_above and above and above != cur else cur
                if not text:
                    continue
                headers[c] = text
                if _best_match(text) >= MIN_CONFIDENCE:
                    matched += 1
            # Joining with the row above must earn its keep: require a strict improvement.
            info = HeaderInfo([r - 1, r] if use_above else [r], headers, matched)
            if best is None or info.score > best.score:
                best = info
    if best is None or best.score < 2:
        raise ValueError("Could not find a header row: fewer than two columns look like rent roll fields.")
    return best


_NOISE_RE = re.compile(
    r"^(page\s*\d+(\s*(of|/)\s*\d+)?|\(?cont(inued|'d|\.)?\)?|printed\b.*|run\s+(date|on)\b.*|"
    r"report\s+(date|run)\b.*|as\s+of\b.*|confidential\b.*|\*+.*|note:.*)$",
    re.I,
)


def _is_noise(v: Any) -> bool:
    """Page numbers, run dates and footnotes that sit alone on a row."""
    if isinstance(v, (int, float)) or hasattr(v, "year"):
        return True  # a lone number or date is a page number or a printed date
    return bool(_NOISE_RE.match(_text(v)))


def classify_rows(
    grid: Grid, header: HeaderInfo, unit_col: int | None, charge_cols: tuple[int, ...] = ()
) -> list[ClassifiedRow]:
    """Label each row below the header. Order matters:
    blank -> repeated header -> total -> charge line -> lone cell (section / noise) -> no unit -> data.
    """
    start = max(header.header_rows) + 1
    header_norm = {c: norm_header(t) for c, t in header.headers.items()}
    out: list[ClassifiedRow] = []
    section: str | None = None

    for r in range(start, len(grid.rows)):
        row = grid.rows[r]
        filled = [(c, v) for c, v in enumerate(row) if _text(v)]
        if not filled:
            out.append(ClassifiedRow(r, RowKind.BLANK, section))
            continue
        texts = [_text(v) for _, v in filled]
        unit_text = _text(grid.value(r, unit_col)) if unit_col is not None else ""

        # A repeated page header can contain words like "Total Charges", so it is
        # recognised before totals (finding 4).
        same_as_header = sum(1 for c, v in filled if header_norm.get(c) and norm_header(v) == header_norm[c])
        if same_as_header >= max(2, (len(filled) + 1) // 2):
            out.append(ClassifiedRow(r, RowKind.REPEATED_HEADER, section))
            continue

        summary = _summary_row(filled, unit_col, unit_text) if unit_col is not None else None
        if summary is not None:
            out.append(ClassifiedRow(r, RowKind.SUMMARY, section, label=texts[0], stat=summary[0], stat_col=summary[1]))
            continue

        # A total label never sits next to a real unit code. "Total Wine & More" in
        # the tenant column of unit 101 is a tenant, not a total (finding 3).
        if not (unit_text and _looks_like_unit_code(unit_text) and not _TOTAL_RE.search(unit_text)):
            label = next((t for t in texts if not _is_number_like(t) and _TOTAL_RE.search(t)), None)
            if label is not None:
                out.append(ClassifiedRow(r, RowKind.TOTAL, section, label=label))
                continue

        # Charge-line layouts list one unit's charges on several rows; only the first
        # carries the unit. A row with no unit whose cells all sit in the charge
        # columns, right after a unit or another charge line, belongs to that unit.
        prev = next((o for o in reversed(out) if o.kind is not RowKind.BLANK), None)
        if (
            charge_cols
            and not unit_text
            and prev is not None
            and prev.kind in (RowKind.DATA, RowKind.CHARGE)
            and all(c in charge_cols for c, _ in filled)
        ):
            out.append(ClassifiedRow(r, RowKind.CHARGE, section))
            continue

        if len(filled) == 1 and not (filled[0][0] == unit_col and _looks_like_unit_code(texts[0])):
            v = filled[0][1]
            if _is_noise(v) or len(texts[0]) > 60:
                # Page numbers and footnotes must not start a new section, or
                # duplicates across a page break would go unnoticed (finding 12).
                out.append(ClassifiedRow(r, RowKind.NOTE, section, label=texts[0]))
            else:
                section = texts[0]
                out.append(ClassifiedRow(r, RowKind.SECTION, section, label=section))
            continue

        if unit_col is not None and not unit_text:
            out.append(ClassifiedRow(r, RowKind.NOTE, section, label=" | ".join(texts)[:120]))
            continue

        out.append(ClassifiedRow(r, RowKind.DATA, section))
    return out


# --- report date ------------------------------------------------------------

# Labels ranked by how surely they name the date the roll describes. A "printed" or
# "run" date is when the report was generated, not what it covers, so it never counts.
_DATE_LABELS: list[tuple[int, re.Pattern[str]]] = [
    (3, re.compile(r"\bas[\s-]*of(?:\s+date)?\b", re.I)),
    (2, re.compile(r"\b(?:report|effective|statement)\s+date\b|\bperiod\s+end(?:ing|ed)?\b|\bdated\b", re.I)),
]
_NOT_REPORT_DATE = re.compile(r"\b(?:print(?:ed)?|run|generated|created|exported|downloaded)\b", re.I)
_DATE_IN_TEXT = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?,?\s+\d{4}",
    re.I,
)
TITLE_ROWS = 15  # report titles sit above the header, within the first few rows


@dataclass
class ReportDate:
    value: date
    ref: SourceRef
    text: str  # the cell text it was read from, for the reviewer


def _as_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        m = _DATE_IN_TEXT.search(v)
        if m:
            parsed, problem = parse_date(m.group(0))
            if isinstance(parsed, date) and problem is None:
                return parsed
    return None


def find_report_date(grid: Grid, header: HeaderInfo | None = None) -> ReportDate | None:
    """The "as of" date printed in the title rows above the header, if there is exactly one.

    Reads "As of 10/31/2026", "As Of = 10/31/2026" (Yardi), "Report Date: Oct 31, 2026", or a
    label cell followed by a date cell. Printed/run dates are ignored. Returns None when no
    labelled date is found or the best-ranked labels disagree, so a guess never stands in
    for the reviewer's own report date.
    """
    stop = min(header.header_rows[0] if header and header.header_rows else TITLE_ROWS, TITLE_ROWS)
    found: list[tuple[int, date, int, int, str]] = []  # rank, date, row, col, text
    for r in range(stop):
        row = grid.rows[r] if r < len(grid.rows) else []
        for c, v in enumerate(row):
            if not isinstance(v, str) or not v.strip() or _NOT_REPORT_DATE.search(v):
                continue
            hit = next(((rk, m) for rk, pat in _DATE_LABELS if (m := pat.search(v))), None)
            if hit is None:
                continue
            rank, label = hit
            d = _as_date(v[label.end() :])
            if d is None:  # label alone; the date is in the next filled cell on the row
                nxt = next(((j, row[j]) for j in range(c + 1, len(row)) if row[j] not in (None, "")), None)
                if nxt is not None:
                    d = _as_date(nxt[1])
            if d is not None and 1990 <= d.year <= 2100:
                found.append((rank, d, r, c, v.strip()))
    if not found:
        return None
    best = max(f[0] for f in found)
    top = [f for f in found if f[0] == best]
    if len({f[1] for f in top}) != 1:
        return None
    _, d, r, c, text = top[0]
    return ReportDate(d, SourceRef(grid.file, grid.sheet, r + 1, c + 1), text[:120])
