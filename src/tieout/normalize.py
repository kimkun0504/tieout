"""Turn raw cell values into typed values. Each parser returns (value, issue)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from dateutil import parser as date_parser

from tieout.schema import FieldType

# Excel stores dates as days since 1899-12-30 (it treats 1900 as a leap year).
_EXCEL_EPOCH = date(1899, 12, 30)
_VACANT_WORDS = {"vacant", "vacancy", "vacant unit", "available", "unrented"}

Parsed = tuple[Any, "str | None"]


def parse(value: Any, ftype: FieldType) -> Parsed:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, None
    if ftype is FieldType.MONEY:
        return parse_money(value)
    if ftype is FieldType.NUMBER:
        return parse_number(value)
    if ftype is FieldType.DATE:
        return parse_date(value)
    if ftype is FieldType.STATUS:
        return parse_status(value)
    return parse_text(value)


def parse_money(value: Any) -> Parsed:
    if isinstance(value, bool):
        return None, f"expected an amount, got {value!r}"
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)).quantize(Decimal("0.01")), None
    s = str(value).strip()
    if s in {"-", "--", "—", "n/a", "N/A", "na"}:
        return None, None
    negative = s.startswith("(") and s.endswith(")") or s.startswith("-") or s.endswith("-")
    digits = re.sub(r"[^\d.]", "", s)
    if not digits or digits.count(".") > 1:
        return None, f"could not read amount {s!r}"
    try:
        amount = Decimal(digits).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None, f"could not read amount {s!r}"
    return (-amount if negative else amount), None


def parse_number(value: Any) -> Parsed:
    if isinstance(value, bool):
        return None, f"expected a number, got {value!r}"
    if isinstance(value, (int, float, Decimal)):
        n = float(value)
        return (int(n) if n.is_integer() else n), None
    s = re.sub(r"[,\s]|sq\.?\s*ft\.?|sf$", "", str(value).strip(), flags=re.I)
    try:
        n = float(s)
    except ValueError:
        return None, f"could not read number {str(value)!r}"
    return (int(n) if n.is_integer() else n), None


def parse_date(value: Any) -> Parsed:
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # A bare number in a date column is almost always an Excel serial date.
        if 20000 < value < 80000:
            return _EXCEL_EPOCH + timedelta(days=int(value)), None
        return None, f"number {value!r} is not a plausible date"
    s = str(value).strip()
    if s.lower() in {"mtm", "month to month", "month-to-month"}:
        return None, "month-to-month lease (no end date)"
    try:
        # US exports: 03/04/2025 means March 4.
        return date_parser.parse(s, dayfirst=False, default=datetime(2000, 1, 1)).date(), None
    except (ValueError, OverflowError):
        return None, f"could not read date {s!r}"


def parse_status(value: Any) -> Parsed:
    s = str(value).strip().lower()
    if not s:
        return None, None
    if s in _VACANT_WORDS or s.startswith("vacant"):
        return "vacant", None
    if s.startswith(("occ", "current", "leased", "rented")):
        return "occupied", None
    if "notice" in s or s.startswith("ntv"):
        return "notice", None
    if s.startswith("model"):
        return "model", None
    if s.startswith(("down", "offline", "admin", "renovat")):
        return "down", None
    return None, f"unknown status {value!r}"


def parse_text(value: Any) -> Parsed:
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # unit "101.0" from Excel should read "101"
    s = " ".join(str(value).split())
    return s, None


def tidy_name(name: str) -> str:
    """'SMITH, JOHN' -> 'Smith, John'. Leaves mixed-case names alone."""
    if name.isupper() and any(ch.isalpha() for ch in name):
        return " ".join(w.capitalize() if not _is_suffix(w) else w for w in name.split())
    return name


def _is_suffix(word: str) -> bool:
    return word.strip(".,") in {"LLC", "LP", "LLP", "INC", "II", "III", "IV", "DBA"}


def is_vacant_marker(text: str | None) -> bool:
    return bool(text) and text.strip().lower() in _VACANT_WORDS | {"*vacant*", "-vacant-"}
