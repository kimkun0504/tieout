"""Result types shared across the pipeline."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from tieout.ingest import SourceRef


class Severity(str, Enum):
    ERROR = "error"  # numbers are wrong or missing; do not use without review
    WARNING = "warning"  # suspicious; a person should look
    INFO = "info"  # worth knowing, usually fine


@dataclass
class TracedValue:
    """A cleaned value plus the raw text it came from and where.

    `derived` marks values computed by tieout (status inferred from a tenant
    name, rent rolled up from charge lines). `correction` is set when a reviewer
    overrode the value; `original` then holds what the pipeline produced.
    """

    value: Any
    raw: Any
    source: SourceRef | None
    derived: bool = False
    issue: str | None = None
    correction: Correction | None = None
    original: Any = None
    sources: list[SourceRef] = dc_field(default_factory=list)  # extra cells for rolled-up values

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "value": jsonable(self.value),
            "raw": jsonable(self.raw),
            "source": self.source.to_dict() if self.source else None,
            "derived": self.derived,
        }
        if self.sources:
            out["sources"] = [s.to_dict() for s in self.sources]
        if self.issue:
            out["issue"] = self.issue
        if self.correction:
            out["original"] = jsonable(self.original)
            out["correction"] = self.correction.to_dict()
        return out


@dataclass
class Charge:
    """One charge line of a unit (rent, parking, pet fee...)."""

    code: TracedValue
    amount: TracedValue
    category: str  # "rent" | "concession" | "other"

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.to_dict(), "amount": self.amount.to_dict(), "category": self.category}


@dataclass
class CleanRow:
    source_row: int  # 1-based row in the original sheet
    section: str | None
    values: dict[str, TracedValue] = dc_field(default_factory=dict)
    charges: list[Charge] = dc_field(default_factory=list)

    @property
    def current(self) -> bool:
        """False for a future/applicant lease row, which repeats a unit listed elsewhere."""
        return bool(self.get("status") != "future")

    def get(self, name: str) -> Any:
        tv = self.values.get(name)
        return tv.value if tv else None


@dataclass(frozen=True)
class Correction:
    """A reviewer's override of one field on one source row."""

    source_row: int
    field: str
    value: str | None  # as typed by the reviewer; parsed with the field's type
    reason: str
    author: str = ""
    at: str = ""  # ISO timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_row": self.source_row,
            "field": self.field,
            "value": self.value,
            "reason": self.reason,
            "author": self.author,
            "at": self.at,
        }


@dataclass(frozen=True)
class Acknowledgment:
    """A reviewer accepted an issue as-is, with a note."""

    issue_id: str
    note: str
    author: str = ""
    at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"issue_id": self.issue_id, "note": self.note, "author": self.author, "at": self.at}


@dataclass
class Issue:
    severity: Severity
    rule: str
    message: str
    row: int | None = None  # 1-based source row
    field: str | None = None
    refs: list[SourceRef] = dc_field(default_factory=list)
    acknowledgment: Acknowledgment | None = None

    @property
    def id(self) -> str:
        """Stable across re-runs: built from what the issue is about, not its wording."""
        key = f"{self.rule}|{self.row}|{self.field}|{','.join(r.cell for r in self.refs)}"
        return hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:12]

    @property
    def open(self) -> bool:
        return self.acknowledgment is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "acknowledgment": self.acknowledgment.to_dict() if self.acknowledgment else None,
            "severity": self.severity.value,
            "rule": self.rule,
            "message": self.message,
            "row": self.row,
            "field": self.field,
            "cells": [r.cell for r in self.refs],
        }


@dataclass
class ReportedTotal:
    """A total/subtotal row found in the source, kept so we can check it ties out."""

    row: int  # 1-based
    label: str
    section: str | None
    scope_rows: list[int]  # source rows this total should cover
    amounts: dict[str, TracedValue]  # field -> reported amount


@dataclass
class StatedFigure:
    """A statistic printed in the report's footer ("Occupied Units 95"), to check against the units."""

    stat: str  # total_units | occupied_units | vacant_units | occupancy
    label: str
    raw: Any
    ref: SourceRef


def jsonable(v: Any) -> Any:
    """JSON-safe value. Money stays an exact decimal string ("1425.10"), never a float."""
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, date):
        return v.isoformat()
    return v
