"""Dai bilanci grezzi alle metriche che un analista guarda davvero.

Questo modulo non giudica: calcola. Produce un oggetto `Metrics` con lo
storico per esercizio, i valori TTM, la crescita, la qualita' del business, la
solidita' finanziaria, i multipli (anche rispetto alla propria storia) e il
comportamento del prezzo. Le valutazioni stanno in `valuation.py`, i giudizi
in `scoring.py`.

Convenzione: ogni grandezza puo' essere `None`. Meglio un dato mancante
dichiarato che un numero inventato.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from setxray.datasource import StockData, coerce_float, first_value, latest_close, row, sum_last

TRADING_DAYS = 252
THAI_CORPORATE_TAX = 0.20  # aliquota societaria standard in Thailandia


# --------------------------------------------------------------------------
# piccoli aiuti numerici
# --------------------------------------------------------------------------
def safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Divisione che non esplode: None se uno dei due manca o il divisore e' ~0."""
    a, b = coerce_float(a), coerce_float(b)
    if a is None or b is None or abs(b) < 1e-12:
        return None
    result = a / b
    return result if math.isfinite(result) else None


def cagr(first: Optional[float], last: Optional[float], years: float) -> Optional[float]:
    """Tasso di crescita annuo composto. None se il punto di partenza non e' positivo.

    Con una base negativa (una perdita) il CAGR non ha significato economico:
    e' meglio non mostrarlo che mostrarne uno finto.
    """
    first, last = coerce_float(first), coerce_float(last)
    if first is None or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1.0 / years) - 1.0


def pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Variazione percentuale da `b` ad `a`, con base positiva."""
    a, b = coerce_float(a), coerce_float(b)
    if a is None or b is None or abs(b) < 1e-12:
        return None
    return a / abs(b) - 1.0


def percentile_of(series: Optional[pd.Series], value: Optional[float]) -> Optional[float]:
    """In che percentile della propria storia si trova `value` (0 = minimo)."""
    value = coerce_float(value)
    if series is None or value is None:
        return None
    clean = pd.to_numeric(pd.Series(series), errors="coerce").dropna()
    clean = clean[(clean > 0) & np.isfinite(clean)]
    if len(clean) < 4:
        return None
    return float((clean <= value).mean())


def _align(series: Optional[pd.Series], ref: pd.DatetimeIndex, tol_days: int = 75) -> pd.Series:
    """Riporta una voce di bilancio sulle date di riferimento dell'esercizio.

    Yahoo usa in genere la stessa data di chiusura per i tre prospetti, ma non
    sempre: agganciamo ogni valore alla data di riferimento piu' vicina.
    """
    out = pd.Series(index=ref, dtype="float64")
    if series is None or series.empty:
        return out
    try:
        idx = pd.to_datetime(series.index)
    except (TypeError, ValueError):
        return out
    values = pd.Series(series.values, index=idx).dropna()
    for date in ref:
        if values.empty:
            break
        deltas = (values.index - date).days
        nearest = int(np.argmin(np.abs(deltas)))
        if abs(deltas[nearest]) <= tol_days:
            out.loc[date] = float(values.iloc[nearest])
    return out


# --------------------------------------------------------------------------
# risultato
# --------------------------------------------------------------------------
@dataclass
class Metrics:
    symbol: str
    name: str
    currency: str = "THB"
    sector: Optional[str] = None
    industry: Optional[str] = None
    is_financial: bool = False
    price: Optional[float] = None
    market_cap: Optional[float] = None
    shares: Optional[float] = None
    years: pd.DataFrame = field(default_factory=pd.DataFrame)
    ttm: dict = field(default_factory=dict)
    growth: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)
    health: dict = field(default_factory=dict)
    valuation: dict = field(default_factory=dict)
    multiple_history: dict = field(default_factory=dict)
    trend: dict = field(default_factory=dict)
    dividend: dict = field(default_factory=dict)
    estimates: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def n_years(self) -> int:
        return 0 if self.years is None else int(len(self.years))

    def year_labels(self) -> list[str]:
        if self.years is None or self.years.empty:
            return []
        return [d.strftime("%Y") for d in self.years.index]


# --------------------------------------------------------------------------
# storico per esercizio
# --------------------------------------------------------------------------
def _build_years(data: StockData) -> pd.DataFrame:
    """Tabella per esercizio con voci grezze e indici derivati."""
    revenue = row(data.income_a, "TotalRevenue", "OperatingRevenue")
    if revenue is None or revenue.empty:
        # Banche e finanziarie: a volte Yahoo espone solo il margine di interesse.
        revenue = row(data.income_a, "NetInterestIncome", "TotalOperatingIncomeAsReported")
    if revenue is None or revenue.empty:
        return pd.DataFrame()

    ref = pd.DatetimeIndex(sorted(pd.to_datetime(revenue.index)))
    cols: dict[str, pd.Series] = {}

    def take(df, *keys, name=None):
        cols[name] = _align(row(df, *keys), ref)

    cols["revenue"] = _align(revenue, ref)
    take(data.income_a, "GrossProfit", name="gross_profit")
    take(data.income_a, "OperatingIncome", "TotalOperatingIncomeAsReported", name="operating_income")
    take(data.income_a, "EBITDA", "NormalizedEBITDA", name="ebitda")
    take(data.income_a, "EBIT", name="ebit")
    take(data.income_a, "PretaxIncome", name="pretax_income")
    take(data.income_a, "TaxProvision", name="tax_provision")
    take(data.income_a, "NetIncomeCommonStockholders", "NetIncome", name="net_income")
    take(data.income_a, "DilutedEPS", "BasicEPS", name="eps")
    take(data.income_a, "DilutedAverageShares", "BasicAverageShares", name="shares")
    take(data.income_a, "InterestExpense", "InterestExpenseNonOperating", name="interest_expense")
    take(data.income_a, "DividendPerShare", name="dps_reported")
    take(data.income_a, "ReconciledDepreciation", name="depreciation")

    take(data.balance_a, "StockholdersEquity", "CommonStockEquity", name="equity")
    take(data.balance_a, "TotalAssets", name="total_assets")
    take(data.balance_a, "TotalDebt", name="total_debt")
    take(data.balance_a, "NetDebt", name="net_debt_reported")
    take(data.balance_a, "CashCashEquivalentsAndShortTermInvestments", "CashAndCashEquivalents", name="cash")
    take(data.balance_a, "InvestedCapital", name="invested_capital_reported")
    take(data.balance_a, "CurrentAssets", name="current_assets")
    take(data.balance_a, "CurrentLiabilities", name="current_liabilities")
    take(data.balance_a, "OrdinarySharesNumber", "ShareIssued", name="shares_outstanding")
    take(data.balance_a, "TangibleBookValue", name="tangible_book")

    take(data.cash_a, "OperatingCashFlow", "CashFlowFromContinuingOperatingActivities", name="cfo")
    take(data.cash_a, "CapitalExpenditure", "CapitalExpenditureReported", "PurchaseOfPPE", name="capex")
    take(data.cash_a, "FreeCashFlow", name="fcf_reported")
    take(data.cash_a, "CashDividendsPaid", "CommonStockDividendPaid", name="dividends_paid")
    take(data.cash_a, "RepurchaseOfCapitalStock", name="buybacks")

    df = pd.DataFrame(cols, index=ref).sort_index()

    # --- normalizzazioni di segno -------------------------------------------
    df["capex"] = -df["capex"].abs()  # Yahoo la riporta negativa, la teniamo tale
    df["dividends_paid"] = df["dividends_paid"].abs()
    df["buybacks"] = df["buybacks"].abs()
    df["interest_expense"] = df["interest_expense"].abs()

    # --- voci ricostruite ---------------------------------------------------
    df["fcf"] = df["fcf_reported"].where(df["fcf_reported"].notna(), df["cfo"] + df["capex"])
    df["net_debt"] = df["net_debt_reported"].where(
        df["net_debt_reported"].notna(), df["total_debt"] - df["cash"]
    )
    df["invested_capital"] = df["invested_capital_reported"].where(
        df["invested_capital_reported"].notna(), df["equity"] + df["total_debt"]
    )
    df["shares"] = df["shares"].where(df["shares"].notna(), df["shares_outstanding"])
    df["eps"] = df["eps"].where(df["eps"].notna(), df["net_income"] / df["shares"])
    df["ebitda"] = df["ebitda"].where(
        df["ebitda"].notna(), df["operating_income"] + df["depreciation"]
    )
    df["ebit"] = df["ebit"].where(df["ebit"].notna(), df["operating_income"])

    dps = df["dps_reported"].copy()
    from_cash = df["dividends_paid"] / df["shares"]
    dps = dps.where(dps.notna(), from_cash)
    if data.dividends is not None and not data.dividends.empty:
        by_year = data.dividends.groupby(data.dividends.index.year).sum()
        paid = pd.Series(
            [coerce_float(by_year.get(d.year)) for d in df.index], index=df.index, dtype="float64"
        )
        dps = dps.where(dps.notna(), paid)
    df["dps"] = dps

    # --- indici derivati ----------------------------------------------------
    tax_rate = (df["tax_provision"] / df["pretax_income"]).clip(0.0, 0.40)
    df["tax_rate"] = tax_rate.fillna(THAI_CORPORATE_TAX)
    df["gross_margin"] = df["gross_profit"] / df["revenue"]
    df["operating_margin"] = df["operating_income"] / df["revenue"]
    df["ebitda_margin"] = df["ebitda"] / df["revenue"]
    df["net_margin"] = df["net_income"] / df["revenue"]

    avg_equity = (df["equity"] + df["equity"].shift(1)) / 2
    df["roe"] = df["net_income"] / avg_equity.where(avg_equity > 0, df["equity"])
    avg_assets = (df["total_assets"] + df["total_assets"].shift(1)) / 2
    df["roa"] = df["net_income"] / avg_assets.where(avg_assets > 0, df["total_assets"])
    nopat = df["ebit"] * (1 - df["tax_rate"])
    df["roic"] = nopat / df["invested_capital"].where(df["invested_capital"] > 0)

    df["net_debt_ebitda"] = df["net_debt"] / df["ebitda"].where(df["ebitda"] > 0)
    df["debt_equity"] = df["total_debt"] / df["equity"].where(df["equity"] > 0)
    df["interest_coverage"] = df["ebit"] / df["interest_expense"].where(df["interest_expense"] > 0)
    df["current_ratio"] = df["current_assets"] / df["current_liabilities"].where(
        df["current_liabilities"] > 0
    )
    df["equity_ratio"] = df["equity"] / df["total_assets"].where(df["total_assets"] > 0)
    df["payout"] = df["dps"] / df["eps"].where(df["eps"] > 0)
    df["fcf_margin"] = df["fcf"] / df["revenue"]
    df["capex_intensity"] = df["capex"].abs() / df["revenue"]
    df["cash_conversion"] = df["cfo"] / df["net_income"].where(df["net_income"] > 0)

    return df.dropna(axis=1, how="all")


# --------------------------------------------------------------------------
# TTM
# --------------------------------------------------------------------------
def _build_ttm(data: StockData, years: pd.DataFrame) -> dict:
    """Ultimi dodici mesi: dal prospetto trailing, dai 4 trimestri, o dall'ultimo anno."""
    ttm: dict[str, Optional[float]] = {}

    def pick(field_name: str, ttm_df, quarterly_df, *keys, annual_col: Optional[str] = None):
        value = first_value(ttm_df, *keys)
        source = "TTM Yahoo"
        if value is None:
            value = sum_last(quarterly_df, 4, *keys)
            source = "somma 4 trimestri"
        if value is None and annual_col and annual_col in years.columns and not years.empty:
            series = years[annual_col].dropna()
            if not series.empty:
                value = float(series.iloc[-1])
                source = "ultimo esercizio"
        ttm[field_name] = value
        ttm[field_name + "_source"] = source if value is not None else None

    pick("revenue", data.income_ttm, data.income_q, "TotalRevenue", "OperatingRevenue", annual_col="revenue")
    pick("gross_profit", data.income_ttm, data.income_q, "GrossProfit", annual_col="gross_profit")
    pick("operating_income", data.income_ttm, data.income_q, "OperatingIncome", annual_col="operating_income")
    pick("ebitda", data.income_ttm, data.income_q, "EBITDA", "NormalizedEBITDA", annual_col="ebitda")
    pick("ebit", data.income_ttm, data.income_q, "EBIT", annual_col="ebit")
    pick("net_income", data.income_ttm, data.income_q, "NetIncomeCommonStockholders", "NetIncome", annual_col="net_income")
    pick("cfo", data.cash_ttm, data.cash_q, "OperatingCashFlow", annual_col="cfo")
    pick("capex", data.cash_ttm, data.cash_q, "CapitalExpenditure", "CapitalExpenditureReported", annual_col="capex")
    pick("interest_expense", data.income_ttm, data.income_q, "InterestExpense", annual_col="interest_expense")

    if ttm.get("capex") is not None:
        ttm["capex"] = -abs(ttm["capex"])
    fcf = first_value(data.cash_ttm, "FreeCashFlow")
    if fcf is None and ttm.get("cfo") is not None and ttm.get("capex") is not None:
        fcf = ttm["cfo"] + ttm["capex"]
    ttm["fcf"] = fcf

    # EPS TTM: il dato per azione e' quello che conta per il P/E.
    eps = first_value(data.income_ttm, "DilutedEPS", "BasicEPS")
    if eps is None:
        eps = sum_last(data.income_q, 4, "DilutedEPS", "BasicEPS")
    if eps is None:
        eps = coerce_float(data.info.get("trailingEps"))
    if eps is None and not years.empty and "eps" in years.columns:
        series = years["eps"].dropna()
        eps = float(series.iloc[-1]) if not series.empty else None
    ttm["eps"] = eps

    # Patrimonio netto e debito: la foto piu' recente, non la media dell'anno.
    equity = first_value(data.balance_q, "StockholdersEquity", "CommonStockEquity")
    if equity is None and not years.empty and "equity" in years.columns:
        series = years["equity"].dropna()
        equity = float(series.iloc[-1]) if not series.empty else None
    ttm["equity"] = equity

    net_debt = first_value(data.balance_q, "NetDebt")
    if net_debt is None:
        debt = first_value(data.balance_q, "TotalDebt")
        cash = first_value(
            data.balance_q, "CashCashEquivalentsAndShortTermInvestments", "CashAndCashEquivalents"
        )
        if debt is not None:
            net_debt = debt - (cash or 0.0)
    if net_debt is None and not years.empty and "net_debt" in years.columns:
        series = years["net_debt"].dropna()
        net_debt = float(series.iloc[-1]) if not series.empty else None
    ttm["net_debt"] = net_debt
    ttm["total_debt"] = first_value(data.balance_q, "TotalDebt") or (
        float(years["total_debt"].dropna().iloc[-1])
        if not years.empty and "total_debt" in years.columns and years["total_debt"].notna().any()
        else None
    )

    ttm["net_margin"] = safe_div(ttm.get("net_income"), ttm.get("revenue"))
    ttm["operating_margin"] = safe_div(ttm.get("operating_income"), ttm.get("revenue"))
    ttm["roe"] = safe_div(ttm.get("net_income"), ttm.get("equity"))
    ttm["net_debt_ebitda"] = safe_div(ttm.get("net_debt"), ttm.get("ebitda"))
    ttm["interest_coverage"] = safe_div(ttm.get("ebit"), ttm.get("interest_expense"))
    return ttm


