"""EOD Historical Data: buona copertura dei dividendi sui mercati asiatici.

Piano gratuito con un limite giornaliero di chiamate. Registra una chiave su
eodhd.com e mettila nella variabile d'ambiente EODHD_API_KEY.
"""

from __future__ import annotations

import os
from typing import Optional

import pandas as pd

from setxray.sources.base import parse_dividend_records
from setxray.sources.http import FetchError, get_json

URL = "https://eodhd.com/api/div/{symbol}"


def dividends(symbol: str) -> Optional[pd.Series]:
    chiave = os.environ.get("EODHD_API_KEY")
    if not chiave:
        raise FetchError("manca EODHD_API_KEY")
    from setxray.datasource import normalize_symbol

    _, yahoo_symbol = normalize_symbol(symbol)  # EODHD usa lo stesso suffisso .BK
    dati = get_json(URL.format(symbol=yahoo_symbol), {
        "api_token": chiave, "fmt": "json", "from": "2010-01-01",
    })
    if isinstance(dati, dict) and dati.get("error"):
        raise FetchError(str(dati["error"])[:120])
    return parse_dividend_records(dati)
