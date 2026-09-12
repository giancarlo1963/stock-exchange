"""Dieci anni di dividendi: cosa e' stato pagato, quanto e' solido, cosa aspettarsi.

Il cuore dello strumento. Le domande a cui risponde, in ordine:

1. **Quanto ha pagato?** Dividendo per azione anno per anno, crescita media,
   tagli, anni saltati, regolarita' degli stacchi.
2. **Quanto contava il dividendo nel rendimento?** Scomposizione del rendimento
   totale a dieci anni fra prezzo e cedole reinvestite.
3. **Il prezzo di oggi e' generoso?** Rendimento attuale confrontato con la
   propria storia, non con una media di mercato.
4. **Il dividendo regge?** Un punteggio di solidita' costruito da fattori
   visibili uno per uno: copertura con gli utili, copertura con la cassa,
   debito, andamento degli utili, storia dei tagli.
5. **Cosa pagherà nei prossimi due anni?** Previsione da tre metodi
   indipendenti, con una forchetta e uno scenario di taglio quando serve.
6. **Questo segnale ha mai funzionato su questo titolo?** Verifica retrospettiva
   della regola "compra quando il rendimento e' alto rispetto alla sua storia".

Una precisazione sull'onesta' del modello: il punteggio di solidita' e il
rischio di taglio sono **regole trasparenti**, con i punti di ogni fattore
scritti in chiaro, non un modello statistico addestrato su una base storica di
tagli. Non chiamiamolo piu' di quello che e'. La verifica retrospettiva del
punto 6, invece, e' misurata davvero sui dati del titolo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from setxray.metrics import Metrics, cagr, safe_div
from setxray.sources.base import DividendSet

ANNI_STORIA = 10
# Rendimento obiettivo che rende sensato comprare un titolo da reddito, oltre
# al quale il prezzo non offre piu' un margine: usato per il prezzo d'ingresso.
RENDIMENTO_MIN = 0.02
RENDIMENTO_MAX = 0.12
# Margine richiesto sul rendimento obiettivo per parlare di prezzo d'ingresso.
MARGINE_SICUREZZA = 0.20


# ==========================================================================
# contenitori
# ==========================================================================
@dataclass
class Factor:
    """Un fattore del punteggio, con il suo contributo in chiaro."""

    label: str
    value: Optional[float]
    points: float
    explanation: str
    fmt: str = "pct"


@dataclass
class DividendSafety:
    score: float
    band: str                                   # "solid" | "watch closely" | "at risk"
    factors: list[Factor] = field(default_factory=list)
    hard_triggers: list[str] = field(default_factory=list)
    cut_risk_band: str = "medium"               # "low" | "medium" | "high"
    cut_risk_score: float = 50.0


@dataclass
class ForecastMethod:
    label: str
    value: Optional[float]
    weight: float = 0.0
    detail: str = ""
    skipped_reason: Optional[str] = None

    @property
    def usable(self) -> bool:
        return self.value is not None and self.value >= 0


@dataclass
class DividendForecast:
    year1_low: Optional[float] = None
    year1_base: Optional[float] = None
    year1_high: Optional[float] = None
    year2_low: Optional[float] = None
    year2_base: Optional[float] = None
    year2_high: Optional[float] = None
    growth: Optional[float] = None
    methods: list[ForecastMethod] = field(default_factory=list)
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.year1_base is not None

    @property
    def two_year_total(self) -> Optional[float]:
        if self.year1_base is None or self.year2_base is None:
            return None
        return self.year1_base + self.year2_base


@dataclass
class BacktestBucket:
    label: str
    observations: int
    avg_return_2y: Optional[float]
    hit_rate: Optional[float]
    median_return_2y: Optional[float] = None


@dataclass
class YieldBacktest:
    buckets: list[BacktestBucket] = field(default_factory=list)
    observations: int = 0
    years_covered: float = 0.0
    usable: bool = False
    note: str = ""
    separation: Optional[float] = None   # differenza fra il gruppo "alto" e "basso"


@dataclass
class DividendSignal:
    action: str
    conviction: str
    headline: str
    reasons: list[str] = field(default_factory=list)
    fair_price: Optional[float] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    expected_return_2y: Optional[float] = None
    expected_annualized: Optional[float] = None
    income_component: Optional[float] = None
    price_component: Optional[float] = None
    target_yield: Optional[float] = None


@dataclass
class DividendAnalysis:
    symbol: str
    currency: str = "THB"
    price: Optional[float] = None
    source: Optional[DividendSet] = None
    years: pd.DataFrame = field(default_factory=pd.DataFrame)
    payments: Optional[pd.Series] = None
    daily_yield: Optional[pd.Series] = None
    span_years: float = 0.0
    cadence: Optional[int] = None
    growth: dict = field(default_factory=dict)
    streaks: dict = field(default_factory=dict)
    yield_stats: dict = field(default_factory=dict)
    total_return: dict = field(default_factory=dict)
    yield_on_cost: dict = field(default_factory=dict)
    safety: Optional[DividendSafety] = None
    forecast: Optional[DividendForecast] = None
    backtest: Optional[YieldBacktest] = None
    signal: Optional[DividendSignal] = None
    notes: list[str] = field(default_factory=list)

    @property
    def pays_dividends(self) -> bool:
        return self.payments is not None and not self.payments.empty

    def complete_years(self) -> pd.DataFrame:
        """Solo gli anni con storia intera: l'anno in corso falsa ogni media."""
        if self.years is None or self.years.empty or "completo" not in self.years:
            return pd.DataFrame()
        return self.years[self.years["completo"]]


