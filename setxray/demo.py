"""Dati dimostrativi sintetici, per provare l'app senza collegamento a internet.

ATTENZIONE: le societa' di questo modulo NON esistono e i numeri sono
inventati. Servono solo a mostrare come funziona l'analisi e a far girare i
test. Nessun dato qui dentro riguarda una societa' reale della SET.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from setxray.datasource import StockData

PROFILES: dict[str, str] = {
    "solida": "Growing company, healthy accounts, reasonable valuation",
    "cara": "Quality company priced far above its own historical average",
    "difficolta": "Falling revenue, high debt, negative cash flow",
    "dividendo": "Stable utility with a generous dividend, rising for 10 years",
    "tagliato": "Cut its dividend in 2020 and now pays out almost all its earnings",
    "irregolare": "Pays only in good years: no continuity",
}

# The profile keys are identifiers (`demo:solida` in a symbol, and in the tests)
# so they stay as they are; these are the names the interface shows.
PROFILE_NAMES: dict[str, str] = {
    "solida": "solid",
    "cara": "expensive",
    "difficolta": "in trouble",
    "dividendo": "dividend payer",
    "tagliato": "dividend cut",
    "irregolare": "irregular payer",
}


def _annual_dates(n: int = 4, last_year: int = 2025) -> pd.DatetimeIndex:
    return pd.DatetimeIndex([pd.Timestamp(f"{last_year - i}-12-31") for i in range(n)][::-1])


def _quarter_dates(n: int = 5, last: str = "2026-06-30") -> pd.DatetimeIndex:
    end = pd.Timestamp(last)
    return pd.DatetimeIndex([end - pd.offsets.QuarterEnd(i) for i in range(n)][::-1])


def _frame(rows: dict[str, list[float]], dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Come Yahoo: voci in camelCase sull'indice, periodi a colonne (piu' recente prima)."""
    df = pd.DataFrame(rows, index=dates).T
    return df[sorted(df.columns, reverse=True)]


MARKET_DRIFT = 0.035
MARKET_VOL = 0.14


def _ohlc(shocks: np.ndarray, end_price: float, days: pd.DatetimeIndex, seed: int) -> pd.DataFrame:
    """Da una serie di rendimenti giornalieri a un OHLCV che finisce a `end_price`."""
    rng = np.random.default_rng(seed + 1)
    path = np.exp(np.cumsum(shocks))
    path = path / path[-1] * end_price
    close = pd.Series(path, index=days)
    return pd.DataFrame(
        {
            "Open": close.shift(1).fillna(close.iloc[0]),
            "High": close * (1 + rng.uniform(0, 0.012, len(days))),
            "Low": close * (1 - rng.uniform(0, 0.012, len(days))),
            "Close": close,
            "Volume": rng.integers(3_000_000, 40_000_000, len(days)).astype(float),
        },
        index=days,
    )