# --------------------------------------------------------------------------
# crescita
# --------------------------------------------------------------------------
def _build_growth(years: pd.DataFrame, ttm: dict) -> dict:
    out: dict = {"span_years": None}
    if years is None or years.empty:
        return out

    def series_of(col: str) -> pd.Series:
        return years[col].dropna() if col in years.columns else pd.Series(dtype="float64")

    for name, col in (("revenue", "revenue"), ("eps", "eps"), ("net_income", "net_income"),
                      ("fcf", "fcf"), ("dps", "dps"), ("equity", "equity")):
        s = series_of(col)
        if len(s) >= 2:
            span = (s.index[-1] - s.index[0]).days / 365.25
            out[f"{name}_cagr"] = cagr(s.iloc[0], s.iloc[-1], span)
            out[f"{name}_span"] = span
            out[f"{name}_last_yoy"] = pct(s.iloc[-1], s.iloc[-2])
        else:
            out[f"{name}_cagr"] = None
            out[f"{name}_span"] = None
            out[f"{name}_last_yoy"] = None

    rev = series_of("revenue")
    out["span_years"] = (rev.index[-1] - rev.index[0]).days / 365.25 if len(rev) >= 2 else None
    if len(rev) >= 3:
        changes = rev.pct_change().dropna()
        out["revenue_up_years"] = int((changes > 0).sum())
        out["revenue_total_years"] = int(len(changes))
        out["revenue_consecutive_declines"] = _trailing_run(changes, positive=False)
    net = series_of("net_income")
    out["profitable_years"] = int((net > 0).sum()) if not net.empty else None
    out["loss_years"] = int((net <= 0).sum()) if not net.empty else None
    fcf = series_of("fcf")
    out["fcf_positive_years"] = int((fcf > 0).sum()) if not fcf.empty else None
    out["fcf_total_years"] = int(len(fcf)) if not fcf.empty else None

    # Crescita TTM rispetto all'ultimo bilancio annuale: dice se sta accelerando.
    if ttm.get("revenue") is not None and not rev.empty:
        out["revenue_ttm_vs_last_year"] = pct(ttm["revenue"], rev.iloc[-1])
    net_ttm = ttm.get("net_income")
    if net_ttm is not None and not net.empty:
        out["net_income_ttm_vs_last_year"] = pct(net_ttm, net.iloc[-1])
    return out