# ==========================================================================
# 1. la tabella per anno
# ==========================================================================
def _build_years(payments: pd.Series, prices: Optional[pd.DataFrame],
                 metrics: Metrics) -> pd.DataFrame:
    """Una riga per anno solare: dividendo, rendimento, copertura."""
    anno_corrente = pd.Timestamp.now().year
    primo = int(payments.index[0].year)
    ultimo = int(max(payments.index[-1].year, anno_corrente))
    anni = list(range(max(primo, ultimo - ANNI_STORIA), ultimo + 1))

    per_anno = payments.groupby(payments.index.year).sum()
    conteggi = payments.groupby(payments.index.year).count()

    prezzo_medio: dict[int, float] = {}
    prezzo_fine: dict[int, float] = {}
    if prices is not None and not prices.empty:
        chiusure = prices["Close"].dropna()
        prezzo_medio = chiusure.groupby(chiusure.index.year).mean().to_dict()
        prezzo_fine = chiusure.groupby(chiusure.index.year).last().to_dict()

    # Utile e cassa per azione dell'esercizio che chiude in quell'anno.
    eps_per_anno: dict[int, float] = {}
    fcf_ps_per_anno: dict[int, float] = {}
    if metrics.years is not None and not metrics.years.empty:
        for data, riga in metrics.years.iterrows():
            anno = int(data.year)
            if "eps" in riga and pd.notna(riga.get("eps")):
                eps_per_anno[anno] = float(riga["eps"])
            azioni = riga.get("shares")
            fcf = riga.get("fcf")
            if pd.notna(fcf) and pd.notna(azioni) and azioni:
                fcf_ps_per_anno[anno] = float(fcf) / float(azioni)

    # Il primo anno della serie e' incompleto se la storia comincia a meta'
    # anno: non sapremmo se un primo stacco e' stato perso o non c'e' stato.
    inizio_storia = payments.index[0]
    primo_anno_parziale = inizio_storia.month > 2

    righe = []
    for anno in anni:
        dps = float(per_anno.get(anno, 0.0))
        completo = anno < anno_corrente and not (anno == primo and primo_anno_parziale)
        medio = prezzo_medio.get(anno)
        eps = eps_per_anno.get(anno)
        fcf_ps = fcf_ps_per_anno.get(anno)
        righe.append({
            "anno": anno,
            "dps": dps,
            "stacchi": int(conteggi.get(anno, 0)),
            "prezzo_medio": medio,
            "prezzo_fine": prezzo_fine.get(anno),
            "rendimento": safe_div(dps, medio),
            "eps": eps,
            "payout": safe_div(dps, eps) if (eps or 0) > 0 else None,
            "fcf_per_azione": fcf_ps,
            "copertura_cassa": safe_div(fcf_ps, dps) if dps > 0 else None,
            "completo": completo,
        })
    tabella = pd.DataFrame(righe).set_index("anno")
    tabella["variazione"] = tabella["dps"].pct_change().replace(
        [np.inf, -np.inf], np.nan)
    return tabella


def _cadence(payments: pd.Series) -> Optional[int]:
    """Quanti stacchi all'anno, secondo gli ultimi anni completi."""
    anno_corrente = pd.Timestamp.now().year
    conteggi = payments.groupby(payments.index.year).count()
    completi = conteggi[conteggi.index < anno_corrente]
    if completi.empty:
        return None
    recenti = completi.iloc[-4:]
    return int(round(float(recenti.median())))


def _indicated_dps(payments: pd.Series, cadence: Optional[int]) -> Optional[float]:
    """Dividendo corrente su base annua: gli ultimi `cadence` stacchi.

    Sommare i dodici mesi esatti e' fragile: basta uno stacco spostato di
    pochi giorni per contarne due o nessuno.
    """
    if payments is None or payments.empty:
        return None
    if cadence and cadence >= 1:
        return float(payments.iloc[-int(cadence):].sum())
    finestra = payments[payments.index > payments.index[-1] - pd.Timedelta(days=365)]
    return float(finestra.sum()) if not finestra.empty else None


# ==========================================================================
# 2. serie giornaliera del rendimento
# ==========================================================================
def _indicated_dividend_series(payments: pd.Series, index: pd.DatetimeIndex,
                               cadence: int) -> pd.Series:
    """Dividendo su base annua, giorno per giorno: gli ultimi `cadence` stacchi.

    Perche' non una finestra di 365 giorni. Con stacchi a date quasi fisse, una
    finestra di dodici mesi ne racchiude ora due e ora uno a seconda del giorno
    (gli anni bisestili bastano a spostare il confine), e la serie si riempie di
    punte verticali che non corrispondono a niente di reale.

    C'e' una ragione piu' importante della pulizia del grafico: il rendimento di
    *oggi* e' calcolato sugli ultimi `cadence` stacchi. Se la serie storica
    usasse un criterio diverso, il percentile confronterebbe due misure diverse
    e direbbe una cosa falsa su quanto il prezzo di oggi sia generoso.
    """
    cadenza = max(1, int(cadence))
    somme = payments.sort_index().rolling(cadenza).sum().dropna()
    if somme.empty:
        return pd.Series(dtype="float64", index=index[:0])
    # Ogni valore resta valido dal suo stacco fino al successivo.
    return somme.reindex(index, method="ffill").dropna()


def _daily_yield(payments: pd.Series, prices: Optional[pd.DataFrame],
                 cadence: Optional[int]) -> Optional[pd.Series]:
    """Serie giornaliera del rendimento: dieci anni di borsa, oltre duemila
    osservazioni, abbastanza per un percentile e per la verifica retrospettiva."""
    if prices is None or prices.empty or payments is None or payments.empty:
        return None
    chiusure = prices["Close"].dropna()
    if chiusure.empty:
        return None
    annualizzato = _indicated_dividend_series(payments, chiusure.index, cadence or 1)
    if annualizzato.empty:
        return None
    rendimento = (annualizzato / chiusure).replace([np.inf, -np.inf], np.nan).dropna()
    rendimento = rendimento[(rendimento > 0) & (rendimento < 0.60)]
    return rendimento if len(rendimento) >= 120 else None


# ==========================================================================
# 3. crescita, tagli, regolarita'
# ==========================================================================
def _consecutive_changes(completi: pd.DataFrame) -> pd.Series:
    """Variazioni anno su anno fra anni *solari consecutivi*, entrambi paganti.

    Un pagatore irregolare che salta il 2020 e il 2021 non ha "tagliato" il
    dividendo passando dal 2019 al 2022: confrontare anni non adiacenti
    produrrebbe tagli e aumenti che non sono mai avvenuti.
    """
    variazioni = {}
    for anno in completi.index:
        precedente = anno - 1
        if precedente not in completi.index:
            continue
        prima = float(completi.loc[precedente, "dps"])
        dopo = float(completi.loc[anno, "dps"])
        if prima > 0 and dopo > 0:
            variazioni[int(anno)] = dopo / prima - 1.0
    return pd.Series(variazioni, dtype="float64").sort_index()


