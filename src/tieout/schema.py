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
    output: bool = True  # False for input-only fields (charge lines are rolled up per unit)
    additive: bool = True  # False for rates: a total row's rent per SF is an average, not a sum


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
            "monthly base rent",
            "base rent monthly",
            "base rent",
            "in place rent",
            "effective rent",
        ),
        required=True,
        description="Rent actually charged per month",
    ),
    FieldSpec(
        "annual_rent",
        FieldType.MONEY,
        (
            "annual rent",
            "annual base rent",
            "annualized rent",
            "annual rent amount",
            "yearly rent",
            "base rent annual",
            "abr",
            "current annual rent",
        ),
        description="Rent per year (common in commercial rent rolls)",
    ),
    FieldSpec(
        "rent_psf",
        FieldType.MONEY,
        (
            "rent psf",
            "rent per sf",
            "rent sf",
            "psf",
            "rent per sq ft",
            "rent per square foot",
            "annual rent psf",
            "annual rent sf",
            "annual rent per sf",
            "annual psf",
            "base rent psf",
            "base rent sf",
            "base rent sf yr",
            "rent sf yr",
            "rent psf yr",
            "annual base rent psf",
            "annual base rent sf",
            "abr psf",
            "abr sf",
            "rate psf",
            "rate sf",
        ),
        description="Annual rent per square foot (commercial rent rolls)",
        additive=False,
    ),
    FieldSpec(
        "rent_psf_monthly",
        FieldType.MONEY,
        (
            "rent psf mo",
            "rent sf mo",
            "rent sf month",
            "rent psf month",
            "monthly rent psf",
            "monthly rent sf",
            "monthly psf",
            "base rent sf mo",
            "base rent psf mo",
            "psf mo",
            "rent per sf per month",
        ),
        description="Monthly rent per square foot (converted to annual rent_psf)",
        output=False,
        additive=False,
    ),
    FieldSpec(
        "concessions",
        FieldType.MONEY,
        ("concessions", "concession", "monthly concession", "discount", "rent concession"),
        description="Monthly concessions or discounts (usually negative)",
    ),
    FieldSpec(
        "other_charges",
        FieldType.MONEY,
        ("other charges", "other", "other income", "fees", "additional charges", "misc charges"),
        description="Recurring non-rent charges (parking, pet, storage, utilities)",
    ),
    FieldSpec(
        "total_charges",
        FieldType.MONEY,
        ("total charges", "total monthly charges", "total billed", "gross charges"),
        description="All recurring monthly charges for the unit",
    ),
    FieldSpec(
        "charge_code",
        FieldType.TEXT,
        ("charge code", "charge", "code", "charge type", "charge desc", "charge description", "lease charges"),
        description="Charge line code (one unit may have several lines)",
        output=False,
    ),
    FieldSpec(
        "charge_amount",
        FieldType.MONEY,
        ("charge amount", "amount", "charges", "monthly amount", "charge amt"),
        description="Amount of one charge line",
        output=False,
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
OUTPUT_FIELDS: tuple[str, ...] = tuple(f.name for f in RENT_ROLL_FIELDS if f.output)

# Charge codes vary by system ("RENT", "RNT", "BASERENT", "CONC", "PARK", "PET").
# Classify them into rent, concession or other so per-line charges roll up into
# current_rent, concessions and other_charges.
RENT_CODE_RE = (
    r"^(rent|rnt|rentr|rentres|base\s*rent|baserent|res\s*rent|apt\s*rent|mrent|market\s*rent|resident\s*rent)\b|^rent"
)
CONCESSION_CODE_RE = r"conc|concession|disc(ount)?\b|special|promo|free\s*rent|credit"

STATUS_VALUES = ("occupied", "vacant", "notice", "model", "down")