def _trailing_run(changes: pd.Series, positive: bool) -> int:
    """Quanti periodi consecutivi, partendo dall'ultimo, vanno nella stessa direzione."""
    run = 0
    for value in reversed(list(changes.values)):
        if (value > 0) == positive and pd.notna(value):
            run += 1
        else:
            break
    return run


# --------------------------------------------------------------------------
# qualita' e solidita'
# --------------------------------------------------------------------------
def _mean_last(years: pd.DataFrame, col: str, n: int = 3) -> Optional[float]:
    if years is None or years.empty or col not in years.columns:
        return None
    s = years[col].dropna()
    if s.empty:
        return None
    return float(s.iloc[-n:].mean())


def _last(years: pd.DataFrame, col: str) -> Optional[float]:
    if years is None or years.empty or col not in years.columns:
        return None
    s = years[col].dropna()
    return float(s.iloc[-1]) if not s.empty else None


def _build_quality(years: pd.DataFrame, ttm: dict) -> dict:
    out = {
        "roe": ttm.get("roe") if ttm.get("roe") is not None else _last(years, "roe"),
        "roe_avg3": _mean_last(years, "roe", 3),
        "roic": _last(years, "roic"),
        "roic_avg3": _mean_last(years, "roic", 3),
        "roa": _last(years, "roa"),
        "gross_margin": _last(years, "gross_margin"),
        "operating_margin": ttm.get("operating_margin") or _last(years, "operating_margin"),
        "operating_margin_avg3": _mean_last(years, "operating_margin", 3),
        "net_margin": ttm.get("net_margin") or _last(years, "net_margin"),
        "fcf_margin": _last(years, "fcf_margin"),
        "cash_conversion": _mean_last(years, "cash_conversion", 3),
        "capex_intensity": _mean_last(years, "capex_intensity", 3),
    }
    # Stabilita' del margine operativo: un business prevedibile vale di piu'.
    if years is not None and not years.empty and "operating_margin" in years.columns:
        s = years["operating_margin"].dropna()
        out["operating_margin_std"] = float(s.std()) if len(s) >= 3 else None
        out["operating_margin_trend"] = (
            float(s.iloc[-1] - s.iloc[0]) if len(s) >= 2 else None
        )
    return out


