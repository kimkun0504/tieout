"""Read rent roll tables out of text-based PDF exports.

Property-management PDFs usually have no ruling lines, and a centred title or
page footer confuses generic table finders. Rent rolls have one thing we can
rely on instead: a header line naming the columns. So, per page:

1. Group words into lines by vertical position.
2. Within a line, join words separated by ordinary spacing into phrases
   ("Novak, Petra", "Market Rent"); a wider gap starts a new phrase.
3. Find the header line (the line with the most phrases that look like
   rent roll field names) and use its phrases as column anchors.
4. Put every other phrase in the column whose span contains its centre.

Pages without their own header reuse the previous page's columns. Lines
above the header (titles) become single-cell rows, which the pipeline
already ignores. Scanned PDFs have no text layer and are refused with a
clear message: they need OCR, which this module does not do.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from tieout.mapping import MIN_CONFIDENCE, norm_header, score_header
from tieout.schema import RENT_ROLL_FIELDS

LINE_TOLERANCE = 2.5  # points: words whose tops differ less are on one line
PHRASE_GAP_RATIO = 0.55  # a gap wider than this x font size starts a new phrase


@dataclass
class Phrase:
    text: str
    x0: float
    x1: float

    @property
    def center(self) -> float:
        return (self.x0 + self.x1) / 2


def _lines(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    lines: list[list[dict[str, Any]]] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= LINE_TOLERANCE:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _phrases(line: list[dict[str, Any]]) -> list[Phrase]:
    out: list[Phrase] = []
    for w in line:
        size = float(w.get("size") or (w["bottom"] - w["top"]) or 9)
        if out and w["x0"] - out[-1].x1 <= size * PHRASE_GAP_RATIO:
            out[-1] = Phrase(f"{out[-1].text} {w['text']}", out[-1].x0, w["x1"])
        else:
            out.append(Phrase(w["text"], w["x0"], w["x1"]))
    return out


def _header_score(phrases: list[Phrase]) -> int:
    return sum(
        1 for p in phrases if max(score_header(norm_header(p.text), f) for f in RENT_ROLL_FIELDS) >= MIN_CONFIDENCE
    )


def _boundaries(header: list[Phrase]) -> list[float]:
    """Column i spans [b[i], b[i+1]); boundaries sit midway between header phrases."""
    mids = [(a.x1 + b.x0) / 2 for a, b in pairwise(header)]
    return [float("-inf"), *mids, float("inf")]


def _column(p: Phrase, bounds: list[float]) -> int:
    for i in range(len(bounds) - 1):
        if bounds[i] <= p.center < bounds[i + 1]:
            return i
    return len(bounds) - 2


WRAP_GAP_RATIO = 0.85  # a line this much closer than the usual row pitch is a wrapped cell


def _is_wrapped(
    row: list[Any], rows: list[list[Any]], i: int, header_at: int | None, tops: list[float], pitch: float
) -> bool:
    """A continuation line: first column empty, sitting tighter under the previous data row than rows do."""
    if i == 0 or not rows or row[0] is not None or pitch <= 0:
        return False
    if header_at is not None and i <= header_at + 1:
        return False  # never merge into the header
    prev = rows[-1]
    if len(prev) < 2 or prev[0] is None:
        return False  # only merge into a real data row
    return tops[i] - tops[i - 1] < pitch * WRAP_GAP_RATIO


def read_pdf_rows(path: Path) -> tuple[list[list[Any]], list[str]]:
    """Return (rows, page label per row)."""
    try:
        import pdfplumber
    except ImportError as e:  # optional dependency
        from tieout.ingest import UnsupportedFormat

        raise UnsupportedFormat("PDF support needs an extra package: pip install 'tieout[pdf]'") from e

    rows: list[list[Any]] = []
    pages: list[str] = []
    bounds: list[float] | None = None
    any_text = False
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(extra_attrs=["size"], keep_blank_chars=False, use_text_flow=False)
            if not words:
                continue
            any_text = True
            raw_lines = _lines(words)
            lines = [_phrases(line) for line in raw_lines]
            tops = [float(line[0]["top"]) for line in raw_lines]
            gaps = sorted(b - a for a, b in pairwise(tops))
            row_pitch = gaps[len(gaps) // 2] if gaps else 0.0
            scores = [_header_score(p) for p in lines]
            best = max(range(len(lines)), key=lambda i: scores[i])
            header_at = best if scores[best] >= 3 else None
            if header_at is not None:
                bounds = _boundaries(lines[header_at])
            for i, phrases in enumerate(lines):
                if bounds is None or (header_at is not None and i < header_at):
                    # Before any header: titles and notes, kept as one cell.
                    rows.append([" ".join(p.text for p in phrases)])
                else:
                    row: list[Any] = [None] * (len(bounds) - 1)
                    for p in phrases:
                        c = _column(p, bounds)
                        row[c] = p.text if row[c] is None else f"{row[c]} {p.text}"
                    if _is_wrapped(row, rows, i, header_at, tops, row_pitch):
                        # Text that wrapped inside its cell: append it to the row above.
                        prev = rows[-1]
                        for c, text in enumerate(row):
                            if text is not None:
                                prev[c] = text if prev[c] is None else f"{prev[c]} {text}"
                        continue
                    rows.append(row)
                pages.append(f"page {page_no}")
    if not any_text:
        from tieout.ingest import UnsupportedFormat

        raise UnsupportedFormat(
            "This PDF has no text layer (it is probably scanned). Export the rent roll to Excel or a text PDF, "
            "or run it through OCR first."
        )
    return rows, pages
