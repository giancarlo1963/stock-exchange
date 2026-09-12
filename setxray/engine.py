"""Il filo che unisce tutto: da un simbolo a una decisione.

    analisi = analyze("PTT")
    print(analisi.verdict.headline)
    print(analisi.report())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from setxray import narrative
from setxray.datasource import (
    DEFAULT_CACHE_TTL_MIN,
    StockData,
    fetch_stock,
    normalize_symbol,
)
from setxray.dividends import DividendAnalysis, analyze_dividends
from setxray.metrics import Metrics, compute_metrics
from setxray.sources import DividendSet, collect_dividends, requested_sources
from setxray.scoring import Verdict, evaluate
from setxray.valuation import (
    EQUITY_RISK_PREMIUM_TH,
    RISK_FREE_TH,
    Valuation,
    value_company,
)


class NoDataError(RuntimeError):
    """Nessun dato utilizzabile per il simbolo richiesto."""


@dataclass
class Analysis:
    """Il risultato completo: dati grezzi, metriche, valore, verdetto, racconto."""

    data: StockData
    metrics: Metrics
    valuation: Valuation
    verdict: Verdict
    dividends: Optional[DividendAnalysis] = None
    narrative: dict[str, list[str]] = field(default_factory=dict)

    @property
    def symbol(self) -> str:
        return self.metrics.symbol

    @property
    def name(self) -> str:
        return self.metrics.name

    def report(self) -> str:
        """Il report in markdown, pronto da salvare."""
        return narrative.build_report(self)


def analyze_data(data: StockData, *, risk_free: float = RISK_FREE_TH,
                 erp: float = EQUITY_RISK_PREMIUM_TH,
                 dividend_sources: Optional[list[str]] = None) -> Analysis:
    """Esegue l'analisi su dati gia' scaricati (o sintetici, per i test).

    I dividendi vengono raccolti *prima* delle metriche: se una fonte piu'
    affidabile di Yahoo ha una storia piu' lunga, e' quella che deve alimentare
    rendimento, payout e modello di Gordon, non solo la scheda dividendi.
    """
    if dividend_sources is None:
        dividend_sources = [] if data.is_demo else requested_sources()
    raccolta = collect_dividends(data.symbol, only=dividend_sources,
                                 fallback=data.dividends)
    if raccolta.ok and (data.dividends is None
                        or len(raccolta.series) >= len(data.dividends)):
        data.dividends = raccolta.series

    metrics = compute_metrics(data)
    if metrics.price is None:
        raise NoDataError(
            f"Nessun prezzo disponibile per {data.symbol}. Controlla il simbolo: "
            "deve essere quello della SET, per esempio PTT, AOT, CPALL."
        )
    valuation = value_company(metrics, risk_free=risk_free, erp=erp)
    verdict = evaluate(metrics, valuation)
    dividendi = analyze_dividends(metrics, data.prices, raccolta)
    analysis = Analysis(data=data, metrics=metrics, valuation=valuation,
                        verdict=verdict, dividends=dividendi)
    analysis.narrative = {
        "passato": narrative.past(metrics),
        "presente": narrative.present(metrics, valuation),
        "futuro": narrative.future(metrics, valuation, verdict),
        "dividendi": narrative.dividends(dividendi),
    }
    return analysis


def analyze(symbol: str, *, cache_ttl_min: float = DEFAULT_CACHE_TTL_MIN,
            risk_free: float = RISK_FREE_TH, erp: float = EQUITY_RISK_PREMIUM_TH,
            history_period: str = "11y",
            dividend_sources: Optional[list[str]] = None) -> Analysis:
    """Scarica i dati di un titolo SET e restituisce l'analisi completa.

    Il simbolo puo' essere scritto come si vuole: "ptt", "PTT", "PTT.BK".
    Usa `demo:<profilo>` per lavorare sui dati dimostrativi senza rete.
    """
    if str(symbol).lower().startswith("demo"):
        from setxray.demo import build_demo

        _, _, profile = str(symbol).replace("-", ":").partition(":")
        return analyze_data(build_demo(profile or "solida"), risk_free=risk_free, erp=erp)

    normalize_symbol(symbol)  # convalida subito, prima di toccare la rete
    data = fetch_stock(symbol, cache_ttl_min=cache_ttl_min, history_period=history_period)
    if data.prices is None and not data.info:
        raise NoDataError(
            f"Yahoo Finance non restituisce dati per {data.yahoo_symbol}. "
            "Verifica che il simbolo esista alla SET e che ci sia connessione a internet."
        )
    return analyze_data(data, risk_free=risk_free, erp=erp,
                        dividend_sources=dividend_sources)