def _build_health(years: pd.DataFrame, ttm: dict) -> dict:
    out = {
        "net_debt_ebitda": ttm.get("net_debt_ebitda")
        if ttm.get("net_debt_ebitda") is not None
        else _last(years, "net_debt_ebitda"),
        "debt_equity": _last(years, "debt_equity"),
        "interest_coverage": ttm.get("interest_coverage") or _last(years, "interest_coverage"),
        "current_ratio": _last(years, "current_ratio"),
        "equity_ratio": _last(years, "equity_ratio"),
        "equity": ttm.get("equity"),
        "net_debt": ttm.get("net_debt"),
        "payout": _last(years, "payout"),
        "fcf_ttm": ttm.get("fcf"),
    }
    if years is not None and not years.empty and "net_debt" in years.columns:
        s = years["net_debt"].dropna()
        out["net_debt_change_3y"] = (
            float(s.iloc[-1] - s.iloc[max(0, len(s) - 4)]) if len(s) >= 2 else None
        )
    if years is not None and not years.empty and "shares" in years.columns:
        s = years["shares"].dropna()
        if len(s) >= 2:
            span = (s.index[-1] - s.index[0]).days / 365.25
            out["share_count_cagr"] = cagr(s.iloc[0], s.iloc[-1], span)
    return out