def _growth(tabella: pd.DataFrame) -> dict:
    completi = tabella[tabella["completo"]]
    paganti = completi[completi["dps"] > 0]
    out: dict = {"anni_completi": int(len(completi)),
                 "irregolare": bool((completi["dps"] <= 0).any())}
    if len(paganti) >= 2:
        for orizzonte in (3, 5, 10):
            # Finestra di anni *solari*, non di soli anni paganti: su dieci
            # anni la crescita media va misurata su dieci anni.
            fine = int(completi.index[-1])
            inizio = fine - orizzonte
            finestra = completi[(completi.index >= inizio) & (completi.index <= fine)]
            if len(finestra) < 2:
                out[f"cagr_{orizzonte}y"] = None
                continue
            if (finestra["dps"] <= 0).any():
                # Con un anno a zero dentro la finestra un tasso di crescita
                # composto non ha significato: meglio dichiararlo assente.
                out[f"cagr_{orizzonte}y"] = None
                out[f"cagr_{orizzonte}y_bloccato"] = "anni senza dividendo nella finestra"
                continue
            anni = float(finestra.index[-1] - finestra.index[0])
            out[f"cagr_{orizzonte}y"] = cagr(
                float(finestra["dps"].iloc[0]), float(finestra["dps"].iloc[-1]), anni)
            out[f"cagr_{orizzonte}y_span"] = anni
        variazioni = _consecutive_changes(completi)
        out["volatilita"] = float(variazioni.std()) if len(variazioni) >= 3 else None
        out["anni_in_crescita"] = int((variazioni > 0.02).sum())
        out["anni_in_calo"] = int((variazioni < -0.02).sum())
        out["anni_stabili"] = int(len(variazioni)) - out["anni_in_crescita"] - out["anni_in_calo"]
        out["ultima_variazione"] = float(variazioni.iloc[-1]) if len(variazioni) else None
    else:
        for orizzonte in (3, 5, 10):
            out[f"cagr_{orizzonte}y"] = None
    return out


def _streaks(tabella: pd.DataFrame) -> dict:
    completi = tabella[tabella["completo"]]
    out: dict = {}
    if completi.empty:
        return out
    out["anni_osservati"] = int(len(completi))
    out["anni_pagati"] = int((completi["dps"] > 0).sum())
    out["anni_saltati"] = int((completi["dps"] <= 0).sum())

    variazioni = _consecutive_changes(completi)
    tagli = variazioni[variazioni < -0.02]
    out["tagli"] = int(len(tagli))
    out["taglio_massimo"] = float(tagli.min()) if len(tagli) else None
    out["anno_ultimo_taglio"] = int(tagli.index[-1]) if len(tagli) else None
    out["anni_dall_ultimo_taglio"] = (
        int(completi.index[-1] - tagli.index[-1]) if len(tagli) else out["anni_osservati"])

    # Aumenti consecutivi, contati dall'ultimo anno completo a ritroso.
    consecutivi = 0
    for valore in reversed(list(variazioni.values)):
        if valore > 0.02:
            consecutivi += 1
        else:
            break
    out["aumenti_consecutivi"] = consecutivi

    # Anni consecutivi senza interruzione del pagamento.
    senza_interruzioni = 0
    for dps in reversed(list(completi["dps"].values)):
        if dps > 0:
            senza_interruzioni += 1
        else:
            break
    out["anni_consecutivi_pagati"] = senza_interruzioni
    return out


# ==========================================================================
# 4. rendimento: adesso contro la propria storia
# ==========================================================================
def _yield_stats(tabella: pd.DataFrame, daily: Optional[pd.Series],
                 dps_indicato: Optional[float], prezzo: Optional[float]) -> dict:
    out: dict = {"attuale": safe_div(dps_indicato, prezzo)}
    # Preferiamo la serie giornaliera: la media annuale su dieci punti e'
    # troppo grossolana per un percentile.
    base = daily if daily is not None else (
        tabella[tabella["completo"]]["rendimento"].dropna() if not tabella.empty else None)
    if base is None or len(base) < 4:
        return out
    pulita = pd.Series(base).dropna()
    pulita = pulita[pulita > 0]
    if len(pulita) < 4:
        return out
    out["mediana"] = float(pulita.median())
    out["p25"] = float(pulita.quantile(0.25))
    out["p75"] = float(pulita.quantile(0.75))
    out["minimo"] = float(pulita.min())
    out["massimo"] = float(pulita.max())
    out["osservazioni"] = int(len(pulita))
    out["base"] = "giornaliera" if daily is not None else "media annuale"
    attuale = out.get("attuale")
    if attuale:
        out["percentile"] = float((pulita <= attuale).mean())
        out["contro_mediana"] = attuale / out["mediana"] - 1.0 if out["mediana"] else None
    return out


# ==========================================================================
# 5. quanto del rendimento e' venuto dai dividendi
# ==========================================================================
def _total_return(payments: pd.Series, prices: Optional[pd.DataFrame],
                  anni: int = ANNI_STORIA) -> dict:
    """Scompone il rendimento fra prezzo e cedole reinvestite.

    E' il numero che decide se un titolo da reddito ha mantenuto la promessa:
    un prezzo fermo da dieci anni con un 6% annuo incassato non e' un
    investimento fallito.
    """
    out: dict = {}
    if prices is None or prices.empty:
        return out
    chiusure = prices["Close"].dropna()
    if len(chiusure) < 200:
        return out
    inizio = chiusure.index[-1] - pd.Timedelta(days=int(365.25 * anni))
    finestra = chiusure[chiusure.index >= inizio]
    if len(finestra) < 200:
        finestra = chiusure
    primo, ultimo = float(finestra.iloc[0]), float(finestra.iloc[-1])
    durata = (finestra.index[-1] - finestra.index[0]).days / 365.25
    out["anni"] = durata
    out["solo_prezzo"] = primo and (ultimo / primo - 1.0)

    # Reinvestimento: ogni stacco ricompra azioni al prezzo di quel giorno.
    quote = 1.0
    incassato = 0.0
    nel_periodo = payments[(payments.index >= finestra.index[0]) & (payments.index <= finestra.index[-1])]
    for data, importo in nel_periodo.items():
        successivi = finestra.index[finestra.index >= data]
        if not len(successivi):
            continue
        prezzo_stacco = float(finestra.loc[successivi[0]])
        if prezzo_stacco <= 0:
            continue
        incassato += quote * float(importo)
        quote += quote * float(importo) / prezzo_stacco
    out["dividendi_incassati_per_azione"] = incassato
    out["totale_reinvestito"] = (quote * ultimo / primo - 1.0) if primo else None
    senza = out.get("solo_prezzo")
    totale = out.get("totale_reinvestito")
    if senza is not None and totale is not None:
        out["contributo_dividendi"] = totale - senza
        out["quota_dividendi"] = (
            (totale - senza) / totale if totale and abs(totale) > 1e-9 else None)
    if durata > 0 and totale is not None and totale > -1:
        out["annualizzato"] = (1 + totale) ** (1 / durata) - 1
    if durata > 0 and senza is not None and senza > -1:
        out["annualizzato_solo_prezzo"] = (1 + senza) ** (1 / durata) - 1
    return out


def _yield_on_cost(prices: Optional[pd.DataFrame], dps_indicato: Optional[float]) -> dict:
    """Rendimento sul prezzo di acquisto, per chi era entrato anni fa."""
    out: dict = {}
    if prices is None or prices.empty or not dps_indicato:
        return out
    chiusure = prices["Close"].dropna()
    for anni in (5, 10):
        soglia = chiusure.index[-1] - pd.Timedelta(days=int(365.25 * anni))
        precedenti = chiusure[chiusure.index <= soglia]
        if precedenti.empty:
            continue
        out[f"{anni}y"] = safe_div(dps_indicato, float(precedenti.iloc[-1]))
        out[f"prezzo_{anni}y"] = float(precedenti.iloc[-1])
    return out


