"""Quanto vale l'azienda, con quattro metodi indipendenti.

Nessun modello singolo e' affidabile da solo: un DCF si piega a qualunque
ipotesi, un multiplo storico non vede i cambi di regime, un modello sui
dividendi non dice niente di chi non li paga. Qui ne calcoliamo quattro, li
teniamo separati e visibili, e li mediamo con pesi che dipendono dal tipo di
azienda. Il risultato e' una forchetta (pessimistico / centrale /
ottimistico), non un numero secco.

Tutti i modelli sono costruiti per un orizzonte di 1-2 anni: l'ipotesi di
fondo e' che in due anni il prezzo tenda al valore stimato.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from setxray.metrics import Metrics, safe_div

# --- parametri di mercato (Thailandia) ------------------------------------
# Rendimento del titolo di stato thailandese a 10 anni e premio per il rischio
# azionario del paese. Sono ipotesi: l'interfaccia permette di cambiarle.
RISK_FREE_TH = 0.028
EQUITY_RISK_PREMIUM_TH = 0.075
# Anche il titolo piu' difensivo della SET resta un'azione di un mercato
# emergente: sotto il 9% di rendimento richiesto non si scende, altrimenti i
# modelli a crescita perpetua producono valori fuori scala.
COST_OF_EQUITY_FLOOR = 0.090
COST_OF_EQUITY_CAP = 0.170
TERMINAL_GROWTH = 0.025  # crescita perpetua: non piu' del PIL nominale di lungo periodo
# Nessuna azienda cresce per sempre piu' del PIL nominale del paese. Questo
# tetto e' cio' che impedisce al P/B giustificato e al modello sui dividendi di
# esplodere quando la crescita si avvicina al tasso di sconto.
PERPETUAL_GROWTH_CAP = 0.040
MIN_DISCOUNT_SPREAD = 0.030  # distanza minima fra tasso e crescita perpetua
DEFAULT_SET_PE = 14.0  # multiplo di riferimento del mercato thailandese
HORIZON_YEARS = 2.0
TARGET_TOTAL_RETURN = 0.20  # rendimento complessivo a 2 anni richiesto per comprare


@dataclass
class MethodResult:
    key: str
    label: str
    fair_value: Optional[float]
    weight: float = 0.0
    detail: str = ""
    skipped_reason: Optional[str] = None

    @property
    def usable(self) -> bool:
        return self.fair_value is not None and self.fair_value > 0


@dataclass
class Scenario:
    """Ipotesi di uno scenario: come piegare multipli, crescita e tasso."""

    name: str
    multiple_key: str  # "p25" / "median" / "p75"
    growth_shift: float
    rate_shift: float


BEAR = Scenario("pessimistico", "p25", -0.03, +0.015)
BASE = Scenario("centrale", "median", 0.0, 0.0)
BULL = Scenario("ottimistico", "p75", +0.03, -0.010)


@dataclass
class Valuation:
    cost_of_equity: float
    risk_free: float
    equity_risk_premium: float
    beta: float
    sustainable_growth: Optional[float] = None
    methods: list[MethodResult] = field(default_factory=list)
    fair_bear: Optional[float] = None
    fair_base: Optional[float] = None
    fair_bull: Optional[float] = None
    upside_bear: Optional[float] = None
    upside_base: Optional[float] = None
    upside_bull: Optional[float] = None
    dividend_yield: Optional[float] = None
    expected_return_2y: Optional[float] = None
    expected_annualized: Optional[float] = None
    entry_price: Optional[float] = None
    analyst_target: Optional[float] = None
    analyst_upside: Optional[float] = None
    dispersion: Optional[float] = None
    reliability: str = "media"  # "alta" / "media" / "bassa"
    notes: list[str] = field(default_factory=list)

    @property
    def has_fair_value(self) -> bool:
        return self.fair_base is not None and self.fair_base > 0

    def usable_methods(self) -> list[MethodResult]:
        return [m for m in self.methods if m.usable]


# --------------------------------------------------------------------------
# costo del capitale e crescita sostenibile
# --------------------------------------------------------------------------
def cost_of_equity(beta: Optional[float], risk_free: float = RISK_FREE_TH,
                   erp: float = EQUITY_RISK_PREMIUM_TH) -> tuple[float, float]:
    """CAPM con beta limitato: ritorna (costo del capitale, beta usato).

    Un beta stimato fuori da [0.4, 1.8] e' quasi sempre rumore statistico su un
    titolo poco liquido, non un'informazione sul rischio: lo riportiamo dentro.
    """
    b = beta if beta is not None else 1.0
    b = min(max(b, 0.4), 1.8)
    rate = risk_free + b * erp
    return min(max(rate, COST_OF_EQUITY_FLOOR), COST_OF_EQUITY_CAP), b


def sustainable_growth(metrics: Metrics) -> Optional[float]:
    """Crescita autofinanziata: ROE x quota di utili reinvestiti."""
    roe = metrics.quality.get("roe_avg3") or metrics.quality.get("roe")
    payout = metrics.health.get("payout")
    if roe is None:
        return None
    retention = 1.0 - (payout if payout is not None else 0.4)
    retention = min(max(retention, 0.0), 1.0)
    growth = roe * retention
    return min(max(growth, -0.05), 0.15)


def _growth_estimate(metrics: Metrics) -> Optional[float]:
    """Crescita di partenza per il DCF: la piu' prudente fra le stime disponibili."""
    candidates = [
        metrics.estimates.get("eps_growth_next_year"),
        metrics.estimates.get("growth_next_year"),
        metrics.estimates.get("revenue_growth_next_year"),
        metrics.growth.get("revenue_cagr"),
        sustainable_growth(metrics),
    ]
    values = [c for c in candidates if c is not None and -0.5 < c < 1.0]
    if not values:
        return None
    values.sort()
    median = values[len(values) // 2]
    return min(max(median, -0.10), 0.15)


# --------------------------------------------------------------------------
# i quattro metodi
# --------------------------------------------------------------------------
def _justified_pe(rate: float, growth: Optional[float], payout: Optional[float]) -> Optional[float]:
    """P/E coerente con redditivita', crescita e tasso (da Gordon).

    Serve da tetto al multiplo storico: impedisce di giustificare un prezzo
    alto solo perche' in passato il titolo era ancora piu' caro.
    """
    if growth is None:
        return None
    g = min(growth, rate - 0.015)
    if rate - g <= 0.005:
        return None
    pay = payout if payout is not None else 0.45
    pay = min(max(pay, 0.15), 0.95)
    value = pay * (1 + g) / (rate - g)
    return value if 2.0 < value < 40.0 else None


def _method_multiple(metrics: Metrics, scenario: Scenario, rate: float) -> MethodResult:
    """Reversione al multiplo storico del titolo applicata all'utile atteso."""
    eps = metrics.estimates.get("eps_forward") or metrics.ttm.get("eps")
    if eps is None or eps <= 0:
        return MethodResult("multiple", "Multiplo storico (P/E)", None,
                            skipped_reason="utile per azione non positivo")
    hist = metrics.multiple_history.get("pe") or {}
    target = hist.get(scenario.multiple_key) or hist.get("median")
    source = f"mediana {hist.get('years', 0):.0f} anni" if target else "media di mercato SET"
    if target is None:
        target = DEFAULT_SET_PE * (0.85 if scenario is BEAR else 1.15 if scenario is BULL else 1.0)
    growth = _growth_estimate(metrics)
    ceiling = _justified_pe(rate, growth, metrics.health.get("payout"))
    if ceiling is not None and target > ceiling * 1.3:
        target = ceiling * 1.3
        source += ", limitato dal P/E giustificato"
    target = min(max(target, 5.0), 30.0)
    return MethodResult(
        "multiple", "Multiplo storico (P/E)", eps * target,
        detail=f"utile atteso {eps:.2f} x P/E {target:.1f} ({source})",
    )


def _method_ddm(metrics: Metrics, scenario: Scenario, rate: float) -> MethodResult:
    """Gordon: valore dei dividendi futuri, per chi paga un dividendo stabile.

    Il modello vede solo la cassa distribuita, quindi sottovaluta per
    costruzione chi reinveste: lo applichiamo solo quando il dividendo e' una
    parte rilevante del ritorno, non a tutti i titoli.
    """
    label = "Dividendi scontati (Gordon)"
    dps = metrics.dividend.get("dps_ttm")
    if not dps or dps <= 0:
        return MethodResult("ddm", label, None, skipped_reason="nessun dividendo")
    payout = metrics.health.get("payout")
    yield_now = metrics.dividend.get("yield_current") or 0.0
    if payout is not None and payout > 1.5:
        return MethodResult("ddm", label, None,
                            skipped_reason="dividendo superiore agli utili, non sostenibile")
    # Il tetto alla crescita perpetua rende Gordon strutturalmente pessimista su
    # chi reinveste: usiamolo solo quando il dividendo e' davvero la fonte
    # principale del rendimento.
    if yield_now < 0.035 and not (payout is not None and payout >= 0.55):
        return MethodResult("ddm", label, None,
                            skipped_reason="dividendo non dominante nel rendimento: modello non adatto")
    candidates = [sustainable_growth(metrics), metrics.growth.get("dps_cagr"),
                  metrics.growth.get("revenue_cagr")]
    values = sorted(c for c in candidates if c is not None)
    g = values[0] if values else 0.02  # la piu' prudente
    g = min(max(g + scenario.growth_shift, -0.02), PERPETUAL_GROWTH_CAP)
    r = max(rate + scenario.rate_shift, g + MIN_DISCOUNT_SPREAD)
    # Un multiplo sul dividendo oltre 28x e' un artefatto del modello, non una
    # valutazione: vuol dire che tasso e crescita sono troppo vicini.
    fair = min(dps * (1 + g) / (r - g), dps * 28)
    return MethodResult("ddm", label, fair,
                        detail=f"dividendo {dps:.2f}, crescita {g:.1%}, tasso {r:.1%}")


def _method_dcf(metrics: Metrics, scenario: Scenario, rate: float) -> MethodResult:
    """Flussi di cassa liberi attualizzati, con crescita che sfuma in 5 anni."""
    fcf = metrics.ttm.get("fcf")
    shares = metrics.shares
    if fcf is None or shares is None or shares <= 0:
        return MethodResult("dcf", "Flussi di cassa scontati", None,
                            skipped_reason="flusso di cassa non disponibile")
    if fcf <= 0:
        return MethodResult("dcf", "Flussi di cassa scontati", None,
                            skipped_reason="flusso di cassa libero negativo")
    fcf_ps = fcf / shares
    g0 = _growth_estimate(metrics)
    if g0 is None:
        g0 = 0.03
    g0 = min(max(g0 + scenario.growth_shift, -0.08), 0.15)
    r = min(max(rate + scenario.rate_shift, 0.05), 0.20)
    gt = TERMINAL_GROWTH
    if r - gt < 0.025:
        gt = r - 0.025

    value, flow = 0.0, fcf_ps
    for year in range(1, 6):
        # la crescita sfuma linearmente verso quella perpetua: nessuna azienda
        # cresce al ritmo di oggi per sempre
        g = g0 + (gt - g0) * (year / 5.0)
        flow *= 1 + g
        value += flow / (1 + r) ** year
    terminal = flow * (1 + gt) / (r - gt)
    value += terminal / (1 + r) ** 5
    return MethodResult(
        "dcf", "Flussi di cassa scontati", value,
        detail=f"FCF/azione {fcf_ps:.2f}, crescita {g0:.1%} verso {gt:.1%}, tasso {r:.1%}",
    )


def _method_pb(metrics: Metrics, scenario: Scenario, rate: float) -> MethodResult:
    """P/B giustificato da ROE e crescita: il metodo di riferimento per le banche."""
    label = "Valore di libro giustificato (P/B)"
    bvps = metrics.valuation.get("bvps")
    roe = metrics.quality.get("roe_avg3") or metrics.quality.get("roe")
    if bvps is None or bvps <= 0:
        return MethodResult("pb", label, None,
                            skipped_reason="patrimonio netto per azione non disponibile")
    if roe is None:
        return MethodResult("pb", label, None, skipped_reason="ROE non calcolabile")
    if roe <= 0:
        return MethodResult("pb", label, None,
                            skipped_reason="ROE negativo: il patrimonio si sta erodendo")
    g = sustainable_growth(metrics) or 0.02
    g = min(max(g + scenario.growth_shift, -0.02), PERPETUAL_GROWTH_CAP)
    r = max(rate + scenario.rate_shift, g + MIN_DISCOUNT_SPREAD)
    justified = (roe - g) / (r - g)
    note = ""
    # Secondo freno: il multiplo che il mercato ha storicamente pagato per
    # questo titolo. Evita di trasformare il ROE di un anno buono in un valore
    # permanente.
    hist_median = (metrics.multiple_history.get("pb") or {}).get("median")
    if hist_median and justified > hist_median * 1.6:
        justified = hist_median * 1.6
        note = ", limitato dal P/B storico"
    justified = min(max(justified, 0.3), 5.0)
    return MethodResult(
        "pb", label, bvps * justified,
        detail=f"patrimonio/azione {bvps:.2f} x P/B {justified:.2f} "
               f"(ROE {roe:.1%}, tasso {r:.1%}{note})",
    )


def _method_book_floor(metrics: Metrics) -> MethodResult:
    """Ultima ancora quando nessun modello regge: il patrimonio tangibile scontato.

    Non e' una valutazione del business, ma un ordine di grandezza del
    "pavimento" patrimoniale. Usato solo per le aziende in perdita.
    """
    label = "Pavimento patrimoniale (patrimonio tangibile)"
    shares = metrics.shares
    tangible = None
    if metrics.years is not None and not metrics.years.empty and "tangible_book" in metrics.years.columns:
        series = metrics.years["tangible_book"].dropna()
        tangible = float(series.iloc[-1]) if not series.empty else None
    if tangible is None:
        tangible = metrics.ttm.get("equity")
    if tangible is None or shares is None or shares <= 0 or tangible <= 0:
        return MethodResult("book_floor", label, None,
                            skipped_reason="patrimonio tangibile non disponibile o negativo")
    bvps = tangible / shares
    # 0,7x il patrimonio tangibile: lo sconto tipico a cui il mercato tratta
    # un'azienda che sta distruggendo valore.
    return MethodResult("book_floor", label, bvps * 0.7,
                        detail=f"patrimonio tangibile/azione {bvps:.2f} x 0,7 (azienda in perdita)")


# --------------------------------------------------------------------------
# pesi
# --------------------------------------------------------------------------
def _weights(metrics: Metrics) -> dict[str, float]:
    """Quanto pesa ogni metodo, in base al tipo di azienda."""
    if metrics.is_financial:
        # Per una banca EV/EBITDA e flussi di cassa non significano nulla:
        # contano il patrimonio e la redditivita' del patrimonio.
        weights = {"multiple": 0.30, "ddm": 0.25, "dcf": 0.0, "pb": 0.45, "book_floor": 0.0}
    else:
        weights = {"multiple": 0.35, "ddm": 0.20, "dcf": 0.30, "pb": 0.15, "book_floor": 0.0}

    yield_now = metrics.dividend.get("yield_current") or 0.0
    payout = metrics.health.get("payout")
    if yield_now >= 0.05 or (payout is not None and payout >= 0.65):
        # Su un titolo da reddito il dividendo e' la ragione per cui lo si tiene.
        weights["ddm"] += 0.10
        weights["multiple"] -= 0.05
        weights["dcf"] = max(0.0, weights["dcf"] - 0.05)
    elif yield_now < 0.035 and not (payout is not None and payout >= 0.55):
        # Chi reinveste non si valuta sui dividendi: il modello li sottostima.
        weights["dcf"] += weights["ddm"] * 0.6
        weights["multiple"] += weights["ddm"] * 0.4
        weights["ddm"] = 0.0

    if (metrics.quality.get("capex_intensity") or 0) > 0.12:
        # Aziende molto intensive di capitale: il flusso di cassa di un singolo
        # anno dipende dal ciclo degli investimenti, meglio pesare il patrimonio.
        weights["dcf"] = max(0.0, weights["dcf"] - 0.05)
        weights["pb"] += 0.05
    return weights


def _blend(results: list[MethodResult], weights: dict[str, float]) -> Optional[float]:
    """Media ponderata dei soli metodi utilizzabili, con pesi rinormalizzati."""
    usable = [(r, weights.get(r.key, 0.0)) for r in results if r.usable]
    usable = [(r, w) for r, w in usable if w > 0]
    if not usable:
        usable = [(r, 1.0) for r in results if r.usable]
    if not usable:
        return None
    total = sum(w for _, w in usable)
    if total <= 0:
        return None
    for result, weight in usable:
        result.weight = weight / total
    return sum(r.fair_value * w for r, w in usable) / total


# --------------------------------------------------------------------------
# ingresso pubblico
# --------------------------------------------------------------------------
def value_company(metrics: Metrics, *, risk_free: float = RISK_FREE_TH,
                  erp: float = EQUITY_RISK_PREMIUM_TH) -> Valuation:
    """Calcola la forchetta di valore e il rendimento atteso a due anni."""
    rate, beta_used = cost_of_equity(metrics.trend.get("beta"), risk_free, erp)
    valuation = Valuation(
        cost_of_equity=rate, risk_free=risk_free, equity_risk_premium=erp, beta=beta_used,
        sustainable_growth=sustainable_growth(metrics),
    )
    weights = _weights(metrics)
    builders = (_method_multiple, _method_ddm, _method_dcf, _method_pb)

    base_results = [fn(metrics, BASE, rate) for fn in builders]
    bear_results = [fn(metrics, BEAR, rate) for fn in builders]
    bull_results = [fn(metrics, BULL, rate) for fn in builders]
    if not any(r.usable for r in base_results):
        # Azienda in perdita e senza cassa: resta solo il patrimonio, dichiarando
        # apertamente che non e' una valutazione del business.
        floor = _method_book_floor(metrics)
        base_results.append(floor)
        weights["book_floor"] = 1.0
        if floor.usable:
            bear_results.append(MethodResult("book_floor", floor.label, floor.fair_value * 0.6))
            bull_results.append(MethodResult("book_floor", floor.label, floor.fair_value * 1.4))
    valuation.methods = base_results
    valuation.fair_base = _blend(base_results, weights)
    valuation.fair_bear = _blend(bear_results, weights)
    valuation.fair_bull = _blend(bull_results, weights)

    # Gli scenari devono restare ordinati anche se un metodo reagisce in modo
    # non monotono ai parametri (capita con il DDM vicino a r == g).
    bounds = sorted(v for v in (valuation.fair_bear, valuation.fair_base, valuation.fair_bull)
                    if v is not None)
    if len(bounds) == 3:
        valuation.fair_bear, valuation.fair_base, valuation.fair_bull = bounds

    price = metrics.price
    dy = metrics.dividend.get("yield_current") or 0.0
    valuation.dividend_yield = dy
    if price and price > 0:
        for label in ("bear", "base", "bull"):
            fair = getattr(valuation, f"fair_{label}")
            setattr(valuation, f"upside_{label}", (fair / price - 1.0) if fair else None)
        if valuation.upside_base is not None:
            total = valuation.upside_base + dy * HORIZON_YEARS
            valuation.expected_return_2y = total
            valuation.expected_annualized = (1 + total) ** (1 / HORIZON_YEARS) - 1 if total > -1 else None
        if valuation.fair_base:
            denominator = 1 + TARGET_TOTAL_RETURN - dy * HORIZON_YEARS
            if denominator > 0.1:
                # Con un dividendo molto alto le cedole da sole coprono
                # l'obiettivo, e la formula produce un prezzo d'ingresso sopra
                # il valore stimato: comprare sopra il valore non e' mai un
                # consiglio sensato, quindi il valore resta il tetto.
                valuation.entry_price = min(valuation.fair_base,
                                            valuation.fair_base / denominator)

    valuation.analyst_target = metrics.estimates.get("target_mean")
    valuation.analyst_upside = metrics.estimates.get("target_upside")
    if valuation.fair_base:
        valuation.dispersion = safe_div(
            (valuation.fair_bull or valuation.fair_base) - (valuation.fair_bear or valuation.fair_base),
            valuation.fair_base,
        )

    usable = valuation.usable_methods()
    # Affidabilita': quanti modelli indipendenti concordano e quanto sono
    # distanti fra loro. Serve a chi legge per sapere quanto fidarsi del numero.
    if not usable or all(m.key == "book_floor" for m in usable):
        valuation.reliability = "bassa"
    elif len(usable) >= 3 and (valuation.dispersion or 0) <= 0.55:
        valuation.reliability = "alta"
    else:
        valuation.reliability = "media"
    if usable and all(m.key == "book_floor" for m in usable):
        valuation.notes.append(
            "Nessun modello basato su utili o cassa e' applicabile: il valore indicato e' solo un "
            "riferimento patrimoniale, non una stima del valore del business."
        )
    elif not usable:
        valuation.notes.append(
            "Nessun modello di valutazione applicabile (utili e flussi di cassa negativi, "
            "patrimonio non disponibile): il giudizio si basa solo su qualita' dei conti e prezzo."
        )
    elif len(usable) == 1:
        valuation.notes.append(
            f"Un solo modello utilizzabile ({usable[0].label}): la stima di valore e' fragile."
        )
    if valuation.fair_base and price:
        spread = valuation.dispersion
        if spread is not None and spread > 0.8:
            valuation.notes.append(
                "Forchetta di valore molto ampia: le ipotesi contano piu' dei dati, "
                "prendere il valore centrale con prudenza."
            )
    return valuation
