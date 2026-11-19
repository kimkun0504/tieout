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
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from tieout.schema import FIELDS_BY_NAME, RENT_ROLL_FIELDS, FieldSpec

_NON_ALNUM = re.compile(r"[^a-z0-9#]+")


def norm_header(text: object) -> str:
    """Cached wrapper; see _norm_header."""
    return _norm_header(text if isinstance(text, str) or text is None else str(text))


@lru_cache(maxsize=8192)
def _norm_header(text: str | None) -> str:
    """'Mkt. Rent ($)' -> 'mkt rent'. Keeps '#' because 'Unit #' is common."""
    if text is None:
        return ""
    s = str(text).lower().replace("\n", " ")
    s = s.replace("sq. ft", "sqft").replace("sq.ft", "sqft").replace("square footage", "square feet")
    s = _NON_ALNUM.sub(" ", s)
    return " ".join(s.split())


# Words that change what a column measures. "Monthly Rent/SF" contains the
# synonym "monthly rent" but is a per-square-foot rate; "Annual Rent" is 12x
# monthly rent. A header with one of these words only matches a synonym that
# contains the same word.
QUALIFIERS = frozenset(
    {
        "sf",
        "psf",
        "sqft",
        "annual",
        "annually",
        "annualized",
        "yr",
        "year",
        "yearly",
        "pct",
        "percent",
        "ytd",
        "per",
        "prior",
        "previous",
        "last",
        "budget",
        "budgeted",
        "variance",
        "change",
        "delta",
        "balance",
        "due",
        "avg",
        "average",
    }
)


@lru_cache(maxsize=8192)
def score_header(header: str, spec: FieldSpec) -> float:
    """How well a normalized header matches a field, from 0 to 1. Pure, so cached."""
    if not header:
        return 0.0
    best = 0.0
    tokens = set(header.split())
    for syn in spec.synonyms:
        syn_n = norm_header(syn)
        if header == syn_n:
            return 1.0
        syn_tokens = set(syn_n.split())
        if (tokens - syn_tokens) & QUALIFIERS:
            continue  # the header measures something else (per SF, annual, prior period...)
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

    def suggest(self, headers: dict[str, list[str]], free_fields: list[str]) -> dict[str, tuple[str, float]]: ...


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
                target = next((c for c, h in headers.items() if h == header and c not in taken), None)
                if target is None or field not in FIELDS_BY_NAME or field in taken_fields:
                    continue
                # Cap model guesses below rule matches so they always surface for review.
                taken[target] = (field, min(conf, 0.8), "mapper")
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
    """Stable ID for a header layout (ordered header texts), used to look up saved templates."""
    key = "|".join(norm_header(h) for h in headers)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _header_keys(headers: dict[int, str]) -> dict[int, str]:
    """Column -> 'normalized header#occurrence', so two columns both called 'Rent' stay distinct."""
    seen: dict[str, int] = {}
    keys = {}
    for c in sorted(headers):
        h = norm_header(headers[c])
        seen[h] = seen.get(h, 0) + 1
        keys[c] = f"{h}#{seen[h]}"
    return keys


class TemplateStore:
    """Saved, human-confirmed mappings keyed by header fingerprint.

    Mappings are stored by header name (and occurrence), never by column
    position: the same export with an extra blank column must still map
    "Tenant" to tenant, not whatever now sits in the old position.
    """

    VERSION = 2

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)

    def _path(self, fingerprint: str) -> Path:
        return self.dir / f"{fingerprint}.json"

    def load(self, headers: dict[int, str]) -> list[ColumnMapping] | None:
        p = self._path(header_fingerprint([headers[c] for c in sorted(headers)]))
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("version") != self.VERSION:
            return None  # old position-based template: ignore rather than risk a wrong mapping
        by_key: dict[str, str | None] = data["fields_by_header"]
        keys = _header_keys(headers)
        out = []
        for c in sorted(headers):
            field = by_key.get(keys[c])
            out.append(ColumnMapping(c, headers[c], field, 1.0 if field else 0.0, "template" if field else "unmapped"))
        return out

    def save(self, headers: dict[int, str], mappings: list[ColumnMapping], name: str = "") -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        fp = header_fingerprint([headers[c] for c in sorted(headers)])
        keys = _header_keys(headers)
        by_col = {m.column: m.field for m in mappings}
        payload = {
            "version": self.VERSION,
            "name": name,
            "fingerprint": fp,
            "headers": [headers[c] for c in sorted(headers)],
            "fields_by_header": {keys[c]: by_col.get(c) for c in sorted(headers)},
        }
        p = self._path(fp)
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return p