# ==========================================================================
# 6. solidita' del dividendo
# ==========================================================================
def _band_from_points(value: Optional[float], soglie: tuple[tuple[float, float, str], ...],
                      default_points: float, default_text: str) -> tuple[float, str]:
    """Associa a un valore i punti e la spiegazione della fascia in cui cade."""
    if value is None:
        return default_points, default_text
    for limite, punti, testo in soglie:
        if value < limite:
            return punti, testo
    limite, punti, testo = soglie[-1]
    return punti, testo


def _safety(tabella: pd.DataFrame, streaks: dict, growth: dict, metrics: Metrics,
            dps_indicato: Optional[float], yield_stats: dict) -> DividendSafety:
    """Punteggio 0-100 costruito da fattori, ognuno con i suoi punti in chiaro.

    E' una regola, non un modello addestrato: i punti sono scelti da noi in
    base a come si valuta di solito la sostenibilita' di un dividendo. Il
    vantaggio e' che l'utente puo' vedere esattamente da dove viene il numero
    e non essere d'accordo su un singolo fattore.
    """
    fattori: list[Factor] = []
    punteggio = 50.0
    completi = tabella[tabella["completo"]] if not tabella.empty else pd.DataFrame()

    def mediana(colonna: str, n: int = 3) -> Optional[float]:
        if completi.empty or colonna not in completi:
            return None
        serie = completi[colonna].dropna()
        return float(serie.iloc[-n:].median()) if not serie.empty else None

    # --- quota di utili distribuita -------------------------------------
    payout = mediana("payout")
    punti, testo = _band_from_points(payout, (
        (0.40, 15.0, "pays out less than 40% of earnings: plenty of room"),
        (0.60, 10.0, "pays out 40-60% of earnings: ample room"),
        (0.75, 4.0, "pays out 60-75% of earnings: normal room"),
        (0.90, -8.0, "pays out more than 75% of earnings: little room"),
        (1.05, -18.0, "pays out nearly all of its earnings: no room left"),
        (99.0, -28.0, "pays out more than it earns: not sustainable for long"),
    ), 0.0, "share of earnings paid out cannot be computed")
    punteggio += punti
    fattori.append(Factor("Share of earnings paid out (3-year median)", payout, punti, testo))

    # --- copertura con la cassa vera ------------------------------------
    copertura = mediana("copertura_cassa")
    if copertura is None and dps_indicato and metrics.ttm.get("fcf") and metrics.shares:
        copertura = safe_div(metrics.ttm["fcf"] / metrics.shares, dps_indicato)
    punti, testo = _band_from_points(copertura, (
        (0.0, -26.0, "free cash flow is negative: the dividend is funded entirely by debt, "
                     "asset sales or reserves"),
        (0.70, -22.0, "free cash flow covers less than 70% of the dividend: debt funds the rest"),
        (1.00, -10.0, "free cash flow does not fully cover the dividend"),
        (1.20, 3.0, "free cash flow barely covers the dividend"),
        (1.50, 8.0, "free cash flow covers the dividend with a fair margin"),
        (2.00, 12.0, "free cash flow covers the dividend comfortably"),
        (99.0, 15.0, "free cash flow is far above the dividend"),
    ), 0.0, "cash coverage cannot be computed")
    punteggio += punti
    fattori.append(Factor("Free cash flow coverage (3-year median)", copertura,
                          punti, testo, fmt="x"))

    # --- debito ----------------------------------------------------------
    debito = metrics.health.get("net_debt_ebitda")
    if metrics.is_financial:
        fattori.append(Factor("Net debt / EBITDA", None, 0.0,
                              "financial stock: the measure does not apply", fmt="x"))
    else:
        punti, testo = _band_from_points(debito, (
            (1.00, 10.0, "very low debt: the dividend does not compete with the banks"),
            (2.00, 6.0, "contained debt"),
            (3.00, 0.0, "debt within the norm"),
            (4.00, -8.0, "high debt: in a hard year the dividend is the first thing to give"),
            (999.0, -18.0, "very high debt: the dividend ranks behind servicing it"),
        ), 0.0, "net debt cannot be computed")
        punteggio += punti
        fattori.append(Factor("Net debt / EBITDA", debito, punti, testo, fmt="x"))

    # --- andamento degli utili ------------------------------------------
    eps_cagr = metrics.growth.get("eps_cagr")
    punti, testo = _band_from_points(eps_cagr, (
        (-0.10, -14.0, "earnings falling sharply: today's dividend gets harder every year"),
        (0.00, -6.0, "earnings falling"),
        (0.05, 3.0, "earnings stable"),
        (99.0, 8.0, "earnings growing: the dividend has room to rise"),
    ), 0.0, "earnings trend cannot be computed")
    punteggio += punti
    fattori.append(Factor("Average earnings per share growth", eps_cagr, punti, testo))

    # --- storia dei tagli ------------------------------------------------
    anni_dal_taglio = streaks.get("anni_dall_ultimo_taglio")
    tagli = streaks.get("tagli")
    if tagli is None:
        punti, testo = 0.0, "cut history cannot be reconstructed"
    elif tagli == 0:
        punti, testo = 10.0, f"no cut in the {streaks.get('anni_osservati', 0)} years observed"
    elif anni_dal_taglio is not None and anni_dal_taglio <= 3:
        punti, testo = -12.0, f"cut the dividend {anni_dal_taglio} years ago"
    else:
        parola = "cut" if tagli == 1 else "cuts"
        punti, testo = 2.0, (f"{tagli} {parola} in the past, but none in the last "
                             f"{anni_dal_taglio} years")
    punteggio += punti
    fattori.append(Factor("Cut history", float(tagli) if tagli is not None else None,
                          punti, testo, fmt="num"))

    # --- continuita' del pagamento ---------------------------------------
    saltati = streaks.get("anni_saltati")
    osservati = streaks.get("anni_osservati") or 0
    if saltati is None:
        punti, testo = 0.0, "continuity cannot be reconstructed"
    elif saltati == 0:
        punti, testo = 8.0, "paid in every year observed"
    else:
        # Sei punti per ogni anno saltato: chi salta quattro anni su dieci non
        # e' un titolo da reddito, per quanto sia basso il payout quando paga.
        punti = max(-22.0, -6.0 * saltati)
        testo = f"skipped {saltati} of {osservati} years: payment is not dependable"
    punteggio += punti
    fattori.append(Factor("Payment continuity",
                          float(saltati) if saltati is not None else None, punti, testo, fmt="num"))

    # --- crescita del dividendo ------------------------------------------
    # La piu' prudente fra la crescita a 5 e a 10 anni. Dopo un taglio la
    # media a 5 anni misura la risalita dal minimo e sembra ottima: usarla da
    # sola premierebbe proprio le aziende che hanno tagliato.
    candidate_crescita = [v for v in (growth.get("cagr_5y"), growth.get("cagr_10y"))
                          if v is not None]
    crescita = min(candidate_crescita) if candidate_crescita else growth.get("cagr_3y")
    punti, testo = _band_from_points(crescita, (
        (-0.02, -8.0, "the dividend is shrinking over time"),
        (0.00, -2.0, "the dividend is flat"),
        (0.05, 3.0, "the dividend grows slowly"),
        (99.0, 6.0, "the dividend grows at a good pace"),
    ), 0.0, "dividend growth cannot be computed")
    punteggio += punti
    fattori.append(Factor("Average dividend growth", crescita, punti, testo))

    punteggio = max(0.0, min(100.0, punteggio))
    # Tetto per i pagatori irregolari. Chi salta anni non e' un titolo da
    # reddito, per quanto sia prudente il payout negli anni in cui paga: senza
    # questo tetto un payout basso e una cassa abbondante compensavano gli anni
    # saltati e il punteggio saliva, che e' esattamente il contrario di cio'
    # che interessa a chi compra per la cedola.
    if saltati:
        tetto = 35.0 if saltati >= 3 else 45.0
        if punteggio > tetto:
            fattori.append(Factor(
                "Cap for irregular payment", float(saltati), tetto - punteggio,
                f"with {saltati} years skipped the score cannot exceed {tetto:.0f}: "
                "continuity comes before every other factor", fmt="num"))
            punteggio = tetto
    banda = "solid" if punteggio >= 65 else "watch closely" if punteggio >= 45 else "at risk"

    # --- avvisi che valgono da soli --------------------------------------
    innesci: list[str] = []
    utile_ttm = metrics.ttm.get("net_income")
    if utile_ttm is not None and utile_ttm < 0:
        innesci.append("The company is loss-making over the last twelve months: any dividend "
                       "comes out of reserves or debt.")
    if payout is not None and payout > 1.1:
        innesci.append(f"It pays out {payout:.0%} of earnings: above 100% the dividend is not "
                       "funded by the year's result.")
    if copertura is not None and copertura < 0.7:
        innesci.append("Free cash flow covers less than 70% of the dividend: the rest comes "
                       "from debt, asset sales or reserves.")
    rendimento_attuale = yield_stats.get("attuale")
    mediana_rendimento = yield_stats.get("mediana")
    rischio = 100.0 - punteggio
    if rendimento_attuale and mediana_rendimento and rendimento_attuale > 1.7 * mediana_rendimento:
        # Un rendimento molto sopra la propria media di solito non e' un regalo:
        # e' il mercato che sta scontando un taglio. La soglia sta al +70% e non
        # al +100% perche' a due volte la mediana il taglio e' spesso gia'
        # annunciato, e allora l'avviso arriva tardi.
        rischio += 15.0
        innesci.append(f"The yield ({rendimento_attuale:.1%}) is "
                       f"{rendimento_attuale / mediana_rendimento:.1f} times the historical median "
                       f"({mediana_rendimento:.1%}): when the payout yields far more than usual, "
                       "the market is normally already pricing in a cut.")
    if utile_ttm is not None and utile_ttm < 0:
        rischio += 15.0
    if payout is not None and payout > 1.1:
        rischio += 10.0
    rischio = max(0.0, min(100.0, rischio))
    banda_rischio = "low" if rischio < 25 else "medium" if rischio < 55 else "high"

    return DividendSafety(score=punteggio, band=banda, factors=fattori,
                          hard_triggers=innesci, cut_risk_band=banda_rischio,
                          cut_risk_score=rischio)


