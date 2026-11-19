"""Optional LLM fallback for column headers the rules could not place.

Privacy by design: the model sees header names and the *shape* of a few
sample values ("money-like", "date-like", "short text"), never the values
themselves, so tenant names and amounts never leave the machine.

Fail closed: any API error, timeout or malformed answer means "no
suggestion", never a guess. Suggestions are capped below rule confidence by
mapping.map_columns, so they always surface for a reviewer to confirm, and a
confirmed mapping can be saved as a template so the model is asked only once
per export format.

Enable with an Anthropic API key:
    export ANTHROPIC_API_KEY=...
    tieout clean file.xlsx --llm            # or TIEOUT_LLM=1 for `tieout serve`
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Protocol

from tieout.normalize import parse_date, parse_money
from tieout.schema import FIELDS_BY_NAME

DEFAULT_MODEL = "claude-haiku-5-5"  # classification task: fastest, lowest cost
log = logging.getLogger("tieout.llm")


class MessagesClient(Protocol):
    """The slice of anthropic.Anthropic().messages this module uses (injectable for tests)."""

    def create(self, **kwargs: Any) -> Any: ...


def describe_samples(samples: list[str]) -> str:
    """Summarise sample values by shape only: no raw text leaves the machine."""
    if not samples:
        return "empty"
    kinds = []
    for s in samples:
        if parse_money(s)[1] is None:
            kinds.append("money-like")
        elif parse_date(s)[1] is None:
            kinds.append("date-like")
        elif re.fullmatch(r"[A-Za-z]?\d+[A-Za-z]?", s.strip()):
            kinds.append("short code")
        elif len(s) <= 12:
            kinds.append("short text")
        else:
            kinds.append("long text")
    return ", ".join(sorted(set(kinds)))


PROMPT = """You map spreadsheet column headers from a real estate rent roll to a fixed schema.

Unmapped columns (header, and the shape of its sample values):
{columns}

Fields you may assign (each to at most one column):
{fields}

Rules:
- Only map a column when you are confident it holds exactly that field. Monthly vs annual,
  per square foot vs total, and current vs prior period all matter: if unsure, leave it out.
- Answer with JSON only, no prose: {{"mappings": [{{"header": "...", "field": "...", "confidence": 0.0-1.0}}]}}
- Use headers exactly as given. Return an empty list if nothing fits."""


class AnthropicHeaderMapper:
    def __init__(self, client: MessagesClient | None = None, model: str | None = None, timeout: float = 20.0):
        if client is None:
            import anthropic  # optional dependency: pip install 'tieout[llm]'

            self.client: Any = anthropic.Anthropic(timeout=timeout, max_retries=1).messages
        else:
            self.client = client
        self.model = model or os.environ.get("TIEOUT_LLM_MODEL", DEFAULT_MODEL)

    def suggest(self, headers: dict[str, list[str]], free_fields: list[str]) -> dict[str, tuple[str, float]]:
        columns = "\n".join(f"- {json.dumps(h)}: {describe_samples(s)}" for h, s in headers.items())
        fields = "\n".join(f"- {f}: {FIELDS_BY_NAME[f].description}" for f in free_fields if f in FIELDS_BY_NAME)
        try:
            response = self.client.create(
                model=self.model,
                max_tokens=600,
                temperature=0,
                messages=[{"role": "user", "content": PROMPT.format(columns=columns, fields=fields)}],
            )
            text = "".join(getattr(block, "text", "") for block in response.content)
            return parse_suggestions(text, set(headers), set(free_fields))
        except Exception as e:  # fail closed: a mapping suggestion is never worth a crash
            log.warning("LLM header mapping failed: %s", type(e).__name__)
            return {}


def parse_suggestions(text: str, headers: set[str], free_fields: set[str]) -> dict[str, tuple[str, float]]:
    """Accept only well-formed suggestions for known headers and free fields, one header per field."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    out: dict[str, tuple[str, float]] = {}
    used: set[str] = set()
    for item in data.get("mappings", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        header, field, conf = item.get("header"), item.get("field"), item.get("confidence")
        if header not in headers or field not in free_fields or field in used or header in out:
            continue
        if not isinstance(conf, (int, float)) or not 0 <= conf <= 1 or conf < 0.5:
            continue
        out[header] = (field, float(conf))
        used.add(field)
    return out


def mapper_from_env() -> AnthropicHeaderMapper | None:
    """The configured mapper, or None when LLM mapping is not enabled."""
    if os.environ.get("TIEOUT_LLM", "").lower() not in ("1", "true", "yes") or not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        return AnthropicHeaderMapper()
    except ImportError:
        log.warning("TIEOUT_LLM is set but the anthropic package is missing: pip install 'tieout[llm]'")
        return None
