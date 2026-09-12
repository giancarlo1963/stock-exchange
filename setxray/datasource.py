"""Scarico dei dati grezzi per un titolo quotato alla SET (Bangkok).

Fonte primaria: Yahoo Finance via `yfinance`. I titoli SET hanno il suffisso
`.BK` (PTT -> PTT.BK) e l'indice di mercato e' `^SET.BK`.

Tutto quello che sta qui dentro e' "best effort": Yahoo non ha la stessa
copertura su ogni titolo thailandese, quindi ogni campo puo' mancare. Il
resto dell'app deve poter lavorare con dati parziali, percio' questo modulo
non solleva eccezioni per un dato assente: lo lascia a None e annota un
avviso in `StockData.warnings`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import pickle
import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import pandas as pd

# yfinance racconta ogni tentativo fallito sullo standard error: con la rete
# instabile l'utente si ritrova venti righe di diagnostica al posto del
# messaggio dell'app. Le silenziamo, salvo che si stia indagando un problema
# (SETXRAY_DEBUG=1).
if not os.environ.get("SETXRAY_DEBUG"):
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)

SET_SUFFIX = ".BK"
SET_INDEX_SYMBOL = "^SET.BK"
DEFAULT_CACHE_TTL_MIN = 60
_CACHE_DIR = os.environ.get(
    "SETXRAY_CACHE_DIR", os.path.join(os.path.expanduser("~"), ".cache", "setxray")
)

# Elenco indicativo di titoli molto liquidi della SET, usato solo per i
# suggerimenti rapidi nell'interfaccia. Non e' una lista di raccomandazioni.
POPULAR_SET_SYMBOLS: tuple[tuple[str, str], ...] = (
    ("PTT", "PTT (energy)"),
    ("AOT", "Airports of Thailand"),
    ("CPALL", "CP All (retail)"),
    ("ADVANC", "Advanced Info Service"),
    ("SCB", "SCB X (bank)"),
    ("KBANK", "Kasikornbank"),
    ("BBL", "Bangkok Bank"),
    ("PTTEP", "PTT Exploration & Production"),
    ("GULF", "Gulf Development"),
    ("BDMS", "Bangkok Dusit Medical"),
    ("CPN", "Central Pattana"),
    ("MINT", "Minor International"),
    ("SCC", "Siam Cement"),
    ("TRUE", "True Corporation"),
    ("BH", "Bumrungrad Hospital"),
    ("OR", "PTT Oil & Retail"),
)


# --------------------------------------------------------------------------
# simboli
# --------------------------------------------------------------------------
def normalize_symbol(raw: str) -> tuple[str, str]:
    """Da un input libero ricava (simbolo SET, simbolo Yahoo).

    >>> normalize_symbol(" ptt ")
    ('PTT', 'PTT.BK')
    >>> normalize_symbol("AOT.BK")
    ('AOT', 'AOT.BK')
    """
    if raw is None:
        raise ValueError("Symbol is missing")
    s = str(raw).strip().upper().replace(" ", "")
    if not s:
        raise ValueError("Symbol is missing")
    # Yahoo non quota le classi locali/estere separate (-R, -F, -U): usiamo il
    # titolo principale, che e' quello che interessa a chi investe a 1-2 anni.
    for suffix in ("-R", "-F", "-U", "-W"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    if s.endswith(SET_SUFFIX):
        base = s[: -len(SET_SUFFIX)]
    elif s.endswith(".BKK"):
        base = s[: -len(".BKK")]
    else:
        base = s
    base = base.strip(".")
    if not base:
        raise ValueError(f"Invalid symbol: {raw!r}")
    return base, base + SET_SUFFIX


# --------------------------------------------------------------------------
# helper sui DataFrame dei bilanci
# --------------------------------------------------------------------------
def row(df: Optional[pd.DataFrame], *keys: str) -> Optional[pd.Series]:
    """Estrae una riga di bilancio provando piu' grafie della stessa voce.

    yfinance usa l'indice in camelCase (`TotalRevenue`) ma versioni diverse o
    `pretty=True` producono `Total Revenue` / `TOTAL REVENUE`: proviamo tutte
    le varianti prima di arrendersi.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    index = df.index
    # indice a piu' livelli (level_detail): teniamo solo il nome della voce
    if isinstance(index, pd.MultiIndex):
        df = df.copy()
        df.index = index.get_level_values(0)
        index = df.index
    lookup = {}
    for label in index:
        key = str(label).replace(" ", "").replace("_", "").lower()
        lookup.setdefault(key, label)
    for k in keys:
        want = str(k).replace(" ", "").replace("_", "").lower()
        if want in lookup:
            series = df.loc[lookup[want]]
            if isinstance(series, pd.DataFrame):  # etichetta duplicata
                series = series.iloc[0]
            return pd.to_numeric(series, errors="coerce").dropna()
    return None