# ==========================================================================
# 7. previsione a due anni
# ==========================================================================
def _forecast(tabella: pd.DataFrame, growth: dict, metrics: Metrics,
              dps_indicato: Optional[float], safety: DividendSafety) -> DividendForecast:
    """Tre metodi indipendenti, una forchetta, e uno scenario di taglio."""
    previsione = DividendForecast()
    completi = tabella[tabella["completo"]] if not tabella.empty else pd.DataFrame()
    paganti = completi[completi["dps"] > 0] if not completi.empty else pd.DataFrame()
    if dps_indicato is None or dps_indicato <= 0 or paganti.empty:
        previsione.note = ("Without a dividend history there is no way to estimate the next "
                           "payments.")
        return previsione

    # --- metodo 1: tendenza, smorzata ------------------------------------
    finestra = paganti.iloc[-7:]
    if len(finestra) >= 3:
        anni = np.arange(len(finestra), dtype=float)
        pendenza = float(np.polyfit(anni, np.log(finestra["dps"].to_numpy()), 1)[0])
        crescita_storica = math.exp(pendenza) - 1.0
        # Smorziamo: nessuna azienda ripete indefinitamente la crescita del
        # passato, e una retta sui logaritmi estrapola con troppa sicurezza.
        crescita = max(-0.15, min(0.15, crescita_storica * 0.6))
        previsione.methods.append(ForecastMethod(
            "Damped historical trend", dps_indicato * (1 + crescita), 0.40,
            f"historical growth {crescita_storica:+.1%} over {len(finestra)} years, "
            f"taken at 60% ({crescita:+.1%})"))
    else:
        previsione.methods.append(ForecastMethod(
            "Damped historical trend", None,
            skipped_reason="at least 3 complete dividend years are needed"))

    # --- metodo 2: quota di utili ----------------------------------------
    eps_atteso = metrics.estimates.get("eps_forward") or metrics.ttm.get("eps")
    payout_storico = (float(paganti["payout"].dropna().iloc[-5:].median())
                      if "payout" in paganti and paganti["payout"].notna().any() else None)
    if eps_atteso and eps_atteso > 0 and payout_storico and 0 < payout_storico <= 1.5:
        grezzo = eps_atteso * payout_storico
        # Un salto oltre il 40% in un anno non e' una previsione, e' rumore.
        valore = max(dps_indicato * 0.60, min(dps_indicato * 1.40, grezzo))
        previsione.methods.append(ForecastMethod(
            "Payout ratio on expected earnings", valore, 0.35,
            f"expected earnings {eps_atteso:.2f} x historical payout {payout_storico:.0%}"))
    else:
        previsione.methods.append(ForecastMethod(
            "Payout ratio on expected earnings", None,
            skipped_reason="expected earnings or historical payout not available"))

    # --- metodo 3: quanto ne consente la cassa ---------------------------
    fcf_ps = (metrics.ttm.get("fcf") / metrics.shares
              if metrics.ttm.get("fcf") and metrics.shares else None)
    quota_cassa = None
    if "fcf_per_azione" in paganti and paganti["fcf_per_azione"].notna().any():
        rapporti = (paganti["dps"] / paganti["fcf_per_azione"]).replace(
            [np.inf, -np.inf], np.nan).dropna()
        rapporti = rapporti[(rapporti > 0) & (rapporti < 3)]
        if len(rapporti) >= 3:
            quota_cassa = float(rapporti.iloc[-5:].median())
    if fcf_ps and fcf_ps > 0 and quota_cassa:
        valore = max(dps_indicato * 0.50, min(dps_indicato * 1.40, fcf_ps * quota_cassa))
        previsione.methods.append(ForecastMethod(
            "Share of free cash flow", valore, 0.25,
            f"free cash flow per share {fcf_ps:.2f} x historical share {quota_cassa:.0%}"))
    else:
        previsione.methods.append(ForecastMethod(
            "Share of free cash flow", None,
            skipped_reason="free cash flow per share unavailable or negative"))

    utilizzabili = [m for m in previsione.methods if m.usable]
    if not utilizzabili:
        previsione.year1_base = dps_indicato
        previsione.year1_low = dps_indicato * 0.7
        previsione.year1_high = dps_indicato * 1.15
        previsione.year2_base = dps_indicato
        previsione.year2_low = dps_indicato * 0.6
        previsione.year2_high = dps_indicato * 1.25
        previsione.growth = 0.0
        previsione.note = ("No method applies: the forecast assumes today's dividend is "
                           "maintained, with a wide range.")
        return previsione

    peso_totale = sum(m.weight for m in utilizzabili) or 1.0
    for metodo in utilizzabili:
        metodo.weight = metodo.weight / peso_totale
    base = sum(m.value * m.weight for m in utilizzabili)

    valori = [m.value for m in utilizzabili]
    # La forchetta nasce dalla distanza fra i metodi: se concordano e' stretta.
    dispersione = (max(valori) - min(valori)) / base if base else 0.0
    dispersione = max(0.08, min(0.45, dispersione))

    crescita_implicita = base / dps_indicato - 1.0
    previsione.growth = crescita_implicita
    previsione.year1_base = base
    previsione.year1_high = base * (1 + dispersione)
    previsione.year1_low = base * (1 - dispersione)
    previsione.year2_base = base * (1 + max(-0.15, min(0.15, crescita_implicita)))
    previsione.year2_high = previsione.year1_high * (1 + dispersione * 0.5)
    previsione.year2_low = previsione.year1_low * (1 - dispersione * 0.5)

    if safety.cut_risk_band == "high":
        # Scenario pessimistico esplicito: un taglio del 40%, che e' l'ordine
        # di grandezza tipico quando un'azienda taglia davvero.
        previsione.year1_low = min(previsione.year1_low, dps_indicato * 0.60)
        previsione.year2_low = min(previsione.year2_low, dps_indicato * 0.50)
        previsione.note = ("Cut risk is high: the pessimistic case assumes the dividend is "
                           "reduced by 40-50%.")
    elif safety.cut_risk_band == "medium":
        previsione.year1_low = min(previsione.year1_low, dps_indicato * 0.80)
        previsione.year2_low = min(previsione.year2_low, dps_indicato * 0.75)
    return previsione


