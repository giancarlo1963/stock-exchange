"""Number formatting, shared by text, charts and the CLI.

One place for every number the user reads, so the whole app agrees on
separators, decimals and how a missing value is written.
"""

from __future__ import annotations

from typing import Optional

NA = "n/a"


def num(value: Optional[float], decimals: int = 2) -> str:
    """1234.5 -> '1,234.50'"""
    if value is None:
        return NA
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return NA


def pct(value: Optional[float], decimals: int = 1, sign: bool = False) -> str:
    """0.0825 -> '8.3%' (with sign=True and a positive value -> '+8.3%')"""
    if value is None:
        return NA
    formatted = num(value * 100, decimals)
    if sign and value > 0:
        formatted = "+" + formatted
    return formatted + "%"


def mult(value: Optional[float], decimals: int = 1) -> str:
    """12.34 -> '12.3x'"""
    return NA if value is None else num(value, decimals) + "x"


def money(value: Optional[float], currency: str = "THB", decimals: int = 2) -> str:
    return NA if value is None else f"{num(value, decimals)} {currency}"


def big(value: Optional[float], currency: str = "THB") -> str:
    """Large amounts on a readable scale: 98_300_000_000 -> '98.3bn THB'."""
    if value is None:
        return NA
    absolute = abs(value)
    # Above a billion we stay on "bn": a Thai market cap of 1,500bn THB reads
    # better that way than in another unit.
    for threshold, label, digits in ((1e9, "bn", 1), (1e6, "m", 1), (1e3, "k", 1)):
        if absolute >= threshold:
            return f"{num(value / threshold, digits)}{label} {currency}"
    return f"{num(value, 0)} {currency}"


def ratio(value: Optional[float], decimals: int = 2) -> str:
    return NA if value is None else num(value, decimals)


def date(value) -> str:
    """Day-month-year with the month spelled out: no US/European ambiguity."""
    if value is None:
        return NA
    try:
        return value.strftime("%d %b %Y")
    except AttributeError:
        return str(value)
