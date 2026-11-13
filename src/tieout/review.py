"""Reviewer decisions layered over a source file.

The source file is never modified. Everything a reviewer decides (column
mapping overrides, value corrections, accepted issues) lives in a Review that
is re-applied on every run, so the cleaned output is always reproducible from
source + review, and every change is attributable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tieout.models import Acknowledgment, Correction
from tieout.normalize import parse
from tieout.schema import FIELDS_BY_NAME


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class AuditEvent:
    at: str
    author: str
    action: str
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"at": self.at, "author": self.author, "action": self.action, "detail": self.detail}


@dataclass
class Review:
    # header text -> field name, or None to drop a column the rules mapped
    mapping_overrides: dict[str, str | None] = field(default_factory=dict)
    corrections: list[Correction] = field(default_factory=list)
    acknowledgments: list[Acknowledgment] = field(default_factory=list)
    audit: list[AuditEvent] = field(default_factory=list)

    # --- mutations (each one is audited) -------------------------------------

    def override_mapping(self, header: str, field_name: str | None, author: str = "") -> None:
        if field_name is not None and field_name not in FIELDS_BY_NAME:
            raise ValueError(f"Unknown field {field_name!r}")
        self.mapping_overrides[header] = field_name
        self._log(author, "override_mapping", {"header": header, "field": field_name})

    def clear_mapping_override(self, header: str, author: str = "") -> None:
        if self.mapping_overrides.pop(header, "__missing__") != "__missing__":
            self._log(author, "clear_mapping_override", {"header": header})

    def correct(self, source_row: int, field_name: str, value: str | None, reason: str, author: str = "") -> Correction:
        """Record a correction. The value must parse cleanly with the field's type."""
        spec = FIELDS_BY_NAME.get(field_name)
        if spec is None or not spec.output:
            raise ValueError(f"Field {field_name!r} cannot be corrected")
        if not reason.strip():
            raise ValueError("A reason is required for every correction")
        if value is not None and value.strip():
            _, issue = parse(value, spec.type)
            if issue:
                raise ValueError(f"Invalid value for {field_name}: {issue}")
        else:
            value = None
        c = Correction(source_row, field_name, value, reason.strip(), author, now_iso())
        self.corrections = [x for x in self.corrections if not (x.source_row == source_row and x.field == field_name)]
        self.corrections.append(c)
        self._log(author, "correct", c.to_dict())
        return c

    def remove_correction(self, source_row: int, field_name: str, author: str = "") -> bool:
        before = len(self.corrections)
        self.corrections = [x for x in self.corrections if not (x.source_row == source_row and x.field == field_name)]
        removed = len(self.corrections) < before
        if removed:
            self._log(author, "remove_correction", {"source_row": source_row, "field": field_name})
        return removed

    def acknowledge(self, issue_id: str, note: str, author: str = "") -> Acknowledgment:
        if not note.strip():
            raise ValueError("A note is required to accept an issue")
        a = Acknowledgment(issue_id, note.strip(), author, now_iso())
        self.acknowledgments = [x for x in self.acknowledgments if x.issue_id != issue_id] + [a]
        self._log(author, "acknowledge", a.to_dict())
        return a

    def unacknowledge(self, issue_id: str, author: str = "") -> None:
        self.acknowledgments = [x for x in self.acknowledgments if x.issue_id != issue_id]
        self._log(author, "unacknowledge", {"issue_id": issue_id})

    def _log(self, author: str, action: str, detail: dict[str, Any]) -> None:
        self.audit.append(AuditEvent(now_iso(), author, action, detail))

    # --- lookups ----------------------------------------------------------------

    def corrections_for(self, source_row: int) -> list[Correction]:
        return [c for c in self.corrections if c.source_row == source_row]

    def ack_for(self, issue_id: str) -> Acknowledgment | None:
        return next((a for a in self.acknowledgments if a.issue_id == issue_id), None)

    # --- persistence ------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "mapping_overrides": self.mapping_overrides,
            "corrections": [c.to_dict() for c in self.corrections],
            "acknowledgments": [a.to_dict() for a in self.acknowledgments],
            "audit": [e.to_dict() for e in self.audit],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Review:
        return cls(
            mapping_overrides=dict(d.get("mapping_overrides", {})),
            corrections=[Correction(**c) for c in d.get("corrections", [])],
            acknowledgments=[Acknowledgment(**a) for a in d.get("acknowledgments", [])],
            audit=[AuditEvent(**e) for e in d.get("audit", [])],
        )

    def save(self, path: str | Path) -> None:
        path = Path(path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)  # atomic on POSIX: a crash never leaves a half-written review

    @classmethod
    def load(cls, path: str | Path) -> Review:
        path = Path(path)
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else cls()