# ==========================================================================
# 8. verifica retrospettiva del segnale
# ==========================================================================
def _forward_total_return(chiusure: pd.Series, payments: pd.Series,
                          partenza: pd.Timestamp, anni: float) -> Optional[float]:
    """Rendimento totale, dividendi reinvestiti, da `partenza` per `anni`."""
    fine = partenza + pd.Timedelta(days=int(365.25 * anni))
    finestra = chiusure[(chiusure.index >= partenza) & (chiusure.index <= fine)]
    if len(finestra) < 100:
        return None
    primo, ultimo = float(finestra.iloc[0]), float(finestra.iloc[-1])
    if primo <= 0:
        return None
    quote = 1.0
    nel_periodo = payments[(payments.index > finestra.index[0]) & (payments.index <= finestra.index[-1])]
    for data, importo in nel_periodo.items():
        successivi = finestra.index[finestra.index >= data]
        if not len(successivi):
            continue
        prezzo = float(finestra.loc[successivi[0]])
        if prezzo > 0:
            quote += quote * float(importo) / prezzo
    return quote * ultimo / primo - 1.0


ETICHETTE_SEGNALE = (
    "High yield (buy signal)",
    "Middling yield",
    "Low yield (sell signal)",
)


def _backtest(daily: Optional[pd.Series], prices: Optional[pd.DataFrame],
              payments: pd.Series, *, orizzonte: float = 2.0) -> YieldBacktest:
    """La regola "compra quando il rendimento e' alto" ha funzionato *qui*?

    Per ogni fine mese guardiamo in che percentile stava il rendimento rispetto
    ai tre anni precedenti, e misuriamo il rendimento totale dei due anni
    successivi. E' una verifica su un titolo solo, con finestre sovrapposte:
    indicativa, non una dimostrazione. Ma e' misurata sui dati veri, non
    affermata.
    """
    risultato = YieldBacktest()
    if daily is None or prices is None or prices.empty or payments.empty:
        risultato.note = ("A backtest needs at least five years of prices and dividends: there "
                          "is not enough data here.")
        return risultato
    chiusure = prices["Close"].dropna()
    fine_dati = chiusure.index[-1]
    mensili = daily.resample("ME").last().dropna()
    osservazioni: list[tuple[str, float]] = []

    for data, rendimento in mensili.items():
        if data + pd.Timedelta(days=int(365.25 * orizzonte)) > fine_dati:
            break  # non c'e' futuro da misurare
        precedenti = daily[(daily.index > data - pd.Timedelta(days=int(365.25 * 3)))
                           & (daily.index <= data)]
        if len(precedenti) < 400:
            continue  # meno di tre anni di storia: il percentile non significa
        percentile = float((precedenti <= rendimento).mean())
        futuro = _forward_total_return(chiusure, payments, data, orizzonte)
        if futuro is None:
            continue
        if percentile >= 0.75:
            etichetta = ETICHETTE_SEGNALE[0]
        elif percentile <= 0.25:
            etichetta = ETICHETTE_SEGNALE[2]
        else:
            etichetta = ETICHETTE_SEGNALE[1]
        osservazioni.append((etichetta, futuro))

    if len(osservazioni) < 24:
        risultato.observations = len(osservazioni)
        risultato.note = (f"Only {len(osservazioni)} usable observations: too few to say "
                          "anything. More price and dividend history is needed.")
        return risultato

    tabella = pd.DataFrame(osservazioni, columns=["segnale", "rendimento"])
    for etichetta in ETICHETTE_SEGNALE:
        gruppo = tabella[tabella["segnale"] == etichetta]["rendimento"]
        risultato.buckets.append(BacktestBucket(
            label=etichetta, observations=int(len(gruppo)),
            avg_return_2y=float(gruppo.mean()) if len(gruppo) else None,
            median_return_2y=float(gruppo.median()) if len(gruppo) else None,
            hit_rate=float((gruppo > 0).mean()) if len(gruppo) else None,
        ))
    risultato.observations = int(len(tabella))
    risultato.years_covered = float((mensili.index[-1] - mensili.index[0]).days / 365.25)
    alto = next((b for b in risultato.buckets if b.label == ETICHETTE_SEGNALE[0]), None)
    basso = next((b for b in risultato.buckets if b.label == ETICHETTE_SEGNALE[2]), None)
    if alto and basso and alto.avg_return_2y is not None and basso.avg_return_2y is not None:
        risultato.separation = alto.avg_return_2y - basso.avg_return_2y
    risultato.usable = all(b.observations >= 6 for b in risultato.buckets if b.observations)
    risultato.note = (
        f"{risultato.observations} monthly observations over {risultato.years_covered:.0f} years, "
        "with overlapping two-year windows: the independent observations are far fewer than the "
        "count suggests. One stock, one period: this is a hint about how this stock behaved, not "
        "a rule that holds in general."
    )
    return risultato