def _market_and_stock(end_price: float, years: float, drift: float, vol: float,
                      beta: float, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Indice SET e titolo, generati insieme in modo che il beta sia quello atteso.

    Il titolo e' costruito come `beta * mercato + rumore proprio`: senza questo
    legame la demo mostrerebbe un beta casuale vicino a zero, irrealistico.
    """
    days = pd.bdate_range(end="2026-09-11", periods=int(252 * years))
    n = len(days)
    market_shocks = np.random.default_rng(7).normal(
        MARKET_DRIFT / 252, MARKET_VOL / np.sqrt(252), n
    )
    idio_var = max(vol ** 2 - (beta * MARKET_VOL) ** 2, (0.08 ** 2))
    idio = np.random.default_rng(seed).normal(0.0, np.sqrt(idio_var / 252), n)
    stock_shocks = drift / 252 + beta * (market_shocks - MARKET_DRIFT / 252) + idio
    return _ohlc(market_shocks, 1480.0, days, 7), _ohlc(stock_shocks, end_price, days, seed)


def _params(profile: str) -> dict:
    base = dict(
        revenue0=90e9, revenue_growth=0.09, net_margin=0.11, margin_drift=0.002,
        shares=2.4e9, equity0=70e9, debt=38e9, cash=14e9, payout=0.45,
        capex_ratio=0.055, target_pe=10.5, hist_pe=14.5, drift=0.07, vol=0.26,
        name="Siam Sample Industries PCL (DEMO)", sector="Industrials",
        industry="Specialty Industrial Machinery", beta=0.95,
        dividend_profile="crescita", dividend_growth=0.06, cadence=2,
    )
    if profile == "cara":
        base.update(
            revenue_growth=0.11, net_margin=0.16, target_pe=34.0, hist_pe=19.0,
            debt=20e9, payout=0.30, drift=0.22, vol=0.30,
            name="Bangkok Premium Brands PCL (DEMO)", sector="Consumer Defensive",
            industry="Packaged Foods",
        )
    elif profile == "difficolta":
        base.update(
            revenue_growth=-0.08, net_margin=-0.03, margin_drift=-0.015,
            target_pe=0.0, hist_pe=11.0, debt=95e9, cash=6e9, payout=0.0,
            capex_ratio=0.09, drift=-0.22, vol=0.45,
            name="Chao Phraya Heavy Steel PCL (DEMO)", sector="Basic Materials",
            industry="Steel", beta=1.35,
        )
    elif profile == "dividendo":
        base.update(
            revenue_growth=0.03, net_margin=0.14, margin_drift=0.0,
            target_pe=11.0, hist_pe=13.0, debt=55e9, cash=9e9, payout=0.80,
            capex_ratio=0.07, drift=0.02, vol=0.17,
            name="Thai Regional Power PCL (DEMO)", sector="Utilities",
            industry="Utilities - Regulated Electric", beta=0.55,
            dividend_profile="crescita", dividend_growth=0.035, cadence=2,
        )
    elif profile == "tagliato":
        # Il caso che conta davvero per uno strumento sui dividendi: rendimento
        # alto perche' il mercato si aspetta un altro taglio, non perche' sia
        # un'occasione.
        base.update(
            revenue_growth=-0.01, net_margin=0.055, margin_drift=-0.008,
            target_pe=7.0, hist_pe=13.0, debt=72e9, cash=7e9, payout=0.95,
            capex_ratio=0.085, drift=-0.10, vol=0.32,
            name="Chiang Mai Property Trust PCL (DEMO)", sector="Real Estate",
            industry="Real Estate - Diversified", beta=1.15,
            dividend_profile="taglio", dividend_growth=0.02, cadence=2,
        )
    elif profile == "irregolare":
        base.update(
            revenue_growth=0.02, net_margin=0.08, margin_drift=0.0,
            target_pe=9.0, hist_pe=11.0, debt=40e9, cash=11e9, payout=0.35,
            capex_ratio=0.06, drift=0.01, vol=0.34,
            name="Andaman Marine Services PCL (DEMO)", sector="Industrials",
            industry="Marine Shipping", beta=1.25,
            dividend_profile="irregolare", dividend_growth=0.0, cadence=1,
        )
    elif profile == "difficolta":
        base.update(dividend_profile="nessuno")
    return base


def _annual_dps(p: dict, dps_ultimo: float) -> dict[int, float]:
    """Dividendo per azione, anno per anno, dal 2015 al 2026.

    Costruito a ritroso dall'ultimo anno, cosi' il rendimento di oggi resta
    coerente con il prezzo ancorato al P/E del profilo.
    """
    forma = p["dividend_profile"]
    if forma == "nessuno" or dps_ultimo <= 0:
        return {}
    crescita = p["dividend_growth"]
    anni = list(range(2015, 2027))
    serie: dict[int, float] = {}

    if forma == "crescita":
        for anno in anni:
            serie[anno] = dps_ultimo / (1 + crescita) ** (2025 - anno)
    elif forma == "taglio":
        # Cresce fino al 2019, taglio del 55% nel 2020, risalita parziale.
        picco = dps_ultimo / 0.62
        for anno in anni:
            if anno <= 2019:
                serie[anno] = picco / (1 + 0.07) ** (2019 - anno)
            elif anno == 2020:
                serie[anno] = picco * 0.45
            else:
                serie[anno] = picco * 0.45 * (1 + 0.065) ** (anno - 2020)
    elif forma == "irregolare":
        # Paga solo negli anni buoni: il classico ciclico che distribuisce
        # quando il ciclo gira e salta quando non gira.
        saltati = {2016, 2020, 2021, 2024}
        for anno in anni:
            serie[anno] = 0.0 if anno in saltati else dps_ultimo * (0.7 + 0.3 * ((anno % 3) / 2))
    # L'anno in corso e' incompleto: solo la prima parte degli stacchi.
    if 2026 in serie:
        serie[2026] = serie[2026] * (1.0 / max(1, p["cadence"]))
    return {anno: valore for anno, valore in serie.items() if valore > 0}


def _dividend_payments(p: dict, dps_ultimo: float) -> Optional[pd.Series]:
    """Dal dividendo annuale ai singoli stacchi, con le date di stacco."""
    per_anno = _annual_dps(p, dps_ultimo)
    if not per_anno:
        return None
    cadenza = max(1, int(p["cadence"]))
    # Stacchi tipici della SET: finale in aprile, interinale a settembre.
    mesi = {1: [(4, 25)], 2: [(4, 25), (9, 5)], 4: [(2, 20), (5, 15), (8, 14), (11, 13)]}[cadenza]
    date, importi = [], []
    for anno, totale in sorted(per_anno.items()):
        quanti = len(mesi) if anno < 2026 else max(1, len(mesi) - 1)
        for mese, giorno in mesi[:quanti]:
            date.append(pd.Timestamp(f"{anno}-{mese:02d}-{giorno:02d}"))
            importi.append(round(totale / quanti, 4))
    serie = pd.Series(importi, index=pd.DatetimeIndex(date)).sort_index()
    serie = serie[serie.index <= pd.Timestamp("2026-09-11")]
    return serie if not serie.empty else None


def build_demo(profile: str = "solida") -> StockData:
    """Costruisce uno `StockData` completo e coerente con dati inventati."""
    if profile not in PROFILES:
        raise ValueError(f"Unknown demo profile: {profile!r}. Choose from {sorted(PROFILES)}")
    p = _params(profile)
    annual = _annual_dates()
    quarters = _quarter_dates()
    n = len(annual)

    revenue = [p["revenue0"] * (1 + p["revenue_growth"]) ** i for i in range(n)]
    margins = [p["net_margin"] + p["margin_drift"] * i for i in range(n)]
    net_income = [r * m for r, m in zip(revenue, margins)]
    shares = [p["shares"] * (1 + 0.004 * i) for i in range(n)]
    eps = [ni / s for ni, s in zip(net_income, shares)]
    dps = [max(0.0, e) * p["payout"] for e in eps]

    gross = [r * 0.31 for r in revenue]
    operating = [r * (m + 0.045) for r, m in zip(revenue, margins)]
    depreciation = [r * 0.045 for r in revenue]
    ebitda = [o + d for o, d in zip(operating, depreciation)]
    interest = [p["debt"] * 0.042] * n
    pretax = [o - i for o, i in zip(operating, interest)]
    tax = [max(0.0, t) * 0.20 for t in pretax]

    equity, retained = [], p["equity0"]
    for ni, d, s in zip(net_income, dps, shares):
        retained += ni - d * s
        equity.append(retained)
    debt = [p["debt"] * (1 + (0.12 if profile == "difficolta" else 0.01) * i) for i in range(n)]
    cash = [p["cash"] * (1 + 0.05 * i) for i in range(n)]
    assets = [e + d_ + 22e9 for e, d_ in zip(equity, debt)]

    cfo = [ni + dep * 0.95 for ni, dep in zip(net_income, depreciation)]
    capex = [-r * p["capex_ratio"] for r in revenue]
    fcf = [c + x for c, x in zip(cfo, capex)]

    income_a = _frame(
        {
            "TotalRevenue": revenue, "GrossProfit": gross, "OperatingIncome": operating,
            "EBITDA": ebitda, "EBIT": operating, "PretaxIncome": pretax, "TaxProvision": tax,
            "NetIncome": net_income, "NetIncomeCommonStockholders": net_income,
            "DilutedEPS": eps, "BasicEPS": eps, "DilutedAverageShares": shares,
            "InterestExpense": interest, "ReconciledDepreciation": depreciation,
        },
        annual,
    )
    balance_a = _frame(
        {
            "StockholdersEquity": equity, "TotalAssets": assets, "TotalDebt": debt,
            "CashCashEquivalentsAndShortTermInvestments": cash,
            "NetDebt": [d_ - c for d_, c in zip(debt, cash)],
            "InvestedCapital": [e + d_ for e, d_ in zip(equity, debt)],
            "CurrentAssets": [a * 0.34 for a in assets],
            "CurrentLiabilities": [a * (0.30 if profile == "difficolta" else 0.21) for a in assets],
            "OrdinarySharesNumber": shares, "TangibleBookValue": [e * 0.9 for e in equity],
        },
        annual,
    )
    cash_a = _frame(
        {
            "OperatingCashFlow": cfo, "CapitalExpenditure": capex, "FreeCashFlow": fcf,
            "CashDividendsPaid": [-d * s for d, s in zip(dps, shares)],
        },
        annual,
    )

    # Trimestri: l'ultimo anno spalmato su 4 trimestri + 1 trimestre in piu'.
    q_growth = 1 + p["revenue_growth"] / 4
    q_rev = [revenue[-1] / 4 * q_growth ** (i - 2) for i in range(len(quarters))]
    q_ni = [r * margins[-1] for r in q_rev]
    income_q = _frame(
        {
            "TotalRevenue": q_rev, "OperatingIncome": [r * (margins[-1] + 0.045) for r in q_rev],
            "EBITDA": [r * (margins[-1] + 0.09) for r in q_rev], "EBIT": [r * (margins[-1] + 0.045) for r in q_rev],
            "NetIncome": q_ni, "NetIncomeCommonStockholders": q_ni,
            "DilutedEPS": [x / shares[-1] for x in q_ni],
            "InterestExpense": [interest[-1] / 4] * len(quarters),
        },
        quarters,
    )
    balance_q = _frame(
        {
            "StockholdersEquity": [equity[-1] * (1 + 0.012 * i) for i in range(len(quarters))],
            "TotalDebt": [debt[-1]] * len(quarters),
            "CashCashEquivalentsAndShortTermInvestments": [cash[-1]] * len(quarters),
            "NetDebt": [debt[-1] - cash[-1]] * len(quarters),
            "OrdinarySharesNumber": [shares[-1]] * len(quarters),
            "TotalAssets": [assets[-1]] * len(quarters),
        },
        quarters,
    )
    cash_q = _frame(
        {
            "OperatingCashFlow": [cfo[-1] / 4] * len(quarters),
            "CapitalExpenditure": [capex[-1] / 4] * len(quarters),
            "FreeCashFlow": [fcf[-1] / 4] * len(quarters),
        },
        quarters,
    )

    ttm_date = pd.DatetimeIndex([pd.Timestamp("2026-06-30")])
    rev_ttm = sum(q_rev[-4:])
    ni_ttm = sum(q_ni[-4:])
    eps_ttm = ni_ttm / shares[-1]
    income_ttm = _frame(
        {
            "TotalRevenue": [rev_ttm], "NetIncome": [ni_ttm], "NetIncomeCommonStockholders": [ni_ttm],
            "DilutedEPS": [eps_ttm], "EBITDA": [rev_ttm * (margins[-1] + 0.09)],
            "EBIT": [rev_ttm * (margins[-1] + 0.045)],
            "OperatingIncome": [rev_ttm * (margins[-1] + 0.045)], "InterestExpense": [interest[-1]],
        },
        ttm_date,
    )
    cash_ttm = _frame(
        {"OperatingCashFlow": [cfo[-1]], "CapitalExpenditure": [capex[-1]], "FreeCashFlow": [fcf[-1]]},
        ttm_date,
    )

    # Prezzo: lo ancoriamo al P/E obiettivo del profilo, cosi' i casi d'uso
    # (titolo economico / caro / in perdita) sono riproducibili.
    if eps_ttm > 0 and p["target_pe"] > 0:
        end_price = eps_ttm * p["target_pe"]
    else:
        end_price = max(1.0, equity[-1] / shares[-1] * 0.45)
    seed = sum(ord(c) for c in profile) * 37
    # Undici anni di borsa: le misure a dieci anni hanno bisogno di un punto
    # di partenza *oltre* i dieci anni, non esattamente a dieci.
    bench, prices = _market_and_stock(end_price, 11.2, p["drift"], p["vol"], p["beta"], seed)
    prices["AdjClose"] = prices["Close"] * 0.96
    bench["AdjClose"] = bench["Close"]

    dividends = _dividend_payments(p, dps[-1] if dps else 0.0)

    market_cap = end_price * shares[-1]
    info = {
        "longName": p["name"], "sector": p["sector"], "industry": p["industry"],
        "currency": "THB", "exchange": "SET", "marketCap": market_cap,
        "sharesOutstanding": shares[-1], "bookValue": equity[-1] / shares[-1],
        "beta": p["beta"], "trailingEps": eps_ttm,
        "forwardEps": eps_ttm * (1 + max(-0.2, p["revenue_growth"])),
        "currentPrice": end_price, "previousClose": end_price,
        "longBusinessSummary": (
            "Fictional company created for SET X-Ray's demonstration mode. No real data, "
            "no connection to any existing company."
        ),
        "numberOfAnalystOpinions": 9,
        "recommendationKey": {
            "solida": "buy", "cara": "hold", "difficolta": "underperform",
            "dividendo": "hold", "tagliato": "hold", "irregolare": "hold",
        }[profile],
        "targetMeanPrice": end_price * {
            "solida": 1.22, "cara": 1.04, "difficolta": 0.92,
            "dividendo": 1.04, "tagliato": 0.95, "irregolare": 1.08,
        }[profile],
    }

    # Storico dei multipli: centrato sul P/E medio storico del profilo.
    hist_dates = [f"12/31/{y}" for y in range(2026 - 8, 2026)]
    rng = np.random.default_rng(11)
    pe_hist = [max(3.0, p["hist_pe"] * (1 + rng.normal(0, 0.18))) for _ in hist_dates]
    pb_hist = [max(0.3, p["hist_pe"] / 9 * (1 + rng.normal(0, 0.18))) for _ in hist_dates]
    valuation_yearly = pd.DataFrame(
        {
            "Current": [
                market_cap, market_cap + debt[-1] - cash[-1],
                (end_price / eps_ttm) if eps_ttm > 0 else float("nan"),
                (end_price / eps_ttm * 0.92) if eps_ttm > 0 else float("nan"),
                float("nan"), market_cap / rev_ttm,
                end_price / (equity[-1] / shares[-1]),
                (market_cap + debt[-1] - cash[-1]) / rev_ttm,
                (market_cap + debt[-1] - cash[-1]) / (rev_ttm * (margins[-1] + 0.09)),
            ]
        },
        index=["Market Cap", "Enterprise Value", "Trailing P/E", "Forward P/E",
               "PEG Ratio (5yr expected)", "Price/Sales", "Price/Book",
               "Enterprise Value/Revenue", "Enterprise Value/EBITDA"],
    )
    for i, col in enumerate(hist_dates[::-1]):
        valuation_yearly[col] = [
            market_cap * 0.9, market_cap, pe_hist[i], pe_hist[i] * 0.92,
            float("nan"), p["hist_pe"] / 11, pb_hist[i], 1.4, p["hist_pe"] / 1.9,
        ]

    data = StockData(
        symbol=f"DEMO-{profile.upper()}",
        yahoo_symbol=f"DEMO-{profile.upper()}.BK",
        info=info, prices=prices, benchmark=bench,
        income_a=income_a, income_q=income_q, income_ttm=income_ttm,
        balance_a=balance_a, balance_q=balance_q,
        cash_a=cash_a, cash_q=cash_q, cash_ttm=cash_ttm,
        dividends=dividends,  # None per i profili che non distribuiscono
        analyst_targets={
            "current": end_price, "mean": info["targetMeanPrice"],
            "median": info["targetMeanPrice"] * 0.99,
            "high": info["targetMeanPrice"] * 1.25, "low": info["targetMeanPrice"] * 0.72,
        },
        earnings_estimate=pd.DataFrame(
            {"avg": [eps_ttm * 1.05, info["forwardEps"]], "growth": [0.05, p["revenue_growth"]],
             "numberOfAnalysts": [9, 8]},
            index=["0y", "+1y"],
        ),
        revenue_estimate=pd.DataFrame(
            {"avg": [rev_ttm * 1.03, rev_ttm * (1 + p["revenue_growth"])],
             "growth": [0.03, p["revenue_growth"]]},
            index=["0y", "+1y"],
        ),
        growth_estimates=pd.DataFrame(
            {"stockTrend": [0.05, p["revenue_growth"], p["revenue_growth"] * 0.8]},
            index=["0y", "+1y", "+5y"],
        ),
        valuation_yearly=valuation_yearly,
        is_demo=True,
    )
    data.warnings.append(
        "DEMONSTRATION MODE: invented company, synthetic numbers. Do not use for investment "
        "decisions."
    )
    return data
