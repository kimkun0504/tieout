"""Canonical rent roll schema.

Every source format is mapped onto these fields. Synonyms are matched after
normalizing header text (lowercase, punctuation stripped), so "Mkt. Rent" and
"MARKET RENT" both match "market rent".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FieldType(str, Enum):
    TEXT = "text"
    MONEY = "money"
    NUMBER = "number"
    DATE = "date"
    STATUS = "status"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: FieldType
    synonyms: tuple[str, ...]
    required: bool = False
    description: str = ""


RENT_ROLL_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "unit",
        FieldType.TEXT,
        ("unit", "unit no", "unit number", "unit #", "apt", "apartment", "suite", "space", "unit id"),
        required=True,
        description="Unit or suite identifier",
    ),
    FieldSpec(
        "unit_type",
        FieldType.TEXT,
        ("unit type", "type", "floorplan", "floor plan", "bd ba", "bed bath", "plan"),
        description="Floor plan or bed/bath type",
    ),
    FieldSpec(
        "sqft",
        FieldType.NUMBER,
        ("sqft", "sq ft", "square feet", "sf", "rentable sf", "rsf", "area", "unit sqft", "size"),
        description="Rentable square feet",
    ),
    FieldSpec(
        "tenant",
        FieldType.TEXT,
        ("tenant", "tenant name", "resident", "resident name", "lessee", "occupant", "name"),
        description="Tenant or resident name",
    ),
    FieldSpec(
        "status",
        FieldType.STATUS,
        ("status", "unit status", "occupancy", "occupancy status", "occ status"),
        description="occupied / vacant / notice / model / down",
    ),
    FieldSpec(
        "market_rent",
        FieldType.MONEY,
        ("market rent", "market", "mkt rent", "asking rent", "scheduled rent", "gross potential rent", "gpr"),
        description="Market or asking monthly rent",
    ),
    FieldSpec(
        "current_rent",
        FieldType.MONEY,
        (
            "current rent",
            "rent",
            "actual rent",
            "lease rent",
            "contract rent",
            "monthly rent",
            "charge amount",
            "base rent",
            "in place rent",
            "effective rent",
        ),
        required=True,
        description="Rent actually charged per month",
    ),
    FieldSpec(
        "deposit",
        FieldType.MONEY,
        ("deposit", "security deposit", "sec dep", "deposit held", "dep"),
        description="Security deposit held",
    ),
    FieldSpec(
        "move_in",
        FieldType.DATE,
        ("move in", "move in date", "movein", "mi date", "moved in"),
        description="Move-in date",
    ),
    FieldSpec(
        "lease_start",
        FieldType.DATE,
        ("lease start", "lease from", "start date", "lease begin", "from", "commencement", "lease start date"),
        description="Lease start date",
    ),
    FieldSpec(
        "lease_end",
        FieldType.DATE,
        ("lease end", "lease to", "end date", "lease expiration", "expiration", "to", "lease exp", "lease end date"),
        description="Lease end date",
    ),
)

FIELDS_BY_NAME: dict[str, FieldSpec] = {f.name: f for f in RENT_ROLL_FIELDS}

STATUS_VALUES = ("occupied", "vacant", "notice", "model", "down")