# ==========================================================================
# 9. il segnale operativo
# ==========================================================================
def _signal(metrics: Metrics, tabella: pd.DataFrame, yield_stats: dict, growth: dict,
            safety: DividendSafety, previsione: DividendForecast,
            dps_indicato: Optional[float]) -> DividendSignal:
    """Compra / mantieni / vendi, ragionando da investitore da reddito.

    La logica di valutazione e' il ritorno del rendimento alla propria mediana:
    se il titolo ha reso storicamente il 5% e oggi rende il 7%, a dividendo
    confermato il prezzo "normale" e' un 40% piu' alto. A questo si aggiungono
    due anni di cedole incassate.
    """
    prezzo = metrics.price
    segnale = DividendSignal(action="MANTIENI", conviction="bassa", headline="")

    mediana = yield_stats.get("mediana")
    if not prezzo or not previsione.ok or not mediana:
        segnale.headline = "HOLD - not enough data for a dividend signal"
        segnale.reasons.append(
            "Without a historical median yield or a dividend forecast there is no way to say "
            "whether today's price is generous or expensive.")
        return segnale

    # Il rendimento obiettivo non e' la mediana storica secca. Un dividendo
    # fragile merita in modo permanente un rendimento piu' alto: chi assume che
    # torni alla sua vecchia mediana sta scommettendo che l'azienda torni quella
    # di prima. Sotto 60 punti di solidita' alziamo l'obiettivo fino al +90%.
    penalita = max(0.0, (60.0 - safety.score) / 60.0) * 0.9
    obiettivo_pieno = max(RENDIMENTO_MIN, min(RENDIMENTO_MAX, mediana * (1.0 + penalita)))
    attuale = yield_stats.get("attuale")
    if attuale:
        # Il rendimento non torna tutto alla mediana in due anni. Se il prezzo
        # ha avuto una tendenza lunga, la vecchia mediana descrive un'azienda e
        # un mercato diversi da quelli di oggi: assumiamo che si chiuda metà
        # dello scarto, che e' lo stesso smorzamento usato nella previsione.
        obiettivo = attuale + 0.5 * (obiettivo_pieno - attuale)
    else:
        obiettivo = obiettivo_pieno
    obiettivo = max(RENDIMENTO_MIN, min(RENDIMENTO_MAX, obiettivo))
    segnale.target_yield = obiettivo

    # Quando un taglio e' probabile, il titolo va valutato sul dividendo
    # *tagliato*, non su quello di oggi: e' lo scenario che il mercato sta
    # scontando, ed e' l'errore piu' costoso di un modello sui dividendi.
    scenario_taglio = safety.cut_risk_band == "high"
    dps_valutazione = (previsione.year1_low if scenario_taglio and previsione.year1_low
                       else previsione.year1_base)
    dps_secondo_anno = (previsione.year2_low if scenario_taglio and previsione.year2_low
                        else previsione.year2_base)

    segnale.fair_price = dps_valutazione / obiettivo
    # Ingresso e uscita nascono dallo stesso rendimento obiettivo del valore
    # stimato, non dai quartili storici grezzi: derivandoli da due quadri
    # diversi il prezzo d'ingresso poteva finire sopra il valore stimato, che
    # non ha senso. Si compra quando la cedola rende un quinto in piu' di
    # quanto il titolo merita, si alleggerisce quando rende un quinto in meno.
    segnale.entry_price = dps_valutazione / (obiettivo * (1 + MARGINE_SICUREZZA))
    segnale.exit_price = dps_valutazione / (obiettivo * (1 - MARGINE_SICUREZZA))

    # Ultimo freno: oltre il 50% in due anni il modello non stima piu' un
    # valore, estrapola un prezzo che si e' mosso molto.
    segnale.price_component = max(-0.50, min(0.50, segnale.fair_price / prezzo - 1.0))
    incassato = (dps_valutazione or 0) + (dps_secondo_anno or 0)
    segnale.income_component = incassato / prezzo
    segnale.expected_return_2y = segnale.price_component + segnale.income_component
    if segnale.expected_return_2y > -1:
        segnale.expected_annualized = (1 + segnale.expected_return_2y) ** 0.5 - 1

    punti = 0.0
    motivi: list[str] = []

    atteso = segnale.expected_return_2y
    if atteso >= 0.30:
        punti += 2.0
        motivi.append(f"Very high total expected return over two years ({atteso:+.0%}): "
                      f"{segnale.income_component:+.0%} from dividends and "
                      f"{segnale.price_component:+.0%} from the yield moving back towards its "
                      f"{obiettivo:.1%} target.")
    elif atteso >= 0.18:
        punti += 1.5
        motivi.append(f"Attractive total expected return over two years ({atteso:+.0%}), of "
                      f"which {segnale.income_component:+.0%} collected as dividends.")
    elif atteso >= 0.08:
        punti += 0.5
        motivi.append(f"Modest total expected return over two years ({atteso:+.0%}).")
    elif atteso >= -0.08:
        motivi.append(f"Price in line with what the dividend justifies ({atteso:+.0%} over two "
                      "years).")
    elif atteso >= -0.20:
        punti -= 1.5
        motivi.append(f"The price already assumes more than the dividend justifies "
                      f"({atteso:+.0%} over two years).")
    else:
        punti -= 2.0
        motivi.append(f"The price is well above what the dividend justifies ({atteso:+.0%} "
                      "over two years).")

    if safety.score >= 70:
        punti += 1.5
        motivi.append(f"Solid dividend ({safety.score:.0f}/100): {safety.band}.")
    elif safety.score >= 55:
        punti += 0.75
        motivi.append(f"Dividend broadly sustainable ({safety.score:.0f}/100).")
    elif safety.score >= 45:
        motivi.append(f"Dividend sustainability uncertain ({safety.score:.0f}/100).")
    elif safety.score >= 35:
        punti -= 1.0
        motivi.append(f"Fragile dividend ({safety.score:.0f}/100).")
    else:
        punti -= 2.0
        motivi.append(f"Dividend at risk ({safety.score:.0f}/100).")

    percentile = yield_stats.get("percentile")
    if percentile is not None:
        attuale = yield_stats.get("attuale")
        if percentile >= 0.75:
            punti += 1.0
            motivi.append(f"Today's yield ({attuale:.1%}) is among the highest in its history: "
                          f"more generous than {percentile:.0%} of all observations.")
        elif percentile >= 0.55:
            punti += 0.5
            motivi.append(f"Today's yield ({attuale:.1%}) is above its own median "
                          f"({mediana:.1%}).")
        elif percentile <= 0.15:
            punti -= 1.5
            motivi.append(f"Today's yield ({attuale:.1%}) is among the lowest ever recorded: "
                          "by its own history the stock is expensive.")
        elif percentile <= 0.25:
            punti -= 1.0
            motivi.append(f"Today's yield ({attuale:.1%}) is below its own median "
                          f"({mediana:.1%}).")

    crescita = growth.get("cagr_5y") or growth.get("cagr_3y")
    if crescita is not None:
        if crescita > 0.05:
            punti += 0.5
            motivi.append(f"The dividend grows {crescita:.1%} a year: the yield on your "
                          "purchase price improves over time.")
        elif crescita < -0.02:
            punti -= 0.5
            motivi.append(f"The dividend is shrinking {abs(crescita):.1%} a year.")

    if safety.cut_risk_band == "high":
        punti -= 2.0
    elif safety.cut_risk_band == "medium":
        punti -= 0.5

    punti = max(-6.0, min(6.0, punti))
    if punti >= 2.0:
        azione = "BUY"
    elif punti > -1.0:
        azione = "HOLD"
    else:
        azione = "SELL"

    # Il rischio di taglio prevale: un rendimento alto perche' il mercato si
    # aspetta un taglio non e' un'occasione.
    if scenario_taglio:
        motivi.insert(0, f"Cut risk is high, so the valuation uses the pessimistic-case "
                         f"dividend ({dps_valutazione:.2f} instead of "
                         f"{previsione.year1_base:.2f}) and a target yield raised to "
                         f"{obiettivo:.1%} for the risk.")
        if azione == "BUY":
            azione = "HOLD"
            motivi.insert(1, "A cheap price is not enough to recommend buying a dividend that "
                             "may be cut.")
        if atteso < 0.10:
            azione = "SELL"
    for innesco in safety.hard_triggers:
        motivi.append(innesco)

    convinzione = "high" if abs(punti) >= 3.0 else "medium" if abs(punti) >= 1.5 else "low"
    segnale.action = azione
    segnale.conviction = convinzione
    segnale.reasons = motivi
    segnale.headline = {
        "BUY": f"BUY for the dividend - {convinzione} conviction",
        "HOLD": f"HOLD - {convinzione} conviction",
        "SELL": f"SELL / REDUCE - {convinzione} conviction",
    }[azione]
    return segnale


