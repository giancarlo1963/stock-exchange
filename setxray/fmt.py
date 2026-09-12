"""Formattazione dei numeri in italiano, condivisa da testo, grafici e CLI.

In italiano la virgola separa i decimali e il punto le migliaia: Python fa il
contrario, quindi ogni numero mostrato all'utente passa da qui.
"""

from __future__ import annotations

from typing import Optional

NA = "n/d"
# Scambia i due separatori in un colpo solo: senza tabella servirebbe un
# segnaposto intermedio per non sovrascrivere la prima sostituzione.
_ITALIAN = str.maketrans({",": ".", ".": ","})


def num(value: Optional[float], decimals: int = 2) -> str:
    """1234.5 -> '1.234,50'"""
    if value is None:
        return NA
    try:
        return f"{float(value):,.{decimals}f}".translate(_ITALIAN)
    except (TypeError, ValueError):
        return NA


def pct(value: Optional[float], decimals: int = 1, sign: bool = False) -> str:
    """0.0825 -> '8,3%' (con sign=True e valore positivo -> '+8,3%')"""
    if value is None:
        return NA
    formatted = num(value * 100, decimals)
    if sign and value > 0:
        formatted = "+" + formatted
    return formatted + "%"


def mult(value: Optional[float], decimals: int = 1) -> str:
    """12.34 -> '12,3x'"""
    return NA if value is None else num(value, decimals) + "x"


def money(value: Optional[float], currency: str = "THB", decimals: int = 2) -> str:
    return NA if value is None else f"{num(value, decimals)} {currency}"


def big(value: Optional[float], currency: str = "THB") -> str:
    """Importi grandi in scala leggibile: 98_300_000_000 -> '98,3 mld THB'."""
    if value is None:
        return NA
    absolute = abs(value)
    # Sopra il miliardo restiamo su "mld": una capitalizzazione thailandese da
    # 1.500 mld THB si legge meglio cosi' che con un'altra unita'.
    for threshold, label, digits in (
        (1e9, "mld", 1),
        (1e6, "mln", 1),
        (1e3, "mila", 1),
    ):
        if absolute >= threshold:
            return f"{num(value / threshold, digits)} {label} {currency}"
    return f"{num(value, 0)} {currency}"


def ratio(value: Optional[float], decimals: int = 2) -> str:
    return NA if value is None else num(value, decimals)


def date(value) -> str:
    if value is None:
        return NA
    try:
        return value.strftime("%d/%m/%Y")
    except AttributeError:
        return str(value)
