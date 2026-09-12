"""Alpha Vantage: chiave gratuita, limite di 25 chiamate al giorno.

Registrala su alphavantage.co e mettila in ALPHAVANTAGE_API_KEY. I titoli
thailandesi usano il suffisso `.BKK` invece di `.BK`.
"""

from __future__ import annotations

import os
from typing import Optional

import pandas as pd

from setxray.sources.base import clean_series, parse_dividend_records
from setxray.sources.http import FetchError, get_json

URL = "https://www.alphavantage.co/query"


def dividends(symbol: str) -> Optional[pd.Series]:
    chiave = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not chiave:
        raise FetchError("ALPHAVANTAGE_API_KEY is missing")
    from setxray.datasource import normalize_symbol

    set_symbol, _ = normalize_symbol(symbol)
    av_symbol = f"{set_symbol}.BKK"

    # Prima l'endpoint dedicato, poi le serie mensili rettificate, che
    # contengono anch'esse l'importo del dividendo mese per mese.
    dati = _chiama({"function": "DIVIDENDS", "symbol": av_symbol, "apikey": chiave})
    serie = parse_dividend_records(dati)
    if serie is not None and not serie.empty:
        return serie

    dati = _chiama({"function": "TIME_SERIES_MONTHLY_ADJUSTED", "symbol": av_symbol,
                    "apikey": chiave})
    mensili = dati.get("Monthly Adjusted Time Series") if isinstance(dati, dict) else None
    if not isinstance(mensili, dict):
        raise FetchError("no dividend in the response")
    importi = {}
    for data, valori in mensili.items():
        grezzo = valori.get("7. dividend amount") if isinstance(valori, dict) else None
        try:
            importo = float(grezzo)
        except (TypeError, ValueError):
            continue
        if importo > 0:
            importi[data] = importo
    return clean_series(pd.Series(importi)) if importi else None


def _chiama(parametri: dict) -> dict:
    dati = get_json(URL, parametri)
    if not isinstance(dati, dict):
        return {}
    for campo in ("Error Message", "Information", "Note"):
        if campo in dati:
            raise FetchError(str(dati[campo])[:140])
    return dati
