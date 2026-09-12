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
    band: str                                   # "solido" | "da tenere d'occhio" | "a rischio"
    factors: list[Factor] = field(default_factory=list)
    hard_triggers: list[str] = field(default_factory=list)
    cut_risk_band: str = "medio"                # "basso" | "medio" | "alto"
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
        (0.40, 15.0, "distribuisce meno del 40% degli utili: molto margine"),
        (0.60, 10.0, "distribuisce fra il 40% e il 60% degli utili: margine ampio"),
        (0.75, 4.0, "distribuisce fra il 60% e il 75% degli utili: margine normale"),
        (0.90, -8.0, "distribuisce oltre il 75% degli utili: poco margine"),
        (1.05, -18.0, "distribuisce quasi tutto l'utile: nessun margine"),
        (99.0, -28.0, "distribuisce piu' di quanto guadagna: insostenibile a lungo"),
    ), 0.0, "quota di utili distribuita non calcolabile")
    punteggio += punti
    fattori.append(Factor("Quota di utili distribuita (mediana 3 anni)", payout, punti, testo))

    # --- copertura con la cassa vera ------------------------------------
    copertura = mediana("copertura_cassa")
    if copertura is None and dps_indicato and metrics.ttm.get("fcf") and metrics.shares:
        copertura = safe_div(metrics.ttm["fcf"] / metrics.shares, dps_indicato)
    punti, testo = _band_from_points(copertura, (
        (0.0, -26.0, "la cassa libera e' negativa: il dividendo e' interamente finanziato "
                     "da debito, cessioni o riserve"),
        (0.70, -22.0, "la cassa libera copre meno del 70% del dividendo: lo finanzia il debito"),
        (1.00, -10.0, "la cassa libera non copre del tutto il dividendo"),
        (1.20, 3.0, "la cassa libera copre appena il dividendo"),
        (1.50, 8.0, "la cassa libera copre il dividendo con un margine discreto"),
        (2.00, 12.0, "la cassa libera copre il dividendo con largo margine"),
        (99.0, 15.0, "la cassa libera e' molto superiore al dividendo"),
    ), 0.0, "copertura con la cassa non calcolabile")
    punteggio += punti
    fattori.append(Factor("Copertura con la cassa libera (mediana 3 anni)", copertura,
                          punti, testo, fmt="x"))

    # --- debito ----------------------------------------------------------
    debito = metrics.health.get("net_debt_ebitda")
    if metrics.is_financial:
        fattori.append(Factor("Debito netto / EBITDA", None, 0.0,
                              "titolo finanziario: l'indicatore non e' applicabile", fmt="x"))
    else:
        punti, testo = _band_from_points(debito, (
            (1.00, 10.0, "debito molto basso: il dividendo non compete con le banche"),
            (2.00, 6.0, "debito contenuto"),
            (3.00, 0.0, "debito nella norma"),
            (4.00, -8.0, "debito elevato: in un anno difficile il dividendo e' il primo a cedere"),
            (999.0, -18.0, "debito molto elevato: il dividendo e' subordinato al servizio del debito"),
        ), 0.0, "debito netto non calcolabile")
        punteggio += punti
        fattori.append(Factor("Debito netto / EBITDA", debito, punti, testo, fmt="x"))

    # --- andamento degli utili ------------------------------------------
    eps_cagr = metrics.growth.get("eps_cagr")
    punti, testo = _band_from_points(eps_cagr, (
        (-0.10, -14.0, "utili in forte calo: il dividendo attuale e' sempre piu' difficile"),
        (0.00, -6.0, "utili in calo"),
        (0.05, 3.0, "utili stabili"),
        (99.0, 8.0, "utili in crescita: il dividendo ha spazio per salire"),
    ), 0.0, "andamento degli utili non calcolabile")
    punteggio += punti
    fattori.append(Factor("Crescita media dell'utile per azione", eps_cagr, punti, testo))

    # --- storia dei tagli ------------------------------------------------
    anni_dal_taglio = streaks.get("anni_dall_ultimo_taglio")
    tagli = streaks.get("tagli")
    if tagli is None:
        punti, testo = 0.0, "storia dei tagli non ricostruibile"
    elif tagli == 0:
        punti, testo = 10.0, f"nessun taglio negli {streaks.get('anni_osservati', 0)} anni osservati"
    elif anni_dal_taglio is not None and anni_dal_taglio <= 3:
        punti, testo = -12.0, f"ha tagliato il dividendo {anni_dal_taglio} anni fa"
    else:
        parola = "taglio" if tagli == 1 else "tagli"
        punti, testo = 2.0, (f"{tagli} {parola} in passato, ma nessuno negli ultimi "
                             f"{anni_dal_taglio} anni")
    punteggio += punti
    fattori.append(Factor("Storia dei tagli", float(tagli) if tagli is not None else None,
                          punti, testo, fmt="num"))

    # --- continuita' del pagamento ---------------------------------------
    saltati = streaks.get("anni_saltati")
    osservati = streaks.get("anni_osservati") or 0
    if saltati is None:
        punti, testo = 0.0, "continuita' non ricostruibile"
    elif saltati == 0:
        punti, testo = 8.0, "ha pagato in ogni anno osservato"
    else:
        # Sei punti per ogni anno saltato: chi salta quattro anni su dieci non
        # e' un titolo da reddito, per quanto sia basso il payout quando paga.
        punti = max(-22.0, -6.0 * saltati)
        testo = f"ha saltato {saltati} anni su {osservati}: pagamento non affidabile"
    punteggio += punti
    fattori.append(Factor("Continuita' del pagamento",
                          float(saltati) if saltati is not None else None, punti, testo, fmt="num"))

    # --- crescita del dividendo ------------------------------------------
    # La piu' prudente fra la crescita a 5 e a 10 anni. Dopo un taglio la
    # media a 5 anni misura la risalita dal minimo e sembra ottima: usarla da
    # sola premierebbe proprio le aziende che hanno tagliato.
    candidate_crescita = [v for v in (growth.get("cagr_5y"), growth.get("cagr_10y"))
                          if v is not None]
    crescita = min(candidate_crescita) if candidate_crescita else growth.get("cagr_3y")
    punti, testo = _band_from_points(crescita, (
        (-0.02, -8.0, "il dividendo si sta riducendo nel tempo"),
        (0.00, -2.0, "il dividendo e' fermo"),
        (0.05, 3.0, "il dividendo cresce lentamente"),
        (99.0, 6.0, "il dividendo cresce a buon ritmo"),
    ), 0.0, "crescita del dividendo non calcolabile")
    punteggio += punti
    fattori.append(Factor("Crescita media del dividendo", crescita, punti, testo))

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
                "Tetto per pagamento irregolare", float(saltati), tetto - punteggio,
                f"con {saltati} anni saltati il punteggio non puo' superare {tetto:.0f}: "
                "la continuita' viene prima di ogni altro fattore", fmt="num"))
            punteggio = tetto
    banda = "solido" if punteggio >= 65 else "da tenere d'occhio" if punteggio >= 45 else "a rischio"

    # --- avvisi che valgono da soli --------------------------------------
    innesci: list[str] = []
    utile_ttm = metrics.ttm.get("net_income")
    if utile_ttm is not None and utile_ttm < 0:
        innesci.append("L'azienda e' in perdita negli ultimi dodici mesi: qualunque dividendo "
                       "esce dalle riserve o dal debito.")
    if payout is not None and payout > 1.1:
        innesci.append(f"Distribuisce il {payout:.0%} degli utili: oltre il 100% il dividendo "
                       "non e' finanziato dal risultato dell'anno.")
    if copertura is not None and copertura < 0.7:
        innesci.append("La cassa libera copre meno del 70% del dividendo: la differenza arriva "
                       "da debito, cessioni o riserve.")
    rendimento_attuale = yield_stats.get("attuale")
    mediana_rendimento = yield_stats.get("mediana")
    rischio = 100.0 - punteggio
    if rendimento_attuale and mediana_rendimento and rendimento_attuale > 1.7 * mediana_rendimento:
        # Un rendimento molto sopra la propria media di solito non e' un regalo:
        # e' il mercato che sta scontando un taglio. La soglia sta al +70% e non
        # al +100% perche' a due volte la mediana il taglio e' spesso gia'
        # annunciato, e allora l'avviso arriva tardi.
        rischio += 15.0
        innesci.append(f"Il rendimento ({rendimento_attuale:.1%}) e' "
                       f"{rendimento_attuale / mediana_rendimento:.1f} volte la mediana storica "
                       f"({mediana_rendimento:.1%}): quando la cedola rende molto piu' del "
                       "solito, di norma il mercato sta gia' scontando un taglio.")
    if utile_ttm is not None and utile_ttm < 0:
        rischio += 15.0
    if payout is not None and payout > 1.1:
        rischio += 10.0
    rischio = max(0.0, min(100.0, rischio))
    banda_rischio = "basso" if rischio < 25 else "medio" if rischio < 55 else "alto"

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
        previsione.note = ("Senza una storia di dividendi non e' possibile stimare i prossimi "
                           "pagamenti.")
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
            "Tendenza storica smorzata", dps_indicato * (1 + crescita), 0.40,
            f"crescita storica {crescita_storica:+.1%} su {len(finestra)} anni, "
            f"usata al 60% ({crescita:+.1%})"))
    else:
        previsione.methods.append(ForecastMethod(
            "Tendenza storica smorzata", None,
            skipped_reason="servono almeno 3 anni completi di dividendi"))

    # --- metodo 2: quota di utili ----------------------------------------
    eps_atteso = metrics.estimates.get("eps_forward") or metrics.ttm.get("eps")
    payout_storico = (float(paganti["payout"].dropna().iloc[-5:].median())
                      if "payout" in paganti and paganti["payout"].notna().any() else None)
    if eps_atteso and eps_atteso > 0 and payout_storico and 0 < payout_storico <= 1.5:
        grezzo = eps_atteso * payout_storico
        # Un salto oltre il 40% in un anno non e' una previsione, e' rumore.
        valore = max(dps_indicato * 0.60, min(dps_indicato * 1.40, grezzo))
        previsione.methods.append(ForecastMethod(
            "Quota di utili sull'utile atteso", valore, 0.35,
            f"utile atteso {eps_atteso:.2f} x payout storico {payout_storico:.0%}"))
    else:
        previsione.methods.append(ForecastMethod(
            "Quota di utili sull'utile atteso", None,
            skipped_reason="utile atteso o payout storico non disponibili"))

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
            "Quota della cassa libera", valore, 0.25,
            f"cassa libera per azione {fcf_ps:.2f} x quota storica {quota_cassa:.0%}"))
    else:
        previsione.methods.append(ForecastMethod(
            "Quota della cassa libera", None,
            skipped_reason="cassa libera per azione non disponibile o negativa"))

    utilizzabili = [m for m in previsione.methods if m.usable]
    if not utilizzabili:
        previsione.year1_base = dps_indicato
        previsione.year1_low = dps_indicato * 0.7
        previsione.year1_high = dps_indicato * 1.15
        previsione.year2_base = dps_indicato
        previsione.year2_low = dps_indicato * 0.6
        previsione.year2_high = dps_indicato * 1.25
        previsione.growth = 0.0
        previsione.note = ("Nessun metodo applicabile: la previsione assume il dividendo "
                           "attuale confermato, con una forchetta larga.")
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

    if safety.cut_risk_band == "alto":
        # Scenario pessimistico esplicito: un taglio del 40%, che e' l'ordine
        # di grandezza tipico quando un'azienda taglia davvero.
        previsione.year1_low = min(previsione.year1_low, dps_indicato * 0.60)
        previsione.year2_low = min(previsione.year2_low, dps_indicato * 0.50)
        previsione.note = ("Il rischio di taglio e' alto: lo scenario pessimistico assume una "
                           "riduzione del 40-50% del dividendo.")
    elif safety.cut_risk_band == "medio":
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
    "Rendimento alto (segnale di acquisto)",
    "Rendimento intermedio",
    "Rendimento basso (segnale di vendita)",
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
        risultato.note = ("Servono almeno cinque anni di prezzi e dividendi per una verifica "
                          "retrospettiva: i dati disponibili non bastano.")
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
        risultato.note = (f"Solo {len(osservazioni)} osservazioni utilizzabili: troppo poche "
                          "per dire qualcosa. Serve piu' storia di prezzi e dividendi.")
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
        f"{risultato.observations} osservazioni mensili su {risultato.years_covered:.0f} anni, "
        "con finestre di due anni che si sovrappongono: le osservazioni indipendenti sono molte "
        "meno di quelle contate. Un titolo solo, un periodo solo: e' un indizio su come si e' "
        "comportato questo titolo, non una regola valida in generale."
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
        segnale.headline = "MANTIENI - dati insufficienti per un segnale sui dividendi"
        segnale.reasons.append(
            "Senza una mediana storica del rendimento o senza una previsione del dividendo "
            "non e' possibile dire se il prezzo di oggi sia generoso o caro.")
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
    scenario_taglio = safety.cut_risk_band == "alto"
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
        motivi.append(f"Rendimento complessivo atteso a due anni molto alto ({atteso:+.0%}): "
                      f"{segnale.income_component:+.0%} di cedole e {segnale.price_component:+.0%} "
                      f"dal ritorno del rendimento verso l'obiettivo del {obiettivo:.1%}.")
    elif atteso >= 0.18:
        punti += 1.5
        motivi.append(f"Rendimento complessivo atteso a due anni interessante ({atteso:+.0%}), "
                      f"di cui {segnale.income_component:+.0%} incassato in cedole.")
    elif atteso >= 0.08:
        punti += 0.5
        motivi.append(f"Rendimento complessivo atteso a due anni modesto ({atteso:+.0%}).")
    elif atteso >= -0.08:
        motivi.append(f"Prezzo in linea con il valore che il dividendo giustifica ({atteso:+.0%} "
                      "a due anni).")
    elif atteso >= -0.20:
        punti -= 1.5
        motivi.append(f"Il prezzo incorpora piu' di quanto il dividendo giustifichi "
                      f"({atteso:+.0%} a due anni).")
    else:
        punti -= 2.0
        motivi.append(f"Il prezzo e' molto sopra quello che il dividendo giustifica "
                      f"({atteso:+.0%} a due anni).")

    if safety.score >= 70:
        punti += 1.5
        motivi.append(f"Dividendo solido ({safety.score:.0f}/100): {safety.band}.")
    elif safety.score >= 55:
        punti += 0.75
        motivi.append(f"Dividendo nel complesso sostenibile ({safety.score:.0f}/100).")
    elif safety.score >= 45:
        motivi.append(f"Sostenibilita' del dividendo incerta ({safety.score:.0f}/100).")
    elif safety.score >= 35:
        punti -= 1.0
        motivi.append(f"Dividendo fragile ({safety.score:.0f}/100).")
    else:
        punti -= 2.0
        motivi.append(f"Dividendo a rischio ({safety.score:.0f}/100).")

    percentile = yield_stats.get("percentile")
    if percentile is not None:
        attuale = yield_stats.get("attuale")
        if percentile >= 0.75:
            punti += 1.0
            motivi.append(f"Il rendimento di oggi ({attuale:.1%}) e' fra i piu' alti della sua "
                          f"storia: piu' generoso del {percentile:.0%} delle osservazioni.")
        elif percentile >= 0.55:
            punti += 0.5
            motivi.append(f"Il rendimento di oggi ({attuale:.1%}) e' sopra la propria mediana "
                          f"({mediana:.1%}).")
        elif percentile <= 0.15:
            punti -= 1.5
            motivi.append(f"Il rendimento di oggi ({attuale:.1%}) e' fra i piu' bassi mai "
                          "registrati: storicamente il titolo e' caro.")
        elif percentile <= 0.25:
            punti -= 1.0
            motivi.append(f"Il rendimento di oggi ({attuale:.1%}) e' sotto la propria mediana "
                          f"({mediana:.1%}).")

    crescita = growth.get("cagr_5y") or growth.get("cagr_3y")
    if crescita is not None:
        if crescita > 0.05:
            punti += 0.5
            motivi.append(f"Il dividendo cresce del {crescita:.1%} all'anno: il rendimento sul "
                          "prezzo di acquisto migliora con il tempo.")
        elif crescita < -0.02:
            punti -= 0.5
            motivi.append(f"Il dividendo si riduce del {abs(crescita):.1%} all'anno.")

    if safety.cut_risk_band == "alto":
        punti -= 2.0
    elif safety.cut_risk_band == "medio":
        punti -= 0.5

    punti = max(-6.0, min(6.0, punti))
    if punti >= 2.0:
        azione = "COMPRA"
    elif punti > -1.0:
        azione = "MANTIENI"
    else:
        azione = "VENDI"

    # Il rischio di taglio prevale: un rendimento alto perche' il mercato si
    # aspetta un taglio non e' un'occasione.
    if scenario_taglio:
        motivi.insert(0, f"Il rischio di taglio e' alto, quindi la valutazione usa il dividendo "
                         f"dello scenario pessimistico ({dps_valutazione:.2f} invece di "
                         f"{previsione.year1_base:.2f}) e un rendimento obiettivo alzato al "
                         f"{obiettivo:.1%} per il rischio.")
        if azione == "COMPRA":
            azione = "MANTIENI"
            motivi.insert(1, "Un prezzo conveniente non basta a consigliare l'acquisto di un "
                             "dividendo che potrebbe essere tagliato.")
        if atteso < 0.10:
            azione = "VENDI"
    for innesco in safety.hard_triggers:
        motivi.append(innesco)

    convinzione = "alta" if abs(punti) >= 3.0 else "media" if abs(punti) >= 1.5 else "bassa"
    segnale.action = azione
    segnale.conviction = convinzione
    segnale.reasons = motivi
    segnale.headline = {
        "COMPRA": f"COMPRA per il dividendo - convinzione {convinzione}",
        "MANTIENI": f"MANTIENI - convinzione {convinzione}",
        "VENDI": f"VENDI / RIDUCI - convinzione {convinzione}",
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
            "Nessun dividendo registrato per questo titolo nelle fonti disponibili. "
            "Se distribuisce ma i dati mancano, puoi fornirli in un file CSV "
            "(vedi la scheda Fonti dei dati)."
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
            f"Solo {completi} anni completi di dividendi: l'obiettivo dichiarato e' una lettura "
            "a dieci anni, e con questa storia le medie sono indicative."
        )
    conteggi = pagamenti.groupby(pagamenti.index.year).count()
    completi_conteggio = conteggi[conteggi.index < pd.Timestamp.now().year]
    if len(completi_conteggio) >= 4 and completi_conteggio.nunique() > 1:
        analisi.notes.append(
            "Il numero di stacchi per anno e' cambiato nel periodo: la serie storica del "
            f"rendimento usa la cadenza attuale ({analisi.cadence} stacchi l'anno) anche per "
            "il passato, quindi i primi anni possono essere leggermente distorti."
        )
    if analisi.yield_stats.get("base") == "media annuale":
        analisi.notes.append(
            "Il percentile del rendimento e' calcolato sulle medie annuali (mancano prezzi "
            "giornalieri sufficienti): e' piu' grossolano del normale."
        )
    for avviso in (dividend_set.disagreements if dividend_set else []):
        analisi.notes.append(avviso)
    for nota in (dividend_set.notes if dividend_set else []):
        analisi.notes.append(nota)
    return analisi