def first_value(df: Optional[pd.DataFrame], *keys: str) -> Optional[float]:
    """Valore piu' recente di una voce di bilancio (le colonne sono ordinate desc)."""
    series = row(df, *keys)
    if series is None or series.empty:
        return None
    return float(series.iloc[0])


def sum_last(df: Optional[pd.DataFrame], n: int, *keys: str) -> Optional[float]:
    """Somma degli ultimi `n` periodi di una voce (per ricostruire un TTM)."""
    series = row(df, *keys)
    if series is None or len(series) < n:
        return None
    return float(series.iloc[:n].sum())


# --------------------------------------------------------------------------
# contenitore
# --------------------------------------------------------------------------
@dataclass
class StockData:
    """Tutti i dati grezzi scaricati per un titolo, senza elaborazioni."""

    symbol: str
    yahoo_symbol: str
    info: dict = field(default_factory=dict)
    prices: Optional[pd.DataFrame] = None  # storico giornaliero, 10+ anni
    benchmark: Optional[pd.DataFrame] = None  # indice SET
    income_a: Optional[pd.DataFrame] = None
    income_q: Optional[pd.DataFrame] = None
    income_ttm: Optional[pd.DataFrame] = None
    balance_a: Optional[pd.DataFrame] = None
    balance_q: Optional[pd.DataFrame] = None
    cash_a: Optional[pd.DataFrame] = None
    cash_q: Optional[pd.DataFrame] = None
    cash_ttm: Optional[pd.DataFrame] = None
    dividends: Optional[pd.Series] = None
    analyst_targets: dict = field(default_factory=dict)
    growth_estimates: Optional[pd.DataFrame] = None
    earnings_estimate: Optional[pd.DataFrame] = None
    revenue_estimate: Optional[pd.DataFrame] = None
    recommendations: Optional[pd.DataFrame] = None
    valuation_yearly: Optional[pd.DataFrame] = None
    valuation_quarterly: Optional[pd.DataFrame] = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    from_cache: bool = False
    is_demo: bool = False
    warnings: list[str] = field(default_factory=list)

    # ---- comodita' -------------------------------------------------------
    @property
    def name(self) -> str:
        for key in ("longName", "shortName", "displayName"):
            value = self.info.get(key)
            if value:
                return str(value)
        return self.symbol

    @property
    def sector(self) -> Optional[str]:
        return self.info.get("sector") or None

    @property
    def industry(self) -> Optional[str]:
        return self.info.get("industry") or None

    @property
    def currency(self) -> str:
        return str(self.info.get("currency") or "THB")

    @property
    def is_financial(self) -> bool:
        """Banche e assicurazioni vanno valutate su P/B e ROE, non su EV/EBITDA."""
        text = " ".join(
            str(self.info.get(k) or "") for k in ("sector", "industry", "longBusinessSummary")
        ).lower()
        if any(w in text for w in ("bank", "insurance", "capital markets", "credit service")):
            return True
        return str(self.info.get("sector") or "").lower().startswith("financial")

    def has_statements(self) -> bool:
        return any(
            isinstance(df, pd.DataFrame) and not df.empty
            for df in (self.income_a, self.balance_a, self.cash_a)
        )

    def data_coverage(self) -> dict[str, bool]:
        """Cosa e' stato effettivamente trovato: mostrato nell'interfaccia."""
        def ok(obj) -> bool:
            if obj is None:
                return False
            if isinstance(obj, (pd.DataFrame, pd.Series)):
                return not obj.empty
            if isinstance(obj, dict):
                return bool(obj)
            return bool(obj)

        return {
            "Price history": ok(self.prices),
            "SET index": ok(self.benchmark),
            "Income statement": ok(self.income_a),
            "Balance sheet": ok(self.balance_a),
            "Cash flow statement": ok(self.cash_a),
            "Quarterly figures": ok(self.income_q),
            "Dividends": ok(self.dividends),
            "Analyst estimates": ok(self.analyst_targets) or ok(self.earnings_estimate),
            "Historical multiples": ok(self.valuation_yearly) or ok(self.valuation_quarterly),
        }


