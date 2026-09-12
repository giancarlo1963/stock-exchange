"""Financial Modeling Prep: storico dividendi, piano gratuito limitato.

Chiave gratuita su financialmodelingprep.com, poi FMP_API_KEY.
"""

from __future__ import annotations

import os
from typing import Optional

import pandas as pd

from setxray.sources.base import parse_dividend_records
from setxray.sources.http import FetchError, get_json

URL = "https://financialmodelingprep.com/api/v3/historical-price-full/stock_dividend/{symbol}"


def dividends(symbol: str) -> Optional[pd.Series]:
    chiave = os.environ.get("FMP_API_KEY")
    if not chiave:
        raise FetchError("FMP_API_KEY is missing")
    from setxray.datasource import normalize_symbol

    _, yahoo_symbol = normalize_symbol(symbol)
    dati = get_json(URL.format(symbol=yahoo_symbol), {"apikey": chiave})
    if isinstance(dati, dict) and ("Error Message" in dati or "error" in dati):
        raise FetchError(str(dati.get("Error Message") or dati.get("error"))[:120])
    # La risposta attesa e' {"symbol": ..., "historical": [...]}, ma leggiamo
    # comunque in profondita' per sopravvivere a un cambio di forma.
    return parse_dividend_records(dati)
