"""Find the header row(s) in a grid and classify the rows beneath it.

Real exports put report titles, property names and run dates above the table,
split headers over two rows ("Lease" over "Start | End"), insert section
labels ("Building A") and subtotal rows, and repeat the header on each page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
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
    CHARGE = "charge"  # extra charge line belonging to the unit above


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
