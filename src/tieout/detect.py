"""Find the header row(s) in a grid and classify the rows beneath it.

Real exports put report titles, property names and run dates above the table,
split headers over two rows ("Lease" over "Start | End"), insert section
labels ("Building A") and subtotal rows, and repeat the header on each page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from enum import Enum
from typing import Any

from tieout.ingest import Grid
from tieout.mapping import MIN_CONFIDENCE, norm_header, score_header
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


def detect_header(grid: Grid) -> HeaderInfo:
    """Score each early row (alone, and joined with the row above) and keep the best."""
    best: HeaderInfo | None = None
    for r in range(min(SCAN_ROWS, len(grid.rows))):
        row = grid.rows[r]
        if sum(1 for v in row if _looks_like_header_cell(v)) < 2:
            continue
        for use_above in (False, True):
            if use_above and r == 0:
                continue
            headers: dict[int, str] = {}
            matched = 0
            for c in range(grid.width):
                cur = _text(grid.value(r, c)) if _looks_like_header_cell(grid.value(r, c)) else ""
                above = _text(grid.value(r - 1, c)) if use_above and _looks_like_header_cell(grid.value(r - 1, c)) else ""
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


def classify_rows(grid: Grid, header: HeaderInfo, unit_col: int | None) -> list[ClassifiedRow]:
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
        if any(_TOTAL_RE.search(t) for t in texts if not _is_number_like(t)):
            out.append(ClassifiedRow(r, RowKind.TOTAL, section, label=next(t for t in texts if _TOTAL_RE.search(t))))
            continue

        same_as_header = sum(1 for c, v in filled if header_norm.get(c) and norm_header(v) == header_norm[c])
        if same_as_header >= max(2, len(filled) // 2):
            out.append(ClassifiedRow(r, RowKind.REPEATED_HEADER, section))
            continue

        # A row with one lonely text cell is a section label ("Building A") or a footnote,
        # even when it sits in the unit column. Exception: a bare unit code like "104B".
        if len(filled) == 1 and not (filled[0][0] == unit_col and _looks_like_unit_code(texts[0])):
            t = texts[0]
            if len(t) <= 60:
                section = t
                out.append(ClassifiedRow(r, RowKind.SECTION, section, label=t))
            else:
                out.append(ClassifiedRow(r, RowKind.NOTE, section, label=t))
            continue

        if unit_col is not None and not _text(grid.value(r, unit_col)):
            out.append(ClassifiedRow(r, RowKind.NOTE, section, label=" | ".join(texts)[:120]))
            continue

        out.append(ClassifiedRow(r, RowKind.DATA, section))
    return out
