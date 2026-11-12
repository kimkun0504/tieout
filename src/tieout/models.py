"""Result types shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
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
    """A cleaned value plus the raw text it came from and where."""

    value: Any
    raw: Any
    source: SourceRef | None
    derived: bool = False  # True when inferred (e.g. status from tenant name) rather than read
    issue: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": jsonable(self.value),
            "raw": jsonable(self.raw),
            "source": self.source.to_dict() if self.source else None,
            "derived": self.derived,
            **({"issue": self.issue} if self.issue else {}),
        }


@dataclass
class CleanRow:
    source_row: int  # 1-based row in the original sheet
    section: str | None
    values: dict[str, TracedValue] = dc_field(default_factory=dict)

    def get(self, name: str) -> Any:
        tv = self.values.get(name)
        return tv.value if tv else None


@dataclass
class Issue:
    severity: Severity
    rule: str
    message: str
    row: int | None = None  # 1-based source row
    field: str | None = None
    refs: list[SourceRef] = dc_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
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


def jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, date):
        return v.isoformat()
    return v