# --------------------------------------------------------------------------
# cache su disco (vale anche per la CLI, non solo per Streamlit)
# --------------------------------------------------------------------------
def _cache_path(yahoo_symbol: str) -> str:
    digest = hashlib.sha256(yahoo_symbol.encode()).hexdigest()[:16]
    return os.path.join(_CACHE_DIR, f"{digest}.pkl")


def _cache_read(yahoo_symbol: str, ttl_min: float) -> Optional[StockData]:
    if ttl_min <= 0:
        return None
    path = _cache_path(yahoo_symbol)
    try:
        if not os.path.exists(path) or time.time() - os.path.getmtime(path) > ttl_min * 60:
            return None
        with open(path, "rb") as fh:
            data = pickle.load(fh)
    except Exception:
        return None
    if isinstance(data, StockData):
        data.from_cache = True
        return data
    return None


def _cache_write(data: StockData) -> None:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        tmp = _cache_path(data.yahoo_symbol) + ".tmp"
        with open(tmp, "wb") as fh:
            pickle.dump(data, fh)
        os.replace(tmp, _cache_path(data.yahoo_symbol))
    except Exception:
        pass  # una cache che non scrive non deve far fallire l'analisi


def clear_cache() -> int:
    """Svuota la cache su disco. Ritorna il numero di file rimossi."""
    removed = 0
    try:
        for name in os.listdir(_CACHE_DIR):
            if name.endswith(".pkl"):
                os.remove(os.path.join(_CACHE_DIR, name))
                removed += 1
    except FileNotFoundError:
        pass
    return removed


# --------------------------------------------------------------------------
# scarico
# --------------------------------------------------------------------------
def _try(data: StockData, label: str, fn, *args, **kwargs):
    """Esegue una chiamata a Yahoo e registra il problema senza interrompere."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = fn(*args, **kwargs)
    except Exception as exc:  # rete, rate limit, campo assente su questo titolo
        data.warnings.append(f"{label}: unavailable ({type(exc).__name__})")
        return None
    if isinstance(result, (pd.DataFrame, pd.Series)) and result.empty:
        data.warnings.append(f"{label}: Yahoo returns no data for this stock")
        return None
    return result


def _normalize_prices(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Uniforma lo storico prezzi: `Close` grezzo + `AdjClose` total return."""
    if df is None or df.empty:
        return None
    out = df.copy()
    out.columns = [str(c) for c in out.columns]
    rename = {}
    for col in out.columns:
        flat = col.replace(" ", "").lower()
        if flat == "adjclose":
            rename[col] = "AdjClose"
        elif flat == "stocksplits":
            rename[col] = "Splits"
    out = out.rename(columns=rename)
    if "Close" not in out.columns:
        return None
    if "AdjClose" not in out.columns:
        out["AdjClose"] = out["Close"]
    out = out[~out.index.duplicated(keep="last")].sort_index()
    try:  # i fusi orari rendono difficili i confronti fra titolo e indice
        out.index = pd.to_datetime(out.index).tz_localize(None)
    except (TypeError, AttributeError):
        out.index = pd.to_datetime(out.index)
    return out.dropna(subset=["Close"])


