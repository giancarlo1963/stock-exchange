"""Formattazione dei numeri, condivisa da testo, grafici e CLI.

Un posto solo per ogni numero che l'utente legge, cosi' tutta l'app concorda
su separatori, decimali e su come si scrive un valore che manca.

Le due lingue non scrivono i numeri allo stesso modo: in inglese la virgola
separa le migliaia e il punto i decimali (1,234.50), in italiano il contrario
(1.234,50). Cambiano anche le abbreviazioni delle scale (bn / mld) e il modo
di scrivere una data. Quindi la lingua non tocca solo le parole: tocca ogni
cifra, e per questo passa da qui.
"""

from __future__ import annotations

from typing import Optional

from setxray.lang import L, language

# Scambia i due separatori in un colpo solo: senza tabella servirebbe un
# segnaposto intermedio per non sovrascrivere la prima sostituzione.
_ITALIANO = str.maketrans({",": ".", ".": ","})

# Le scale: (soglia, sigla inglese, sigla italiana, decimali). In inglese la
# sigla sta attaccata al numero (98.3bn), in italiano staccata (98,3 mld).
_SCALE = ((1e9, "bn", "mld", 1), (1e6, "m", "mln", 1), (1e3, "k", "mila", 1))


def na() -> str:
    """Come si scrive un valore che manca. Mai lasciato vuoto, mai stimato."""
    return L("n/a", "n/d")


def num(value: Optional[float], decimals: int = 2) -> str:
    """1234.5 -> '1,234.50' in inglese, '1.234,50' in italiano."""
    if value is None:
        return na()
    try:
        testo = f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return na()
    return testo.translate(_ITALIANO) if language() == "it" else testo


def pct(value: Optional[float], decimals: int = 1, sign: bool = False) -> str:
    """0.0825 -> '8.3%' (con sign=True e valore positivo -> '+8.3%')"""
    if value is None:
        return na()
    formatted = num(value * 100, decimals)
    if sign and value > 0:
        formatted = "+" + formatted
    return formatted + "%"


def mult(value: Optional[float], decimals: int = 1) -> str:
    """12.34 -> '12.3x'"""
    return na() if value is None else num(value, decimals) + "x"


def money(value: Optional[float], currency: str = "THB", decimals: int = 2) -> str:
    return na() if value is None else f"{num(value, decimals)} {currency}"


def big(value: Optional[float], currency: str = "THB") -> str:
    """Importi grandi in scala leggibile: 98_300_000_000 -> '98.3bn THB'."""
    if value is None:
        return na()
    absolute = abs(value)
    # Sopra il miliardo restiamo su "bn": una capitalizzazione thailandese da
    # 1,500bn THB si legge meglio cosi' che con un'altra unita'.
    for threshold, inglese, italiano, digits in _SCALE:
        if absolute >= threshold:
            scala = num(value / threshold, digits)
            return L(f"{scala}{inglese} {currency}", f"{scala} {italiano} {currency}")
    return f"{num(value, 0)} {currency}"


def ratio(value: Optional[float], decimals: int = 2) -> str:
    return na() if value is None else num(value, decimals)


def date(value) -> str:
    """In inglese il mese scritto (11 Sep 2026), in italiano in cifre.

    Il mese scritto evita l'ambiguita' fra 09/11 e 11/09, che in inglese
    cambia significato fra Stati Uniti ed Europa. In italiano quel dubbio non
    c'e' - il giorno viene sempre prima - e le cifre sono piu' compatte.
    """
    if value is None:
        return na()
    try:
        return value.strftime(L("%d %b %Y", "%d/%m/%Y"))
    except AttributeError:
        return str(value)