# ==========================================================================
# ingresso pubblico
# ==========================================================================
def analyze_dividends(metrics: Metrics, prices: Optional[pd.DataFrame],
                      dividend_set: DividendSet) -> DividendAnalysis:
    """Analisi completa dei dividendi a dieci anni, dal dato al segnale."""
    analisi = DividendAnalysis(symbol=metrics.symbol, currency=metrics.currency,
                               price=metrics.price, source=dividend_set)
    pagamenti = dividend_set.series if dividend_set and dividend_set.ok else None
    if pagamenti is None or pagamenti.empty:
        analisi.notes.append(
            "No dividend recorded for this stock in the sources available. If it does pay "
            "but the data is missing, you can supply it in a CSV file (see the Data sources tab)."
        )
        return analisi

    analisi.payments = pagamenti
    analisi.span_years = (pagamenti.index[-1] - pagamenti.index[0]).days / 365.25
    analisi.cadence = _cadence(pagamenti)
    analisi.years = _build_years(pagamenti, prices, metrics)
    analisi.daily_yield = _daily_yield(pagamenti, prices, analisi.cadence)

    dps_indicato = _indicated_dps(pagamenti, analisi.cadence)
    analisi.growth = _growth(analisi.years)
    analisi.streaks = _streaks(analisi.years)
    analisi.yield_stats = _yield_stats(analisi.years, analisi.daily_yield,
                                       dps_indicato, metrics.price)
    analisi.yield_stats["dps_indicato"] = dps_indicato
    analisi.total_return = _total_return(pagamenti, prices)
    analisi.yield_on_cost = _yield_on_cost(prices, dps_indicato)
    analisi.safety = _safety(analisi.years, analisi.streaks, analisi.growth, metrics,
                             dps_indicato, analisi.yield_stats)
    analisi.forecast = _forecast(analisi.years, analisi.growth, metrics,
                                 dps_indicato, analisi.safety)
    analisi.backtest = _backtest(analisi.daily_yield, prices, pagamenti)
    analisi.signal = _signal(metrics, analisi.years, analisi.yield_stats, analisi.growth,
                             analisi.safety, analisi.forecast, dps_indicato)

    completi = int(analisi.growth.get("anni_completi") or 0)
    if completi < 5:
        analisi.notes.append(
            f"Only {completi} complete dividend years: this tool is built for a ten-year read, "
            "and with this much history the averages are indicative only."
        )
    conteggi = pagamenti.groupby(pagamenti.index.year).count()
    completi_conteggio = conteggi[conteggi.index < pd.Timestamp.now().year]
    if len(completi_conteggio) >= 4 and completi_conteggio.nunique() > 1:
        analisi.notes.append(
            "The number of payments per year changed over the period: the historical yield "
            f"series uses today's cadence ({analisi.cadence} payments a year) for the past too, "
            "so the earliest years may be slightly distorted."
        )
    if analisi.yield_stats.get("base") == "media annuale":
        analisi.notes.append(
            "The yield percentile is computed on annual averages (not enough daily prices): "
            "it is coarser than usual."
        )
    for avviso in (dividend_set.disagreements if dividend_set else []):
        analisi.notes.append(avviso)
    for nota in (dividend_set.notes if dividend_set else []):
        analisi.notes.append(nota)
    return analisi