# --------------------------------------------------------------------------
# multipli e loro storia
# --------------------------------------------------------------------------
def _valuation_history_series(df: Optional[pd.DataFrame], label: str) -> Optional[pd.Series]:
    """Estrae una riga dalla tabella dei multipli storici di Yahoo."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    wanted = label.replace(" ", "").replace("/", "").lower()
    match = None
    for idx in df.index:
        if str(idx).replace(" ", "").replace("/", "").lower() == wanted:
            match = idx
            break
    if match is None:
        return None
    series = df.loc[match]
    if isinstance(series, pd.DataFrame):
        series = series.iloc[0]
    series = series.drop(labels=[c for c in ("Current",) if c in series.index], errors="ignore")
    out = {}
    for label_col, value in series.items():
        value = coerce_float(value)
        if value is None:
            continue
        try:
            out[pd.to_datetime(label_col)] = value
        except (ValueError, TypeError):
            continue
    if not out:
        return None
    return pd.Series(out).sort_index()


def _computed_pe_history(data: StockData, years: pd.DataFrame) -> Optional[pd.Series]:
    """P/E storico ricostruito: prezzo di borsa diviso l'EPS dell'ultimo bilancio noto.

    Serve da riserva quando Yahoo non fornisce lo storico dei multipli.
    """
    if data.prices is None or data.prices.empty or years is None or years.empty:
        return None
    if "eps" not in years.columns:
        return None
    eps = years["eps"].dropna()
    eps = eps[eps > 0]
    if eps.empty:
        return None
    close = data.prices["Close"].dropna()
    # L'utile dell'esercizio e' noto al mercato ~3 mesi dopo la chiusura.
    known = pd.Series(eps.values, index=eps.index + pd.Timedelta(days=90)).sort_index()
    aligned = known.reindex(close.index, method="ffill")
    series = (close / aligned).dropna()
    series = series[(series > 0) & (series < 200)]
    return series if len(series) >= 60 else None


def _build_valuation(data: StockData, years: pd.DataFrame, ttm: dict, price: Optional[float],
                     market_cap: Optional[float], shares: Optional[float]) -> tuple[dict, dict]:
    info = data.info
    val: dict = {}

    # Un P/E negativo non e' una valutazione "bassa": con utili negativi il
    # multiplo non ha senso e va lasciato vuoto.
    eps_ttm = ttm.get("eps")
    pe = safe_div(price, eps_ttm) if (eps_ttm or 0) > 0 else None
    if pe is None:
        candidate = coerce_float(info.get("trailingPE"))
        pe = candidate if candidate and candidate > 0 else None
    val["pe"] = pe
    forward_pe = coerce_float(info.get("forwardPE"))
    val["forward_pe"] = forward_pe if forward_pe and forward_pe > 0 else None

    bvps = safe_div(ttm.get("equity"), shares) or coerce_float(info.get("bookValue"))
    val["bvps"] = bvps
    val["pb"] = safe_div(price, bvps) or coerce_float(info.get("priceToBook"))
    val["ps"] = safe_div(market_cap, ttm.get("revenue")) or coerce_float(
        info.get("priceToSalesTrailing12Months")
    )

    enterprise_value = None
    if market_cap is not None:
        enterprise_value = market_cap + (ttm.get("net_debt") or 0.0)
    enterprise_value = enterprise_value or coerce_float(info.get("enterpriseValue"))
    val["enterprise_value"] = enterprise_value
    val["ev_ebitda"] = safe_div(enterprise_value, ttm.get("ebitda"))
    val["ev_revenue"] = safe_div(enterprise_value, ttm.get("revenue"))

    val["fcf_yield"] = safe_div(ttm.get("fcf"), market_cap)
    val["earnings_yield"] = safe_div(1.0, val["pe"]) if val.get("pe") and val["pe"] > 0 else None
    val["peg"] = None
    growth_rate = None
    eps_growth = coerce_float(info.get("earningsGrowth"))
    if eps_growth and eps_growth > 0:
        growth_rate = eps_growth * 100
    if val.get("pe") and growth_rate:
        val["peg"] = val["pe"] / growth_rate

    # --- storia dei multipli ------------------------------------------------
    hist: dict = {}
    sources = {
        "pe": ("Trailing P/E", "pe"),
        "pb": ("Price/Book", "pb"),
        "ps": ("Price/Sales", "ps"),
        "ev_ebitda": ("Enterprise Value/EBITDA", "ev_ebitda"),
    }
    for key, (label, current_key) in sources.items():
        series = _valuation_history_series(data.valuation_quarterly, label)
        yearly = _valuation_history_series(data.valuation_yearly, label)
        if series is None or (yearly is not None and len(yearly) > len(series)):
            series = yearly
        if series is None and key == "pe":
            series = _computed_pe_history(data, years)
        if series is None:
            continue
        clean = series[(series > 0) & np.isfinite(series)]
        if len(clean) < 4:
            continue
        current = val.get(current_key)
        hist[key] = {
            "series": clean,
            "median": float(clean.median()),
            "mean": float(clean.mean()),
            "p25": float(clean.quantile(0.25)),
            "p75": float(clean.quantile(0.75)),
            "min": float(clean.min()),
            "max": float(clean.max()),
            "years": float((clean.index[-1] - clean.index[0]).days / 365.25),
            "percentile": percentile_of(clean, current),
            "vs_median": pct(current, float(clean.median())) if current else None,
        }
    return val, hist


# --------------------------------------------------------------------------
# prezzo e tendenza
# --------------------------------------------------------------------------
def _total_return(series: pd.Series, days: int) -> Optional[float]:
    series = series.dropna()
    if series.empty:
        return None
    end = series.index[-1]
    start_date = end - pd.Timedelta(days=days)
    window = series[series.index <= start_date]
    if window.empty:
        return None
    return pct(series.iloc[-1], window.iloc[-1])


def _build_trend(data: StockData, price: Optional[float]) -> dict:
    out: dict = {}
    if data.prices is None or data.prices.empty:
        return out
    close = data.prices["Close"].dropna()
    adj = data.prices["AdjClose"].dropna()
    if close.empty:
        return out

    out["last_date"] = close.index[-1]
    out["sma50"] = float(close.iloc[-50:].mean()) if len(close) >= 50 else None
    out["sma200"] = float(close.iloc[-200:].mean()) if len(close) >= 200 else None
    out["vs_sma200"] = pct(price, out.get("sma200"))
    out["vs_sma50"] = pct(price, out.get("sma50"))
    if out.get("sma50") and out.get("sma200"):
        out["sma50_above_sma200"] = out["sma50"] > out["sma200"]

    year = close[close.index >= close.index[-1] - pd.Timedelta(days=365)]
    if not year.empty:
        out["high_52w"] = float(year.max())
        out["low_52w"] = float(year.min())
        out["from_high_52w"] = pct(price, out["high_52w"])
        out["from_low_52w"] = pct(price, out["low_52w"])

    for label, days in (("1m", 30), ("3m", 91), ("6m", 182), ("1y", 365), ("3y", 1095), ("5y", 1826)):
        out[f"return_{label}"] = _total_return(adj, days)

    # Volatilita' annualizzata e massima perdita storica: il rischio percepito.
    returns = adj.pct_change().dropna()
    if len(returns) >= 60:
        out["volatility"] = float(returns.iloc[-TRADING_DAYS:].std() * math.sqrt(TRADING_DAYS))
    if len(adj) >= 250:
        running_max = adj.cummax()
        drawdown = adj / running_max - 1.0
        out["max_drawdown"] = float(drawdown.min())
        five_years = drawdown[drawdown.index >= drawdown.index[-1] - pd.Timedelta(days=1826)]
        out["max_drawdown_5y"] = float(five_years.min()) if not five_years.empty else None

    volume = data.prices.get("Volume")
    if volume is not None and not volume.dropna().empty and price:
        recent = volume.dropna().iloc[-60:]
        out["avg_turnover_60d"] = float(recent.mean() * price)

    # --- confronto con l'indice SET ----------------------------------------
    if data.benchmark is not None and not data.benchmark.empty:
        bench = data.benchmark["AdjClose"].dropna()
        for label, days in (("1y", 365), ("3y", 1095), ("5y", 1826)):
            bench_ret = _total_return(bench, days)
            own = out.get(f"return_{label}")
            if bench_ret is not None and own is not None:
                out[f"excess_{label}"] = own - bench_ret
            out[f"benchmark_return_{label}"] = bench_ret
        joined = pd.concat([adj.rename("stock"), bench.rename("bench")], axis=1).dropna()
        weekly = joined.resample("W").last().pct_change().dropna()
        weekly = weekly.iloc[-156:]  # ~3 anni di settimane
        if len(weekly) >= 52:
            variance = float(weekly["bench"].var())
            if variance > 1e-12:
                out["beta"] = float(weekly["stock"].cov(weekly["bench"]) / variance)
                out["correlation"] = float(weekly["stock"].corr(weekly["bench"]))
    if out.get("beta") is None:
        out["beta"] = coerce_float(data.info.get("beta"))
    return out


# --------------------------------------------------------------------------
# dividendo
# --------------------------------------------------------------------------
def _build_dividend(data: StockData, years: pd.DataFrame, price: Optional[float]) -> dict:
    out: dict = {}
    dividends = data.dividends
    if dividends is not None and not dividends.empty:
        by_year = dividends.groupby(dividends.index.year).sum()
        out["by_year"] = by_year
        # Dividendo corrente: la somma degli ultimi 12 mesi e' fragile, perche'
        # basta uno stacco spostato di qualche giorno per contarne due o zero.
        # Usiamo il "dividendo indicato": gli ultimi N stacchi, con N pari alla
        # cadenza abituale (1 annuale, 2 semestrale, 4 trimestrale).
        anchor = data.prices.index[-1] if (data.prices is not None and not data.prices.empty) else dividends.index[-1]
        window = dividends[(dividends.index > anchor - pd.Timedelta(days=365)) & (dividends.index <= anchor)]
        out["dps_last_12m"] = float(window.sum()) if not window.empty else None
        recent_years = [y for y in by_year.index if y < anchor.year][-4:]
        counts = [int((dividends.index.year == y).sum()) for y in recent_years]
        cadence = int(pd.Series(counts).median()) if counts else 0
        if cadence >= 1:
            out["cadence"] = cadence
            out["dps_ttm"] = float(dividends.iloc[-cadence:].sum())
        else:
            out["dps_ttm"] = out["dps_last_12m"]
        out["last_payment_date"] = dividends.index[-1]
        complete = by_year.iloc[:-1] if len(by_year) > 1 else by_year
        out["paying_years"] = int((complete > 0).sum())
        out["cuts"] = int((complete.diff() < -1e-9).sum()) if len(complete) >= 2 else 0
        out["consecutive_no_cut"] = _trailing_run(complete.diff().dropna(), positive=True)
        if len(complete) >= 3:
            span = complete.index[-1] - complete.index[0]
            out["dps_cagr"] = cagr(complete.iloc[0], complete.iloc[-1], span)
        # Rendimento storico: dividendo dell'anno sul prezzo medio dell'anno.
        if data.prices is not None and not data.prices.empty:
            close = data.prices["Close"].dropna()
            yearly_price = close.groupby(close.index.year).mean()
            yields = {}
            for yr, amount in by_year.items():
                base = coerce_float(yearly_price.get(yr))
                if base and amount:
                    yields[yr] = amount / base
            if yields:
                series = pd.Series(yields).sort_index()
                out["yield_by_year"] = series
                out["yield_median"] = float(series.median())
    if out.get("dps_ttm") is None:
        out["dps_ttm"] = _last(years, "dps")
    out["yield_current"] = safe_div(out.get("dps_ttm"), price)
    if out.get("yield_current") is None:
        raw = coerce_float(data.info.get("dividendYield"))
        if raw is not None:
            # Yahoo a volte da' 3.5 (percento) e a volte 0.035: normalizziamo.
            out["yield_current"] = raw / 100 if raw > 1 else raw
    out["payout"] = _last(years, "payout")
    return out


# --------------------------------------------------------------------------
# stime prospettiche
# --------------------------------------------------------------------------
def _estimate_row(df: Optional[pd.DataFrame], period: str, column: str) -> Optional[float]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    if period not in df.index:
        return None
    if column not in df.columns:
        return None
    return coerce_float(df.loc[period, column])


def _build_estimates(data: StockData, ttm: dict, price: Optional[float]) -> dict:
    info = data.info
    out: dict = {}
    out["eps_forward"] = coerce_float(
        info.get("forwardEps"),
        _estimate_row(data.earnings_estimate, "+1y", "avg"),
    )
    out["eps_current_year"] = _estimate_row(data.earnings_estimate, "0y", "avg")
    out["eps_next_year"] = _estimate_row(data.earnings_estimate, "+1y", "avg")
    out["eps_growth_next_year"] = _estimate_row(data.earnings_estimate, "+1y", "growth")
    out["revenue_growth_next_year"] = _estimate_row(data.revenue_estimate, "+1y", "growth")
    out["analysts"] = coerce_float(
        info.get("numberOfAnalystOpinions"),
        _estimate_row(data.earnings_estimate, "+1y", "numberOfAnalysts"),
    )

    growth = data.growth_estimates
    if growth is not None and isinstance(growth, pd.DataFrame) and not growth.empty:
        col = "stockTrend" if "stockTrend" in growth.columns else growth.columns[0]
        for period, key in (("+1y", "growth_next_year"), ("0y", "growth_current_year"),
                            ("+5y", "growth_long_term")):
            if period in growth.index:
                out[key] = coerce_float(growth.loc[period, col])

    targets = data.analyst_targets or {}
    out["target_mean"] = coerce_float(targets.get("mean"), info.get("targetMeanPrice"))
    out["target_median"] = coerce_float(targets.get("median"), info.get("targetMedianPrice"))
    out["target_high"] = coerce_float(targets.get("high"), info.get("targetHighPrice"))
    out["target_low"] = coerce_float(targets.get("low"), info.get("targetLowPrice"))
    out["target_upside"] = pct(out.get("target_mean"), price)
    out["recommendation"] = info.get("recommendationKey")
    out["recommendation_mean"] = coerce_float(info.get("recommendationMean"))

    # Se gli analisti non coprono il titolo (frequente sulle mid cap thailandesi)
    # restiamo sui fondamentali: e' la stima piu' onesta che abbiamo.
    if out.get("eps_forward") is None and ttm.get("eps") is not None:
        out["eps_forward"] = ttm["eps"]
        out["eps_forward_is_ttm"] = True
    return out


# --------------------------------------------------------------------------
# ingresso pubblico
# --------------------------------------------------------------------------
def compute_metrics(data: StockData) -> Metrics:
    """Trasforma i dati grezzi di un titolo in metriche pronte per l'analisi."""
    price = latest_close(data)
    years = _build_years(data)
    ttm = _build_ttm(data, years)

    shares = coerce_float(
        data.info.get("sharesOutstanding"),
        first_value(data.balance_q, "OrdinarySharesNumber", "ShareIssued"),
        _last(years, "shares_outstanding"),
        _last(years, "shares"),
    )
    market_cap = coerce_float(data.info.get("marketCap"))
    if market_cap is None and price is not None and shares is not None:
        market_cap = price * shares
    if shares is None and market_cap and price:
        shares = market_cap / price

    val, hist = _build_valuation(data, years, ttm, price, market_cap, shares)

    metrics = Metrics(
        symbol=data.symbol,
        name=data.name,
        currency=data.currency,
        sector=data.sector,
        industry=data.industry,
        is_financial=data.is_financial,
        price=price,
        market_cap=market_cap,
        shares=shares,
        years=years,
        ttm=ttm,
        growth=_build_growth(years, ttm),
        quality=_build_quality(years, ttm),
        health=_build_health(years, ttm),
        valuation=val,
        multiple_history=hist,
        trend=_build_trend(data, price),
        dividend=_build_dividend(data, years, price),
        estimates=_build_estimates(data, ttm, price),
    )

    if years.empty:
        metrics.notes.append(
            "Nessun bilancio disponibile su Yahoo per questo titolo: l'analisi si basa "
            "solo sul prezzo e sui pochi indicatori della scheda. Affidabilita' bassa."
        )
    elif len(years) < 3:
        metrics.notes.append(
            f"Solo {len(years)} esercizi di bilancio disponibili: le tendenze di lungo "
            "periodo sono indicative."
        )
    if metrics.is_financial:
        metrics.notes.append(
            "Titolo finanziario: EV/EBITDA e debito netto non sono significativi, "
            "il giudizio pesa piu' su P/B, ROE e qualita' degli utili."
        )
    if ttm.get("eps") is not None and ttm["eps"] <= 0:
        metrics.notes.append("Utile per azione negativo negli ultimi 12 mesi: il P/E non e' calcolabile.")
    return metrics
