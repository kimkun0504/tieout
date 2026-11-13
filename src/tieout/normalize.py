"""Turn raw cell values into typed values. Each parser returns (value, issue).

Parsers are strict on purpose: a value that does not clearly match the expected
shape is returned as None with an issue, never guessed. A wrong number that
looks right is worse than a blank that gets reviewed.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from dateutil import parser as date_parser

from tieout.schema import FieldType

# Excel stores dates as days since 1899-12-30 (it treats 1900 as a leap year).
_EXCEL_EPOCH = date(1899, 12, 30)
_SERIAL_MIN, _SERIAL_MAX = 20000, 80000  # 1954-10-03 .. 2119-01-10
CENT = Decimal("0.01")
# No rent roll amount is anywhere near this; larger values are corrupt cells.
MAX_AMOUNT = Decimal("1000000000000")

_VACANT_PREFIXES = ("vacant", "vacancy", "available", "unrented", "unoccupied")
_EMPTY_TOKENS = {"-", "--", "—", "–", "n/a", "na", "none", "nil"}

# Optional sign, optional currency, digits with optional US thousands separators,
# optional decimals, optional trailing sign or CR. Parentheses handled separately.
_MONEY_RE = re.compile(
    r"""^(?P<sign>[-+])?\s*
        (?:US)?\$?\s*
        (?P<sign2>-)?\s*
        (?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)
        \s*(?P<trail>-|CR)?
        (?:\s*(?:USD|/\s*mo(?:nth)?))?$""",
    re.I | re.X,
)
# European style "1.300,00" or "1 300,00": detect so we flag instead of misreading.
_EU_MONEY_RE = re.compile(r"^[€$]?\s*\d{1,3}(?:[.\s]\d{3})+,\d{2}\s*€?$|^[€$]?\s*\d+,\d{2}\s*€?$")

_NUMBER_RE = re.compile(r"^-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")

# Dates: require all three parts so "12" or "Jan" is never silently completed.
_DATE_HAS_YEAR = re.compile(r"(?<!\d)(\d{4}|\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2})(?!\d)")
_MONTH_NAMES = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", re.I)

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


def to_cents(d: Decimal) -> Decimal:
    """Round half away from zero, the way Excel and accounting systems do."""
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_money(value: Any) -> Parsed:
    if isinstance(value, bool):
        return None, f"expected an amount, got {value!r}"
    if isinstance(value, (int, float, Decimal)):
        d = Decimal(str(value))
        if not d.is_finite():
            return None, "amount is not a finite number"
        return _checked_amount(d, value)
    s = " ".join(str(value).split())
    if s.lower() in _EMPTY_TOKENS:
        return None, None

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    m = _MONEY_RE.match(s)
    if not m:
        if _EU_MONEY_RE.match(s):
            return None, f"amount {value!r} looks like a European number format; not converted"
        return None, f"could not read amount {value!r}"
    if m.group("sign") == "-" or m.group("sign2") or m.group("trail"):
        negative = True  # "(100)", "-100", "100-" and "100 CR" all mean a credit
    try:
        raw_amount = Decimal(m.group("num").replace(",", ""))
    except InvalidOperation:
        return None, f"could not read amount {value!r}"
    return _checked_amount(-raw_amount if negative else raw_amount, value)


def _checked_amount(d: Decimal, original: Any) -> Parsed:
    if abs(d) >= MAX_AMOUNT:
        return None, f"amount {original!r} is implausibly large"
    return to_cents(d), None


def parse_number(value: Any) -> Parsed:
    if isinstance(value, bool):
        return None, f"expected a number, got {value!r}"
    if isinstance(value, (int, float, Decimal)):
        n = float(value)
        if not math.isfinite(n):
            return None, "number is not finite"
        return (int(n) if n.is_integer() else n), None
    s = re.sub(r"\s*(?:sq\.?\s*ft\.?|sf|rsf)\s*$", "", str(value).strip(), flags=re.I).strip()
    if s.lower() in _EMPTY_TOKENS:
        return None, None
    if not _NUMBER_RE.match(s):
        return None, f"could not read number {str(value)!r}"
    n = float(s.replace(",", ""))
    if not math.isfinite(n) or abs(n) >= float(MAX_AMOUNT):
        return None, f"number {str(value)!r} is implausibly large"
    return (int(n) if n.is_integer() else n), None


def parse_date(value: Any) -> Parsed:
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _from_serial(value)
    s = str(value).strip()
    low = s.lower()
    if low in _EMPTY_TOKENS:
        return None, None
    if low in {"mtm", "month to month", "month-to-month"}:
        return None, "month-to-month lease (no end date)"
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return _from_serial(float(s))
    fast = _fast_date(s)
    if fast is not None:
        return fast
    has_year = bool(_DATE_HAS_YEAR.search(s))
    has_month_day = bool(re.search(r"(?<!\d)\d{1,2}[/\-.]\d{1,2}(?!\d)", s)) or (
        bool(_MONTH_NAMES.search(s)) and bool(re.search(r"(?<!\d)\d{1,2}(?!\d)", s))
    )
    if not (has_year and has_month_day):
        return None, f"incomplete date {s!r} (needs month, day and year)"
    try:
        # US exports: 03/04/2025 means March 4.
        return date_parser.parse(s, dayfirst=False).date(), None
    except (ValueError, OverflowError):
        return None, f"could not read date {s!r}"


_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$")


def _fast_date(s: str) -> Parsed | None:
    """MM/DD/YYYY and YYYY-MM-DD cover most exports; parse them without dateutil."""
    m = _US_DATE.match(s)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            # Fixed POSIX pivot (00-68 -> 2000s, 69-99 -> 1900s) so a file reads the
            # same whatever day it is processed; dateutil's rolling window would not.
            year += 2000 if year <= 68 else 1900
    else:
        m = _ISO_DATE.match(s)
        if not m:
            return None
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(year, month, day), None
    except ValueError:
        return None, f"not a real date {s!r}"


def _from_serial(n: float) -> Parsed:
    if _SERIAL_MIN < n < _SERIAL_MAX:
        return _EXCEL_EPOCH + timedelta(days=int(n)), None
    return None, f"number {n!r} is not a plausible date"


def parse_status(value: Any) -> Parsed:
    original = str(value).strip().lower()
    if not original or original in _EMPTY_TOKENS:
        return None, None
    s = " ".join(original.replace("-", " ").replace("_", " ").split())
    if not s:
        return None, f"unknown status {value!r}"
    words = set(s.split())
    # Notice must be checked before occupied: "Occupied NTV" is a notice unit.
    if ("ntv" in words or "notice" in words) and "no notice" not in s:
        return "notice", None
    if s.startswith(_VACANT_PREFIXES):
        return "vacant", None
    if s.startswith(("occ", "current", "leased", "rented", "in place")):
        return "occupied", None
    if s.startswith("model"):
        return "model", None
    if s.startswith(("down", "offline", "admin", "renovat", "non revenue", "employee")):
        return "down", None
    return None, f"unknown status {value!r}"


def parse_text(value: Any) -> Parsed:
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # unit "101.0" from Excel should read "101"
    if isinstance(value, (datetime, date)):
        return None, f"expected text, got a date {value!r} (Excel may have auto-converted it)"
    s = " ".join(str(value).split())
    return s, None


_SUFFIXES = {"LLC", "LP", "LLP", "INC", "II", "III", "IV", "DBA", "PC", "PLLC", "CO", "LTD", "USA", "NA"}


def tidy_name(name: str) -> str:
    """Fix ALL-CAPS names: 'O'BRIEN, SEAN' -> "O'Brien, Sean", 'SMITH-JONES' -> 'Smith-Jones'.

    Mixed-case input is returned unchanged; it was typed by a person and is
    more trustworthy than any rule. Legal suffixes (LLC, INC) stay upper case.
    """
    if not (name.isupper() and any(ch.isalpha() for ch in name)):
        return name
    out = []
    for word in name.split(" "):
        core = word.strip(".,")
        if core in _SUFFIXES:
            out.append(word)
            continue
        out.append(re.sub(r"[A-Z]+", lambda m: m.group(0).capitalize(), word))
    return " ".join(out)


def is_vacant_marker(text: str | None) -> bool:
    """'VACANT', 'Vacant - Ready', '*VACANT - UNRENTED*' in a tenant column mean no tenant."""
    if not text:
        return False
    s = text.strip().strip("*-_ ").lower()
    return s.startswith(_VACANT_PREFIXES)
