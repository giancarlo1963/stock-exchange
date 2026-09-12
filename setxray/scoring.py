"""Dal dato al giudizio: cinque pilastri, i campanelli d'allarme, una decisione.

Il punteggio (0-100) misura la *qualita' dell'investimento*: quanto e' buona
l'azienda e quanto e' ragionevole il prezzo rispetto alla sua storia. Il
rendimento atteso a due anni, che arriva da `valuation.py`, misura invece
quanto c'e' da guadagnare. La decisione nasce dall'incrocio dei due, con i
campanelli d'allarme che possono bloccare un acquisto anche a punteggio alto.

Una scelta di fondo: niente segnali di breve periodo. L'orizzonte e' 1-2 anni,
quindi la tendenza del prezzo pesa poco (15%) e serve solo a dire se il mercato
sta confermando o smentendo la tesi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from setxray import fmt
from setxray.metrics import Metrics
from setxray.valuation import Valuation

BUY = "COMPRA"
HOLD = "MANTIENI"
SELL = "VENDI"

PILLAR_WEIGHTS: dict[str, float] = {
    "valutazione": 0.25,
    "qualita": 0.20,
    "crescita": 0.20,
    "solidita": 0.20,
    "tendenza": 0.15,
}

PILLAR_LABELS: dict[str, str] = {
    "valutazione": "Valutazione (quanto costa)",
    "qualita": "Qualita' del business",
    "crescita": "Crescita",
    "solidita": "Solidita' finanziaria",
    "tendenza": "Tendenza del prezzo",
}

PILLAR_QUESTIONS: dict[str, str] = {
    "valutazione": "Il prezzo di oggi e' basso o alto rispetto agli utili, al patrimonio e alla storia del titolo?",
    "qualita": "L'azienda guadagna bene sul capitale che impiega, e con margini stabili?",
    "crescita": "Ricavi e utili stanno crescendo, e con continuita'?",
    "solidita": "Il debito e' sostenibile? L'azienda regge un anno brutto?",
    "tendenza": "Il mercato sta confermando o smentendo la tesi negli ultimi 12 mesi?",
}


# --------------------------------------------------------------------------
# punteggio per singolo indicatore
# --------------------------------------------------------------------------
def band(value: Optional[float], points: Sequence[tuple[float, float]]) -> Optional[float]:
    """Interpolazione lineare fra soglie: da un valore a un punteggio 0-100.

    `points` va ordinato per valore crescente. Fuori dall'intervallo il
    punteggio resta quello dell'estremo piu' vicino.

    >>> band(0.10, [(0.0, 0), (0.20, 100)])
    50.0
    >>> band(-1, [(0.0, 10), (1.0, 90)])
    10.0
    """
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    if x <= points[0][0]:
        return float(points[0][1])
    if x >= points[-1][0]:
        return float(points[-1][1])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return float(y1)
            return float(y0 + (y1 - y0) * (x - x0) / (x1 - x0))
    return None


@dataclass
class Criterion:
    """Un singolo indicatore: valore, punteggio, e come va letto."""

    label: str
    value: Optional[float]
    score: Optional[float]
    weight: float = 1.0
    fmt: str = "num"  # num | pct | x | ratio
    note: str = ""

    def formatted(self) -> str:
        if self.value is None:
            return "n/d"
        if self.fmt == "pct":
            return fmt.pct(self.value)
        if self.fmt == "x":
            return fmt.mult(self.value)
        if self.fmt == "ratio":
            return fmt.ratio(self.value)
        return fmt.num(self.value)


@dataclass
class Pillar:
    key: str
    label: str
    question: str
    weight: float
    criteria: list[Criterion] = field(default_factory=list)

    @property
    def score(self) -> Optional[float]:
        """Media ponderata dei soli indicatori calcolabili."""
        usable = [(c.score, c.weight) for c in self.criteria if c.score is not None and c.weight > 0]
        if not usable:
            return None
        total = sum(w for _, w in usable)
        return sum(s * w for s, w in usable) / total if total > 0 else None

    @property
    def coverage(self) -> float:
        """Quota degli indicatori effettivamente disponibili."""
        if not self.criteria:
            return 0.0
        return sum(1 for c in self.criteria if c.score is not None) / len(self.criteria)


@dataclass
class Flag:
    severity: str  # "grave" | "attenzione"
    text: str


@dataclass
class Verdict:
    action: str  # COMPRA | MANTIENI | VENDI
    conviction: str  # "alta" | "media" | "bassa"
    headline: str
    reasons: list[str] = field(default_factory=list)
    composite: Optional[float] = None
    pillars: list[Pillar] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    expected_return_2y: Optional[float] = None
    expected_annualized: Optional[float] = None
    entry_price: Optional[float] = None
    review_triggers: list[str] = field(default_factory=list)
    position_note: str = ""
    data_quality: str = "buona"
    raw_signal: float = 0.0

    @property
    def grave_flags(self) -> list[Flag]:
        return [f for f in self.flags if f.severity == "grave"]

    @property
    def warning_flags(self) -> list[Flag]:
        return [f for f in self.flags if f.severity == "attenzione"]


# --------------------------------------------------------------------------
# i cinque pilastri
# --------------------------------------------------------------------------
def _pillar_valuation(m: Metrics) -> Pillar:
    pillar = Pillar("valutazione", PILLAR_LABELS["valutazione"], PILLAR_QUESTIONS["valutazione"],
                    PILLAR_WEIGHTS["valutazione"])
    pe_hist = m.multiple_history.get("pe") or {}
    pb_hist = m.multiple_history.get("pb") or {}
    pe = m.valuation.get("pe")
    pb = m.valuation.get("pb")

    # Rispetto alla propria storia: un percentile basso vuol dire che il titolo
    # non e' stato quasi mai cosi' economico.
    pe_pct = pe_hist.get("percentile")
    pillar.criteria.append(Criterion(
        f"P/E contro la propria media ({pe_hist.get('years', 0):.0f} anni)",
        pe_pct, None if pe_pct is None else 100.0 * (1.0 - pe_pct), weight=2.0, fmt="pct",
        note=f"mediana storica {fmt.mult(pe_hist.get('median'))}" if pe_hist else "",
    ))
    pb_pct = pb_hist.get("percentile")
    pillar.criteria.append(Criterion(
        "P/B contro la propria media", pb_pct,
        None if pb_pct is None else 100.0 * (1.0 - pb_pct),
        weight=2.0 if m.is_financial else 1.0, fmt="pct",
    ))

    # In assoluto: un P/E di 8 e' poco caro anche se il titolo e' sempre stato a 6.
    pillar.criteria.append(Criterion(
        "P/E attuale", pe,
        band(pe, [(5, 95), (8, 85), (11, 70), (14, 55), (18, 38), (25, 18), (40, 5)]),
        weight=1.5, fmt="x",
    ))
    pillar.criteria.append(Criterion(
        "P/B attuale", pb,
        band(pb, [(0.5, 92), (0.8, 82), (1.2, 68), (1.8, 52), (2.5, 38), (4.0, 18), (7.0, 5)]),
        weight=1.5 if m.is_financial else 0.8, fmt="x",
    ))
    if not m.is_financial:
        ev = m.valuation.get("ev_ebitda")
        pillar.criteria.append(Criterion(
            "EV/EBITDA", ev,
            band(ev, [(3, 92), (5, 80), (7, 65), (9, 50), (12, 32), (18, 12)]),
            weight=1.2, fmt="x",
        ))
        fcfy = m.valuation.get("fcf_yield")
        pillar.criteria.append(Criterion(
            "Rendimento del flusso di cassa libero", fcfy,
            band(fcfy, [(-0.02, 5), (0.0, 20), (0.03, 45), (0.06, 68), (0.10, 85), (0.15, 95)]),
            weight=1.5, fmt="pct",
        ))
    dy = m.dividend.get("yield_current")
    pillar.criteria.append(Criterion(
        "Rendimento da dividendo", dy,
        band(dy, [(0.0, 30), (0.02, 48), (0.035, 62), (0.05, 78), (0.07, 90), (0.12, 85)]),
        weight=1.0, fmt="pct",
        note="un rendimento molto alto puo' segnalare un dividendo a rischio",
    ))
    return pillar


def _pillar_quality(m: Metrics) -> Pillar:
    pillar = Pillar("qualita", PILLAR_LABELS["qualita"], PILLAR_QUESTIONS["qualita"],
                    PILLAR_WEIGHTS["qualita"])
    roe = m.quality.get("roe_avg3") or m.quality.get("roe")
    pillar.criteria.append(Criterion(
        "ROE (utile sul patrimonio)", roe,
        band(roe, [(-0.05, 2), (0.0, 10), (0.05, 30), (0.09, 48), (0.13, 66), (0.18, 82), (0.25, 94)]),
        weight=2.0, fmt="pct",
    ))
    if not m.is_financial:
        roic = m.quality.get("roic_avg3") or m.quality.get("roic")
        pillar.criteria.append(Criterion(
            "ROIC (utile sul capitale investito)", roic,
            band(roic, [(-0.02, 3), (0.02, 20), (0.05, 38), (0.08, 56), (0.12, 74), (0.18, 90)]),
            weight=2.0, fmt="pct",
        ))
    om = m.quality.get("operating_margin_avg3") or m.quality.get("operating_margin")
    pillar.criteria.append(Criterion(
        "Margine operativo", om,
        band(om, [(-0.03, 5), (0.02, 25), (0.06, 45), (0.11, 62), (0.18, 78), (0.30, 92)]),
        weight=1.5, fmt="pct",
    ))
    trend = m.quality.get("operating_margin_trend")
    pillar.criteria.append(Criterion(
        "Tendenza del margine operativo", trend,
        band(trend, [(-0.06, 5), (-0.03, 22), (-0.01, 42), (0.0, 55), (0.02, 72), (0.05, 90)]),
        weight=1.5, fmt="pct",
        note="differenza fra primo e ultimo esercizio disponibile",
    ))
    stability = m.quality.get("operating_margin_std")
    pillar.criteria.append(Criterion(
        "Stabilita' del margine", stability,
        None if stability is None else band(-stability, [(-0.12, 10), (-0.06, 40), (-0.03, 65), (-0.015, 82), (-0.005, 92)]),
        weight=1.0, fmt="pct",
        note="scarto quadratico medio: piu' basso, piu' prevedibile",
    ))
    conv = m.quality.get("cash_conversion")
    pillar.criteria.append(Criterion(
        "Conversione dell'utile in cassa", conv,
        band(conv, [(0.2, 8), (0.5, 28), (0.8, 52), (1.0, 70), (1.3, 88), (2.0, 92)]),
        weight=1.5, fmt="ratio",
        note="cassa generata / utile netto: sotto 1 per anni e' un segnale da approfondire",
    ))
    return pillar


def _pillar_growth(m: Metrics) -> Pillar:
    pillar = Pillar("crescita", PILLAR_LABELS["crescita"], PILLAR_QUESTIONS["crescita"],
                    PILLAR_WEIGHTS["crescita"])
    span = m.growth.get("revenue_span")
    suffix = f" ({span:.0f} anni)" if span else ""
    rev = m.growth.get("revenue_cagr")
    pillar.criteria.append(Criterion(
        f"Crescita media dei ricavi{suffix}", rev,
        band(rev, [(-0.08, 3), (-0.02, 20), (0.02, 40), (0.05, 55), (0.09, 72), (0.14, 87), (0.22, 95)]),
        weight=2.0, fmt="pct",
    ))
    eps = m.growth.get("eps_cagr")
    pillar.criteria.append(Criterion(
        f"Crescita media dell'utile per azione{suffix}", eps,
        band(eps, [(-0.10, 3), (-0.02, 20), (0.02, 40), (0.06, 58), (0.10, 74), (0.16, 88), (0.25, 96)]),
        weight=2.0, fmt="pct",
    ))
    recent = m.growth.get("revenue_ttm_vs_last_year")
    pillar.criteria.append(Criterion(
        "Ricavi ultimi 12 mesi contro ultimo bilancio", recent,
        band(recent, [(-0.12, 5), (-0.04, 25), (0.0, 45), (0.04, 62), (0.10, 80), (0.20, 93)]),
        weight=1.5, fmt="pct",
    ))
    up, total = m.growth.get("revenue_up_years"), m.growth.get("revenue_total_years")
    consistency = (up / total) if (up is not None and total) else None
    pillar.criteria.append(Criterion(
        "Continuita' della crescita", consistency,
        band(consistency, [(0.0, 5), (0.34, 30), (0.5, 50), (0.67, 70), (1.0, 92)]),
        weight=1.2, fmt="pct",
        note=f"{up} esercizi in crescita su {total}" if total else "",
    )) 
    forward = m.estimates.get("eps_growth_next_year") or m.estimates.get("growth_next_year")
    pillar.criteria.append(Criterion(
        "Crescita attesa dell'utile (prossimo anno)", forward,
        band(forward, [(-0.20, 5), (-0.05, 25), (0.0, 45), (0.06, 62), (0.12, 80), (0.25, 94)]),
        weight=1.3, fmt="pct",
        note="stime degli analisti, dove disponibili",
    ))
    return pillar


def _pillar_strength(m: Metrics) -> Pillar:
    pillar = Pillar("solidita", PILLAR_LABELS["solidita"], PILLAR_QUESTIONS["solidita"],
                    PILLAR_WEIGHTS["solidita"])
    if not m.is_financial:
        nd = m.health.get("net_debt_ebitda")
        pillar.criteria.append(Criterion(
            "Debito netto / EBITDA", nd,
            band(nd, [(-1.0, 96), (0.0, 90), (1.0, 80), (2.0, 66), (3.0, 48), (4.0, 28), (6.0, 8), (8.0, 2)]),
            weight=2.5, fmt="x",
            note="negativo significa piu' cassa che debito",
        ))
        cr = m.health.get("current_ratio")
        pillar.criteria.append(Criterion(
            "Attivo corrente / passivo corrente", cr,
            band(cr, [(0.6, 8), (0.9, 30), (1.1, 52), (1.5, 72), (2.5, 88)]),
            weight=1.2, fmt="ratio",
        ))
    cov = m.health.get("interest_coverage")
    pillar.criteria.append(Criterion(
        "Copertura degli interessi", cov,
        band(cov, [(0.5, 2), (1.0, 10), (2.0, 32), (4.0, 58), (8.0, 80), (15.0, 93)]),
        weight=2.0, fmt="x",
        note="utile operativo diviso oneri finanziari",
    ))
    eq = m.health.get("equity_ratio")
    pillar.criteria.append(Criterion(
        "Patrimonio netto / attivo", eq,
        band(eq, [(0.05, 5), (0.12, 25), (0.25, 50), (0.40, 70), (0.60, 88)]),
        weight=2.0 if m.is_financial else 1.3, fmt="pct",
    ))
    pos, tot = m.growth.get("fcf_positive_years"), m.growth.get("fcf_total_years")
    share = (pos / tot) if (pos is not None and tot) else None
    pillar.criteria.append(Criterion(
        "Esercizi con cassa libera positiva", share,
        band(share, [(0.0, 5), (0.34, 28), (0.5, 48), (0.75, 72), (1.0, 92)]),
        weight=1.5, fmt="pct",
        note=f"{pos} su {tot}" if tot else "",
    ))
    payout = m.health.get("payout")
    # Campana: non distribuire nulla e' neutro, distribuire tutto e' fragile.
    pillar.criteria.append(Criterion(
        "Quota di utili distribuita", payout,
        band(payout, [(0.0, 58), (0.25, 78), (0.45, 82), (0.65, 72), (0.85, 48), (1.0, 28), (1.4, 6)]),
        weight=1.2, fmt="pct",
    ))
    dilution = m.health.get("share_count_cagr")
    pillar.criteria.append(Criterion(
        "Variazione del numero di azioni", dilution,
        None if dilution is None else band(-dilution, [(-0.12, 5), (-0.05, 25), (-0.01, 55), (0.0, 70), (0.02, 88)]),
        weight=1.0, fmt="pct",
        note="nuove azioni diluiscono chi c'e' gia'",
    ))
    return pillar


def _pillar_trend(m: Metrics) -> Pillar:
    pillar = Pillar("tendenza", PILLAR_LABELS["tendenza"], PILLAR_QUESTIONS["tendenza"],
                    PILLAR_WEIGHTS["tendenza"])
    vs200 = m.trend.get("vs_sma200")
    pillar.criteria.append(Criterion(
        "Prezzo contro media a 200 giorni", vs200,
        band(vs200, [(-0.35, 12), (-0.18, 30), (-0.05, 48), (0.05, 62), (0.18, 75), (0.40, 82)]),
        weight=1.5, fmt="pct",
    ))
    excess = m.trend.get("excess_1y")
    pillar.criteria.append(Criterion(
        "Sovra/sotto-performance contro indice SET (12 mesi)", excess,
        band(excess, [(-0.40, 12), (-0.20, 30), (-0.05, 48), (0.05, 60), (0.20, 76), (0.45, 88)]),
        weight=1.5, fmt="pct",
    ))
    from_high = m.trend.get("from_high_52w")
    pillar.criteria.append(Criterion(
        "Distanza dal massimo a 52 settimane", from_high,
        band(from_high, [(-0.60, 18), (-0.40, 35), (-0.25, 52), (-0.12, 66), (-0.03, 76)]),
        weight=1.0, fmt="pct",
        note="su un orizzonte lungo, essere lontani dai massimi non e' per forza un male",
    ))
    six = m.trend.get("return_6m")
    pillar.criteria.append(Criterion(
        "Rendimento a 6 mesi", six,
        band(six, [(-0.35, 15), (-0.15, 35), (0.0, 52), (0.12, 68), (0.30, 82)]),
        weight=1.0, fmt="pct",
    ))
    vol = m.trend.get("volatility")
    pillar.criteria.append(Criterion(
        "Volatilita' annua", vol,
        None if vol is None else band(-vol, [(-0.70, 8), (-0.45, 32), (-0.30, 55), (-0.20, 75), (-0.13, 90)]),
        weight=1.0, fmt="pct",
        note="quanto oscilla il prezzo: alta volatilita' richiede posizioni piu' piccole",
    ))
    return pillar


# --------------------------------------------------------------------------
# campanelli d'allarme
# --------------------------------------------------------------------------
def detect_flags(m: Metrics, v: Valuation) -> list[Flag]:
    """I fatti che, da soli, possono cambiare la decisione."""
    flags: list[Flag] = []
    g, h, q, t, d = m.growth, m.health, m.quality, m.trend, m.dividend

    equity = h.get("equity")
    if equity is not None and equity <= 0:
        flags.append(Flag("grave", "Patrimonio netto negativo: le perdite hanno eroso il capitale."))

    nd = h.get("net_debt_ebitda")
    if nd is not None and not m.is_financial:
        if nd > 6:
            flags.append(Flag("grave", f"Debito netto pari a {fmt.num(nd, 1)} volte l'EBITDA: struttura finanziaria fragile."))
        elif nd > 4:
            flags.append(Flag("attenzione", f"Debito netto a {fmt.mult(nd)} l'EBITDA: margine di manovra ridotto."))

    cov = h.get("interest_coverage")
    if cov is not None:
        if cov < 0:
            flags.append(Flag("grave", "Utile operativo negativo: gli oneri finanziari non sono coperti dall'attivita'."))
        elif cov < 1.2:
            flags.append(Flag("grave", f"L'utile operativo copre gli interessi solo {fmt.num(cov, 1)} volte: rischio sui pagamenti del debito."))
        elif cov < 2.5:
            flags.append(Flag("attenzione", f"Copertura degli interessi bassa ({fmt.mult(cov)})."))

    loss_years = g.get("loss_years")
    net_ttm = m.ttm.get("net_income")
    if loss_years is not None and loss_years >= 2:
        flags.append(Flag("grave", f"{loss_years} esercizi in perdita negli ultimi anni disponibili."))
    elif net_ttm is not None and net_ttm < 0:
        flags.append(Flag("grave", "Perdita negli ultimi dodici mesi."))

    declines = g.get("revenue_consecutive_declines")
    if declines is not None and declines >= 3:
        flags.append(Flag("grave", f"Ricavi in calo per {declines} esercizi consecutivi."))
    elif declines == 2:
        flags.append(Flag("attenzione", "Ricavi in calo per due esercizi consecutivi."))

    fcf = h.get("fcf_ttm")
    if fcf is not None and fcf < 0:
        severity = "grave" if (nd is not None and nd > 3) else "attenzione"
        flags.append(Flag(severity, "Flusso di cassa libero negativo negli ultimi dodici mesi."))

    payout = h.get("payout")
    eps_growth = g.get("eps_last_yoy")
    if payout is not None:
        if payout > 1.2 and (eps_growth is None or eps_growth < 0):
            flags.append(Flag("grave", f"Dividendo pari al {fmt.pct(payout, 0)} degli utili con utili in calo: taglio probabile."))
        elif payout > 0.9:
            flags.append(Flag("attenzione", f"Dividendo pari al {fmt.pct(payout, 0)} degli utili: poco margine se gli utili scendono."))

    dilution = h.get("share_count_cagr")
    if dilution is not None and dilution > 0.10:
        flags.append(Flag("grave", f"Numero di azioni in crescita del {fmt.pct(dilution, 0)} all'anno: forte diluizione."))
    elif dilution is not None and dilution > 0.04:
        flags.append(Flag("attenzione", f"Diluizione del {fmt.pct(dilution)} all'anno."))

    cr = h.get("current_ratio")
    if cr is not None and cr < 0.9 and not m.is_financial:
        flags.append(Flag("attenzione", f"Attivo corrente inferiore al passivo corrente ({fmt.ratio(cr)}): tensione di liquidita'."))

    if d.get("cuts") and d["cuts"] >= 1 and (d.get("consecutive_no_cut") or 0) < 2:
        flags.append(Flag("attenzione", "Dividendo tagliato in passato di recente: non dare per scontata la continuita'."))

    pe_pct = (m.multiple_history.get("pe") or {}).get("percentile")
    if pe_pct is not None and pe_pct >= 0.90:
        flags.append(Flag("attenzione", "Il titolo non e' quasi mai stato cosi' caro rispetto ai propri utili."))

    dd = t.get("max_drawdown_5y")
    if dd is not None and dd < -0.60:
        flags.append(Flag("attenzione", f"Negli ultimi 5 anni ha perso fino al {fmt.pct(abs(dd), 0)} dai massimi: titolo volatile."))

    margin_trend = q.get("operating_margin_trend")
    if margin_trend is not None and margin_trend < -0.05:
        flags.append(Flag("attenzione", f"Margine operativo in calo di {fmt.num(abs(margin_trend) * 100, 1)} punti percentuali nel periodo osservato."))

    turnover = t.get("avg_turnover_60d")
    if turnover is not None and turnover < 5_000_000:  # ~5 milioni di baht al giorno
        flags.append(Flag("attenzione", "Scambi giornalieri molto bassi: entrare e uscire puo' essere costoso."))

    if v.reliability == "bassa":
        flags.append(Flag("attenzione", "Stima di valore poco affidabile: pochi modelli applicabili o ipotesi molto divergenti."))
    return flags


# --------------------------------------------------------------------------
# decisione
# --------------------------------------------------------------------------
def _value_signal(v: Valuation) -> tuple[float, str]:
    """Quanto c'e' da guadagnare, secondo la forchetta di valore."""
    expected = v.expected_return_2y
    if expected is None:
        upside = v.analyst_upside
        if upside is None:
            return 0.0, "Nessuna stima di valore disponibile: il prezzo non si puo' confrontare con niente."
        signal = max(-1.0, min(1.0, upside / 0.25))
        return signal, f"Nessun modello applicabile: si usa solo il target medio degli analisti ({fmt.pct(upside, 0, sign=True)})."

    if expected >= 0.40:
        signal, text = 2.0, f"Rendimento atteso a 2 anni molto alto ({fmt.pct(expected, 0, sign=True)})."
    elif expected >= 0.20:
        signal, text = 1.5, f"Rendimento atteso a 2 anni interessante ({fmt.pct(expected, 0, sign=True)})."
    elif expected >= 0.08:
        signal, text = 0.5, f"Rendimento atteso a 2 anni modesto ({fmt.pct(expected, 0, sign=True)})."
    elif expected >= -0.08:
        signal, text = 0.0, f"Prezzo in linea con il valore stimato ({fmt.pct(expected, 0, sign=True)} a 2 anni)."
    elif expected >= -0.25:
        signal, text = -1.5, f"Prezzo sopra il valore stimato ({fmt.pct(expected, 0, sign=True)} a 2 anni)."
    else:
        signal, text = -2.0, f"Prezzo molto sopra il valore stimato ({fmt.pct(expected, 0, sign=True)} a 2 anni)."

    usable = v.usable_methods()
    if usable and all(mth.key == "book_floor" for mth in usable):
        # Su un'azienda in perdita lo sconto sul patrimonio non e' un'occasione:
        # il patrimonio stesso si sta consumando.
        signal = min(signal, 0.5)
        return signal, (
            f"Il prezzo e' sotto il riferimento patrimoniale ({fmt.pct(expected, 0, sign=True)}), ma su un'azienda "
            "in perdita il patrimonio si consuma: non e' uno sconto su cui contare."
        )
    if v.reliability == "bassa":
        # Con una stima fragile non si prende una posizione forte solo sul prezzo.
        signal = max(-1.0, min(1.0, signal))
        text += " Stima poco affidabile, peso ridotto."
    return signal, text


def _quality_signal(composite: Optional[float]) -> tuple[float, str]:
    if composite is None:
        return 0.0, "Punteggio complessivo non calcolabile per mancanza di dati."
    if composite >= 68:
        return 2.0, f"Azienda solida su tutti i fronti (punteggio {composite:.0f}/100)."
    if composite >= 58:
        return 1.0, f"Azienda nel complesso buona (punteggio {composite:.0f}/100)."
    if composite >= 46:
        return 0.0, f"Quadro misto (punteggio {composite:.0f}/100)."
    if composite >= 35:
        return -1.0, f"Piu' debolezze che punti di forza (punteggio {composite:.0f}/100)."
    return -2.0, f"Quadro fondamentale debole (punteggio {composite:.0f}/100)."


def _composite(pillars: list[Pillar]) -> Optional[float]:
    """Punteggio unico 0-100, con i pesi dei pilastri senza dati redistribuiti."""
    usable = [(p.score, p.weight) for p in pillars if p.score is not None]
    if not usable:
        return None
    total = sum(w for _, w in usable)
    return sum(s * w for s, w in usable) / total if total > 0 else None


def _data_quality(m: Metrics, pillars: list[Pillar]) -> str:
    if m.n_years == 0:
        return "insufficiente"
    coverage = sum(p.coverage for p in pillars) / len(pillars) if pillars else 0.0
    if m.n_years >= 4 and coverage >= 0.8:
        return "buona"
    if m.n_years >= 3 and coverage >= 0.6:
        return "discreta"
    return "limitata"


def _review_triggers(m: Metrics, v: Valuation, action: str) -> list[str]:
    """Cosa deve accadere per rimettere in discussione la decisione."""
    out: list[str] = []
    currency = m.currency
    if v.fair_base and m.price:
        if action == BUY and v.entry_price:
            out.append(f"Compra sotto {fmt.money(v.entry_price, currency)}: sopra questo prezzo il margine di sicurezza si assottiglia.")
        if action in (BUY, HOLD) and v.fair_bull:
            out.append(f"Sopra {fmt.money(v.fair_bull, currency)} il titolo esce dalla forchetta di valore: valuta di alleggerire.")
        if action == SELL and v.fair_bear:
            out.append(f"Sotto {fmt.money(v.fair_bear, currency)} il prezzo torna interessante anche nello scenario pessimistico.")
    om = m.quality.get("operating_margin")
    if om is not None:
        out.append(f"Margine operativo sotto il {fmt.pct(max(0.0, om - 0.02))} per due trimestri: tesi da rivedere.")
    nd = m.health.get("net_debt_ebitda")
    if nd is not None and not m.is_financial:
        out.append(f"Debito netto/EBITDA oltre {fmt.mult(max(1.0, nd + 1))}: la solidita' peggiora.")
    rev = m.growth.get("revenue_cagr")
    if rev is not None and rev > 0:
        out.append("Due trimestri consecutivi di ricavi in calo anno su anno: la crescita si e' fermata.")
    if (m.dividend.get("yield_current") or 0) >= 0.04:
        out.append("Taglio del dividendo: per un titolo da reddito e' il segnale piu' importante.")
    out.append("Rivedi comunque i conti a ogni bilancio annuale e semestrale.")
    return out[:6]


def _position_note(action: str, conviction: str, m: Metrics, flags: list[Flag]) -> str:
    vol = m.trend.get("volatility")
    grave = sum(1 for f in flags if f.severity == "grave")
    if action == SELL:
        return ("Non aprire nuove posizioni. Se il titolo e' gia' in portafoglio, pianifica l'uscita "
                "in piu' tranche invece di vendere tutto in un giorno.")
    if action == HOLD:
        return ("Mantieni la posizione esistente senza aumentarla. Se non sei ancora investito, "
                "aspetta un prezzo migliore o un miglioramento dei conti.")
    size = "una posizione piena" if conviction == "alta" else "una posizione parziale"
    extra = ""
    if vol is not None and vol > 0.40:
        extra = " Il titolo e' molto volatile: riduci la dimensione rispetto a quella che useresti di norma."
    elif grave:
        extra = " C'e' un campanello d'allarme aperto: tienine conto nella dimensione."
    return (f"Puoi costruire {size}, meglio in 2-3 ingressi distribuiti su qualche mese per non "
            f"dipendere dal prezzo di un singolo giorno.{extra}")


def evaluate(m: Metrics, v: Valuation) -> Verdict:
    """Incrocia punteggio, rendimento atteso e campanelli d'allarme."""
    pillars = [_pillar_valuation(m), _pillar_quality(m), _pillar_growth(m),
               _pillar_strength(m), _pillar_trend(m)]
    composite = _composite(pillars)
    flags = detect_flags(m, v)

    value_sig, value_reason = _value_signal(v)
    quality_sig, quality_reason = _quality_signal(composite)
    grave = [f for f in flags if f.severity == "grave"]
    warnings = [f for f in flags if f.severity == "attenzione"]

    penalty = 2.0 * len(grave) + min(1.5, 0.3 * len(warnings))
    # Il segnale resta in una scala leggibile: oltre -6 o +6 non cambia la
    # decisione, cambierebbe solo l'apparenza del numero.
    raw = max(-6.0, min(6.0, value_sig + quality_sig - penalty))

    if raw >= 2.0:
        action = BUY
    elif raw > -1.0:
        action = HOLD
    else:
        action = SELL

    # Vincoli che prevalgono sul punteggio: nessun conto conveniente giustifica
    # un bilancio che non regge.
    override: Optional[str] = None
    if len(grave) >= 2:
        action, override = SELL, f"{len(grave)} problemi gravi sui conti: prevalgono su qualunque sconto di prezzo."
    elif len(grave) == 1 and action == BUY:
        action, override = HOLD, "Un problema grave sui conti impedisce di consigliare un acquisto."
    if m.n_years == 0 and action == BUY:
        action, override = HOLD, "Senza bilanci non c'e' base sufficiente per consigliare un acquisto."

    magnitude = abs(raw)
    conviction = "alta" if magnitude >= 3.0 else "media" if magnitude >= 1.5 else "bassa"
    if override:
        conviction = "alta" if len(grave) >= 2 else "media"

    reasons = [quality_reason, value_reason]
    if override:
        reasons.insert(0, override)
    if grave:
        reasons.append("Problemi gravi: " + " ".join(f.text for f in grave[:3]))
    elif warnings:
        reasons.append("Punti di attenzione: " + " ".join(f.text for f in warnings[:2]))

    best = max((p for p in pillars if p.score is not None), key=lambda p: p.score, default=None)
    worst = min((p for p in pillars if p.score is not None), key=lambda p: p.score, default=None)
    if best is not None and worst is not None and best.key != worst.key:
        reasons.append(f"Punto di forza: {best.label.lower()} ({best.score:.0f}/100). "
                       f"Punto debole: {worst.label.lower()} ({worst.score:.0f}/100).")

    headline = {
        BUY: f"COMPRA — convinzione {conviction}",
        HOLD: f"MANTIENI — convinzione {conviction}",
        SELL: f"VENDI / RIDUCI — convinzione {conviction}",
    }[action]

    return Verdict(
        action=action, conviction=conviction, headline=headline, reasons=reasons,
        composite=composite, pillars=pillars, flags=flags,
        expected_return_2y=v.expected_return_2y, expected_annualized=v.expected_annualized,
        entry_price=v.entry_price,
        review_triggers=_review_triggers(m, v, action),
        position_note=_position_note(action, conviction, m, flags),
        data_quality=_data_quality(m, pillars), raw_signal=raw,
    )
