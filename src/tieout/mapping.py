"""Map source column headers to canonical fields.

Order of precedence:
1. A saved template for this exact header layout (deterministic, free).
2. Synonym and fuzzy matching against the schema.
3. An optional pluggable mapper (for example an LLM) for headers still unmapped.

Every mapping carries a confidence and the method that produced it, so the
review step can show low-confidence columns first.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Protocol, Sequence

from tieout.schema import FIELDS_BY_NAME, RENT_ROLL_FIELDS, FieldSpec

_NON_ALNUM = re.compile(r"[^a-z0-9#]+")


def norm_header(text: object) -> str:
    """'Mkt. Rent ($)' -> 'mkt rent'. Keeps '#' because 'Unit #' is common."""
    if text is None:
        return ""
    s = str(text).lower().replace("\n", " ")
    s = s.replace("sq. ft", "sqft").replace("sq.ft", "sqft").replace("square footage", "square feet")
    s = _NON_ALNUM.sub(" ", s)
    return " ".join(s.split())


def score_header(header: str, spec: FieldSpec) -> float:
    """How well a normalized header matches a field, from 0 to 1."""
    if not header:
        return 0.0
    best = 0.0
    tokens = set(header.split())
    for syn in spec.synonyms:
        syn_n = norm_header(syn)
        if header == syn_n:
            return 1.0
        syn_tokens = set(syn_n.split())
        # Every word of a multi-word synonym appears in the header: "lease start date" vs "lease start".
        if len(syn_tokens) > 1 and syn_tokens <= tokens:
            best = max(best, 0.85)
        ratio = SequenceMatcher(None, header, syn_n).ratio()
        if ratio >= 0.85:
            best = max(best, 0.9 * ratio)
    return best


@dataclass
class ColumnMapping:
    column: int  # 0-based column index in the grid
    header: str  # header text as found (possibly two header rows joined)
    field: str | None
    confidence: float
    method: str  # "template" | "synonym" | "mapper" | "unmapped"


class HeaderMapper(Protocol):
    """Pluggable fallback for headers the rules could not place (e.g. an LLM call).

    Receives unmapped headers with a few sample values each and returns
    {header: (field_name, confidence)} for the ones it can place.
    """

    def suggest(
        self, headers: dict[str, list[str]], free_fields: list[str]
    ) -> dict[str, tuple[str, float]]: ...


MIN_CONFIDENCE = 0.75


def map_columns(
    headers: dict[int, str],
    samples: dict[int, list[str]] | None = None,
    mapper: HeaderMapper | None = None,
) -> list[ColumnMapping]:
    """Assign each canonical field to at most one column, best scores first."""
    samples = samples or {}
    candidates: list[tuple[float, int, str]] = []
    for col, header in headers.items():
        h = norm_header(header)
        for spec in RENT_ROLL_FIELDS:
            s = score_header(h, spec)
            if s >= MIN_CONFIDENCE:
                candidates.append((s, col, spec.name))

    # Greedy assignment; on equal scores prefer the leftmost column.
    candidates.sort(key=lambda t: (-t[0], t[1]))
    taken: dict[int, tuple[str, float, str]] = {}  # col -> (field, score, method)
    taken_fields: set[str] = set()
    for s, col, field in candidates:
        if col in taken or field in taken_fields:
            continue
        taken[col] = (field, s, "synonym")
        taken_fields.add(field)

    if mapper is not None:
        unmapped = {headers[c]: samples.get(c, []) for c in headers if c not in taken and headers[c]}
        free = [f.name for f in RENT_ROLL_FIELDS if f.name not in taken_fields]
        if unmapped and free:
            for header, (field, conf) in mapper.suggest(unmapped, free).items():
                col = next((c for c, h in headers.items() if h == header and c not in taken), None)
                if col is None or field not in FIELDS_BY_NAME or field in taken_fields:
                    continue
                # Cap model guesses below rule matches so they always surface for review.
                taken[col] = (field, min(conf, 0.8), "mapper")
                taken_fields.add(field)

    result = []
    for col in sorted(headers):
        if col in taken:
            field, s, method = taken[col]
            result.append(ColumnMapping(col, headers[col], field, round(s, 3), method))
        else:
            result.append(ColumnMapping(col, headers[col], None, 0.0, "unmapped"))
    return result


def header_fingerprint(headers: Sequence[str]) -> str:
    """Stable ID for a header layout, used to look up saved templates."""
    key = "|".join(norm_header(h) for h in headers)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class TemplateStore:
    """Saved, human-confirmed mappings keyed by header fingerprint.

    Once a reviewer confirms how a source system's export maps to the schema,
    every later file with the same layout maps instantly with no guessing.
    """

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)

    def _path(self, fingerprint: str) -> Path:
        return self.dir / f"{fingerprint}.json"

    def load(self, headers: dict[int, str]) -> list[ColumnMapping] | None:
        p = self._path(header_fingerprint([headers[c] for c in sorted(headers)]))
        if not p.exists():
            return None
        data = json.loads(p.read_text())
        by_col = {m["column"]: m for m in data["mappings"]}
        return [
            ColumnMapping(c, headers[c], by_col.get(c, {}).get("field"), 1.0 if by_col.get(c, {}).get("field") else 0.0,
                          "template" if by_col.get(c, {}).get("field") else "unmapped")
            for c in sorted(headers)
        ]

    def save(self, headers: dict[int, str], mappings: list[ColumnMapping], name: str = "") -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        fp = header_fingerprint([headers[c] for c in sorted(headers)])
        payload = {
            "name": name,
            "fingerprint": fp,
            "headers": [headers[c] for c in sorted(headers)],
            "mappings": [asdict(m) for m in mappings],
        }
        p = self._path(fp)
        p.write_text(json.dumps(payload, indent=2))
        return p
