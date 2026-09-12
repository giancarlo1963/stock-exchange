"""Yahoo Finance via `yfinance`: sempre disponibile, ma da verificare.

E' la riserva. Non serve nessuna chiave e copre dieci e piu' anni, ma sui
titoli della SET capita che salti uno stacco o che registri la data con
qualche giorno di scarto. Va bene come base, non come unica fonte.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


def dividends(symbol: str) -> Optional[pd.Series]:
    import yfinance as yf

    from setxray.datasource import normalize_symbol

    _, yahoo_symbol = normalize_symbol(symbol)
    serie = yf.Ticker(yahoo_symbol).dividends
    if serie is None or len(serie) == 0:
        return None
    return pd.Series(serie)
