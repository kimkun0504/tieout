"""Cross-check a rent roll against a T-12 for the same property.

Underwriters compare the two because each can hide what the other shows: a
rent roll is a snapshot of leases, a T-12 is what was actually billed and
collected. Large gaps usually mean the rent roll is stale or incomplete,
units are missing, or the T-12 includes other properties or one-off items.

Compared against the T-12's most recent month:
- gross potential rent: rent roll market rent (all units) vs T-12 GPR;
- rent in place: rent roll rent of occupied units vs T-12 net rental income
  (GPR plus loss to lease, vacancy and concessions, which are negative);
- economic occupancy: in-place / market on both sides;
- timing: how far apart the two documents' dates are.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from tieout.pipeline import CleanResult
from tieout.t12 import Statement

OK_PCT = Decimal("0.02")  # within 2%: consistent
WARN_PCT = Decimal("0.05")  # beyond 5%: needs explaining
NET_RENT_CATEGORIES = ("gross_potential_rent", "loss_to_lease", "vacancy", "concessions", "rental_income")


@dataclass
class Comparison:
    metric: str
    label: str
    rent_roll: str | None
    t12: str | None
    difference: str | None
    pct: float | None
    status: str  # "consistent" | "check" | "investigate" | "unavailable"
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _grade(pct: Decimal) -> str:
    if abs(pct) <= OK_PCT:
        return "consistent"
    return "check" if abs(pct) <= WARN_PCT else "investigate"


def _money(a: Decimal | None) -> str | None:
    return None if a is None else str(a.quantize(Decimal("0.01")))


def _compare(metric: str, label: str, rr: Decimal | None, t12: Decimal | None, why: str) -> Comparison:
    if rr is None or t12 is None or t12 == 0:
        return Comparison(
            metric,
            label,
            _money(rr),
            _money(t12),
            None,
            None,
            "unavailable",
            "One of the documents does not provide this figure.",
        )
    diff = rr - t12
    pct = diff / abs(t12)
    return Comparison(metric, label, _money(rr), _money(t12), _money(diff), round(float(pct), 4), _grade(pct), why)


def compare(rent_roll: CleanResult, statement: Statement) -> dict[str, Any]:
    last = len(statement.months) - 1
    month = statement.months[last] if statement.months else None

    def t12_month(categories: tuple[str, ...]) -> Decimal | None:
        lines = [ln for ln in statement.items("income") if ln.category in categories]
        if not lines:
            return None
        return sum((ln.amounts[last].value or Decimal(0) for ln in lines), Decimal(0))

    m = rent_roll.metrics()
    rr_gpr = Decimal(m["gross_potential_rent"]) if m.get("gross_potential_rent") else None
    rr_rent = Decimal(m["in_place_rent"]) if m.get("in_place_rent") else None
    t12_gpr = t12_month(("gross_potential_rent",))
    t12_net = t12_month(NET_RENT_CATEGORIES)

    checks = [
        _compare(
            "gross_potential_rent",
            "Gross potential rent",
            rr_gpr,
            t12_gpr,
            "Market rent of every unit on the rent roll against the T-12's gross potential rent for its last "
            "month. A gap often means units are missing from one document or market rents were updated.",
        ),
        _compare(
            "rent_in_place",
            "Rent in place",
            rr_rent,
            t12_net,
            "Rent of occupied units on the rent roll against the T-12's rental income after loss to lease, "
            "vacancy and concessions. A rent roll well above the T-12 can mean leases signed but not yet "
            "billing, or concessions missing from the rent roll.",
        ),
    ]
    rr_econ = Decimal(str(m["economic_occupancy"])) if m.get("economic_occupancy") is not None else None
    t12_econ = (t12_net / t12_gpr) if (t12_net is not None and t12_gpr) else None
    if rr_econ is not None and t12_econ is not None:
        points = (rr_econ - t12_econ) * 100
        status = "consistent" if abs(points) <= 2 else "check" if abs(points) <= 5 else "investigate"
        checks.append(
            Comparison(
                "economic_occupancy",
                "Economic occupancy",
                f"{rr_econ:.4f}",
                f"{t12_econ:.4f}",
                f"{points:.1f} pts",
                None,
                status,
                "In-place rent as a share of market rent, on each document.",
            )
        )
    else:
        checks.append(
            Comparison(
                "economic_occupancy",
                "Economic occupancy",
                None,
                None,
                None,
                None,
                "unavailable",
                "Needs market rent on the rent roll and gross potential rent on the T-12.",
            )
        )

    timing = None
    if rent_roll.as_of and month:
        months_apart = (rent_roll.as_of.year - month.year) * 12 + rent_roll.as_of.month - month.month
        timing = {
            "rent_roll_as_of": rent_roll.as_of.isoformat(),
            "t12_last_month": month.isoformat()[:7],
            "months_apart": months_apart,
            "status": "consistent" if 0 <= months_apart <= 1 else "check" if abs(months_apart) <= 3 else "investigate",
        }
    return {
        "rent_roll": {"file": rent_roll.source_file, "as_of": rent_roll.as_of.isoformat() if rent_roll.as_of else None},
        "t12": {"file": statement.file, "last_month": month.isoformat()[:7] if month else None},
        "checks": [c.to_dict() for c in checks],
        "timing": timing,
        "thresholds": {"consistent_within": float(OK_PCT), "investigate_beyond": float(WARN_PCT)},
    }
