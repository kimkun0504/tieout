"""Standard rent roll analytics, computed from cleaned rows.

Definitions (multifamily underwriting conventions):
- Physical occupancy: occupied units (incl. on notice) / all units.
- Economic occupancy: in-place rent of occupied units / market rent of all units.
- Loss to lease: market minus in-place rent across occupied units.
- Vacancy loss: market rent of vacant units.
Money is returned as exact decimal strings; ratios as 4-decimal floats.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from tieout.models import CleanRow

OCCUPIED = ("occupied", "notice")
ZERO = Decimal(0)


def _m(d: Decimal | None) -> str | None:
    return None if d is None else str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _ratio(n: Decimal | int, d: Decimal | int) -> float | None:
    return round(float(Decimal(n) / Decimal(d)), 4) if d else None


def _avg(values: list[Decimal]) -> Decimal | None:
    return sum(values, ZERO) / len(values) if values else None


def compute_metrics(rows: list[CleanRow], as_of: date | None = None) -> dict[str, Any]:
    occupied = [r for r in rows if r.get("status") in OCCUPIED]
    vacant = [r for r in rows if r.get("status") == "vacant"]
    market_all = [r.get("market_rent") for r in rows if r.get("market_rent") is not None]
    rent_occ = [r.get("current_rent") for r in occupied if r.get("current_rent") is not None]
    sqft_occ = sum((r.get("sqft") or 0 for r in occupied if r.get("current_rent") is not None), 0)

    has_market = len(market_all) == len(rows) and rows
    loss_to_lease = None
    if has_market:
        loss_to_lease = sum(
            (r.get("market_rent") - r.get("current_rent") for r in occupied if r.get("current_rent") is not None),
            ZERO,
        )
    concessions = sum((r.get("concessions") or ZERO for r in rows), ZERO)

    out: dict[str, Any] = {
        "units": len(rows),
        "occupied_units": len(occupied),
        "vacant_units": len(vacant),
        "physical_occupancy": _ratio(len(occupied), len(rows)),
        "economic_occupancy": _ratio(sum(rent_occ, ZERO), sum(market_all, ZERO)) if has_market else None,
        "gross_potential_rent": _m(sum(market_all, ZERO)) if has_market else None,
        "in_place_rent": _m(sum(rent_occ, ZERO)),
        "loss_to_lease": _m(loss_to_lease),
        "loss_to_lease_pct": _ratio(loss_to_lease, sum((r.get("market_rent") for r in occupied), ZERO))
        if loss_to_lease is not None
        else None,
        "vacancy_loss": _m(sum((r.get("market_rent") or ZERO for r in vacant), ZERO)) if has_market else None,
        "concessions": _m(concessions) if concessions else None,
        "avg_in_place_rent": _m(_avg(rent_occ)),
        "avg_market_rent": _m(_avg(market_all)),
        "avg_rent_per_sqft": _m(sum(rent_occ, ZERO) / Decimal(sqft_occ)) if sqft_occ else None,
        "unit_mix": _unit_mix(rows),
    }
    if as_of is not None:
        out["lease_expirations"] = _expirations(occupied, as_of)
    return out


def _unit_mix(rows: list[CleanRow]) -> list[dict[str, Any]]:
    groups: dict[str, list[CleanRow]] = defaultdict(list)
    for r in rows:
        groups[r.get("unit_type") or "(none)"].append(r)
    mix = []
    for unit_type, rs in sorted(groups.items()):
        occ = [r for r in rs if r.get("status") in OCCUPIED]
        sq = [Decimal(str(r.get("sqft"))) for r in rs if r.get("sqft")]
        avg_sq = _avg(sq)
        mix.append(
            {
                "unit_type": unit_type,
                "units": len(rs),
                "occupied": len(occ),
                "occupancy": _ratio(len(occ), len(rs)),
                "avg_sqft": round(float(avg_sq), 1) if avg_sq is not None else None,
                "avg_market_rent": _m(_avg([r.get("market_rent") for r in rs if r.get("market_rent") is not None])),
                "avg_in_place_rent": _m(
                    _avg([r.get("current_rent") for r in occ if r.get("current_rent") is not None])
                ),
            }
        )
    return mix


def _expirations(occupied: list[CleanRow], as_of: date) -> dict[str, Any]:
    """Occupied leases expiring in each of the next 12 months, plus expired / month-to-month."""
    months: dict[str, dict[str, Any]] = {}
    y, m = as_of.year, as_of.month
    for _ in range(12):
        months[f"{y:04d}-{m:02d}"] = {"units": 0, "rent": ZERO}
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    expired = no_date = later = 0
    for r in occupied:
        end = r.get("lease_end")
        if end is None:
            no_date += 1
        elif end < as_of:
            expired += 1
        else:
            key = f"{end.year:04d}-{end.month:02d}"
            if key in months:
                months[key]["units"] += 1
                months[key]["rent"] += r.get("current_rent") or ZERO
            else:
                later += 1
    return {
        "as_of": as_of.isoformat(),
        "by_month": [{"month": k, "units": v["units"], "rent": _m(v["rent"])} for k, v in months.items()],
        "expired_or_mtm": expired,
        "no_end_date": no_date,
        "after_12_months": later,
    }