def fetch_stock(
    symbol: str,
    *,
    cache_ttl_min: float = DEFAULT_CACHE_TTL_MIN,
    history_period: str = "10y",
    include_benchmark: bool = True,
) -> StockData:
    """Scarica tutto il possibile su un titolo SET.

    Non solleva eccezioni per dati parziali: se anche i prezzi mancano,
    ritorna un `StockData` con gli avvisi, e sara' il chiamante a decidere.
    """
    set_symbol, yahoo_symbol = normalize_symbol(symbol)

    cached = _cache_read(yahoo_symbol, cache_ttl_min)
    if cached is not None:
        return cached

    import yfinance as yf  # import ritardato: rende veloce l'avvio della CLI

    data = StockData(symbol=set_symbol, yahoo_symbol=yahoo_symbol)
    ticker = yf.Ticker(yahoo_symbol)

    info = _try(data, "Company summary", lambda: ticker.info) or {}
    data.info = info if isinstance(info, dict) else {}

    # auto_adjust=False: serve il prezzo grezzo per i multipli storici
    # (P/E, P/B) e l'AdjClose per il rendimento totale.
    data.prices = _normalize_prices(
        _try(
            data,
            "Price history",
            ticker.history,
            period=history_period,
            interval="1d",
            auto_adjust=False,
            actions=True,
        )
    )

    if include_benchmark:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                bench = yf.Ticker(SET_INDEX_SYMBOL).history(
                    period=history_period, interval="1d", auto_adjust=True
                )
            data.benchmark = _normalize_prices(bench)
        except Exception:
            data.warnings.append("SET index: comparison with the market is unavailable")

    data.income_a = _try(data, "Annual income statement", ticker.get_income_stmt, freq="yearly")
    data.income_q = _try(data, "Quarterly income statement", ticker.get_income_stmt, freq="quarterly")
    data.income_ttm = _try(data, "Trailing income statement", ticker.get_income_stmt, freq="trailing")
    data.balance_a = _try(data, "Annual balance sheet", ticker.get_balance_sheet, freq="yearly")
    data.balance_q = _try(data, "Quarterly balance sheet", ticker.get_balance_sheet, freq="quarterly")
    data.cash_a = _try(data, "Annual cash flow statement", ticker.get_cash_flow, freq="yearly")
    data.cash_q = _try(data, "Quarterly cash flow statement", ticker.get_cash_flow, freq="quarterly")
    data.cash_ttm = _try(data, "Trailing cash flow statement", ticker.get_cash_flow, freq="trailing")

    dividends = _try(data, "Dividends", lambda: ticker.dividends)
    if dividends is not None and len(dividends) > 0:
        series = pd.Series(dividends).dropna()
        try:
            series.index = pd.to_datetime(series.index).tz_localize(None)
        except (TypeError, AttributeError):
            series.index = pd.to_datetime(series.index)
        data.dividends = series.sort_index()

    targets = _try(data, "Analyst price targets", lambda: ticker.analyst_price_targets)
    data.analyst_targets = targets if isinstance(targets, dict) else {}
    data.growth_estimates = _try(data, "Growth estimates", lambda: ticker.growth_estimates)
    data.earnings_estimate = _try(data, "Earnings per share estimates", lambda: ticker.earnings_estimate)
    data.revenue_estimate = _try(data, "Revenue estimates", lambda: ticker.revenue_estimate)
    data.recommendations = _try(data, "Analyst ratings", lambda: ticker.recommendations)

    # Storico dei multipli (P/E, P/B, EV/EBITDA) cosi' come li calcola Yahoo:
    # serve a dire se il titolo e' caro o economico *rispetto a se stesso*.
    data.valuation_yearly = _try(
        data, "Annual historical multiples", ticker.get_valuation_measures, freq="yearly", periods=12
    )
    data.valuation_quarterly = _try(
        data, "Quarterly historical multiples", ticker.get_valuation_measures, freq="quarterly", periods=24
    )

    if data.prices is not None:
        _cache_write(data)
    return data


def latest_close(data: StockData) -> Optional[float]:
    """Ultimo prezzo utilizzabile: prima lo storico, poi la scheda Yahoo."""
    if data.prices is not None and not data.prices.empty:
        return float(data.prices["Close"].iloc[-1])
    for key in ("currentPrice", "regularMarketPrice", "previousClose"):
        value = data.info.get(key)
        if value:
            return float(value)
    return None


def coerce_float(*candidates: Any) -> Optional[float]:
    """Primo valore numerico finito e non nullo fra quelli proposti."""
    for value in candidates:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number != number or number in (float("inf"), float("-inf")):  # NaN/inf
            continue
        return number
    return None


def mean_or_none(values: Iterable[Any]) -> Optional[float]:
    clean = [v for v in (coerce_float(x) for x in values) if v is not None]
    return sum(clean) / len(clean) if clean else None
