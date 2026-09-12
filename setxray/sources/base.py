"""L'astrazione sulle fonti e il confronto fra loro."""

from __future__ import annotations

import os
import re
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

import pandas as pd

# Chiavi che, nei JSON delle varie fonti, contengono la data dello stacco e
# l'importo per azione. Ogni fonte usa nomi diversi; teniamo l'elenco in un
# posto solo perche' il lettore generico li usa tutti.
# L'ordine conta: serve la data di *stacco* (ex dividend), non quella di
# pagamento. E' lo stacco che fa scendere il prezzo, ed e' con lo stacco che
# gli altri archivi registrano l'evento: mescolarli sfaserebbe il confronto
# fra fonti di qualche settimana.
CHIAVI_DATA = (
    "exdividenddate", "exdate", "ex_date", "xdate", "xdDate", "xd_date",
    "exdividend", "dividenddate", "date",
    "paymentdate", "payment_date", "paydate", "recorddate", "begindate",
)
CHIAVI_IMPORTO = (
    "dividendpershare", "cashdividendpershare", "adjdividend", "cashdividend",
    "dividend", "dps", "amount", "value", "dividendamount",
)
# Un dividendo per azione di un titolo SET sta fra pochi satang e qualche
# decina di baht; un dividendo straordinario puo' arrivare a qualche centinaio.
# Fuori da questa scala e' quasi sempre un errore di unita' (satang letti come
# baht) o un campo che non c'entra niente.
DPS_MIN, DPS_MAX = 0.0001, 2000.0
_ISO = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}")


@dataclass
class SourceResult:
    """Cosa ha risposto una singola fonte."""

    key: str
    label: str
    trust: int                      # 1 = riserva, 5 = ufficiale
    series: Optional[pd.Series] = None
    error: Optional[str] = None
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.series is not None and not self.series.empty

    @property
    def span_years(self) -> float:
        if not self.ok:
            return 0.0
        return (self.series.index[-1] - self.series.index[0]).days / 365.25

    @property
    def payments(self) -> int:
        return 0 if not self.ok else int(len(self.series))


@dataclass
class DividendSet:
    """La storia dei dividendi scelta, piu' tutto quello che serve a giudicarla."""

    symbol: str
    series: Optional[pd.Series] = None
    chosen: Optional[str] = None            # chiave della fonte scelta
    results: list[SourceResult] = field(default_factory=list)
    disagreements: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.series is not None and not self.series.empty

    @property
    def span_years(self) -> float:
        if not self.ok:
            return 0.0
        return (self.series.index[-1] - self.series.index[0]).days / 365.25

    def working_sources(self) -> list[SourceResult]:
        return [r for r in self.results if r.ok]

    def chosen_result(self) -> Optional[SourceResult]:
        return next((r for r in self.results if r.key == self.chosen), None)

    def provenance(self) -> str:
        """Una riga che dice da dove vengono i numeri e perche'."""
        scelta = self.chosen_result()
        if scelta is None:
            return "Nessuna fonte ha restituito dividendi."
        altre = [r for r in self.working_sources() if r.key != self.chosen]
        testo = (f"{scelta.label}: {scelta.payments} stacchi su "
                 f"{scelta.span_years:.1f} anni")
        if altre:
            testo += f". Confermata da {len(altre)} altra fonte" + ("" if len(altre) == 1 else "/i")
        else:
            testo += ". Nessuna seconda fonte disponibile per il confronto"
        return testo


# --------------------------------------------------------------------------
# lettura difensiva dei JSON
# --------------------------------------------------------------------------
def _to_date(valore: Any) -> Optional[pd.Timestamp]:
    """Accetta ISO, 'DD/MM/YYYY', timestamp unix in secondi o millisecondi."""
    if valore is None or isinstance(valore, bool):
        return None
    if isinstance(valore, (int, float)):
        if valore <= 0:
            return None
        # Sopra il 2001 in millisecondi: distinguiamo dai secondi con la scala.
        unita = "ms" if valore > 1e11 else "s"
        try:
            return pd.Timestamp(pd.to_datetime(valore, unit=unita)).normalize()
        except (ValueError, OverflowError):
            return None
    testo = str(valore).strip()
    if not testo:
        return None
    # "05/09/2024" e' il 5 settembre in Thailandia e il 9 maggio negli Stati
    # Uniti: senza una convenzione fissa un dividendo su due finisce nel mese
    # sbagliato. Qui il contesto e' thailandese, quindi il giorno viene prima,
    # tranne quando la data e' in formato ISO e non c'e' ambiguita'.
    iso = bool(_ISO.match(testo))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            data = pd.to_datetime(testo, dayfirst=not iso, errors="raise")
        except (ValueError, TypeError, OverflowError):
            return None
    data = pd.Timestamp(data)
    if data.tzinfo is not None:
        data = data.tz_localize(None)
    # Una data di stacco fuori da questa finestra e' un campo sbagliato.
    if pd.Timestamp("1990-01-01") <= data <= pd.Timestamp.now() + pd.Timedelta(days=400):
        return data.normalize()
    return None


def _to_amount(valore: Any) -> Optional[float]:
    """Numero, anche scritto come testo con virgola decimale o simboli."""
    if valore is None or isinstance(valore, bool):
        return None
    if isinstance(valore, (int, float)):
        numero = float(valore)
    else:
        pulito = re.sub(r"[^\d.,\-]", "", str(valore))
        if not pulito:
            return None
        # "1.234,56" (europeo) contro "1,234.56" (anglosassone)
        if "," in pulito and "." in pulito:
            pulito = (pulito.replace(".", "").replace(",", ".")
                      if pulito.rfind(",") > pulito.rfind(".")
                      else pulito.replace(",", ""))
        elif "," in pulito:
            pulito = pulito.replace(",", ".")
        try:
            numero = float(pulito)
        except ValueError:
            return None
    if numero != numero or not (DPS_MIN <= numero <= DPS_MAX):
        return None
    return numero


def _cerca_chiave(record: dict, candidate: Iterable[str]) -> Optional[Any]:
    """Prima chiave presente nel record, ignorando maiuscole e separatori."""
    normalizzato = {re.sub(r"[^a-z0-9]", "", k.lower()): v for k, v in record.items()}
    for nome in candidate:
        chiave = re.sub(r"[^a-z0-9]", "", nome.lower())
        if chiave in normalizzato and normalizzato[chiave] is not None:
            return normalizzato[chiave]
    return None


def parse_dividend_records(dati: Any, *, solo_contanti: bool = True) -> Optional[pd.Series]:
    """Estrae (data, importo) da un JSON di forma non nota a priori.

    Serve perche' le fonti cambiano interfaccia senza avvisare: invece di
    assumere una struttura, cerchiamo in profondita' i record che hanno
    insieme qualcosa che somiglia a una data e qualcosa che somiglia a un
    importo per azione. Se la forma cambia ma i nomi dei campi restano
    riconoscibili, continua a funzionare.
    """
    raccolti: dict[pd.Timestamp, float] = {}

    def visita(nodo: Any) -> None:
        if isinstance(nodo, dict):
            data = _to_date(_cerca_chiave(nodo, CHIAVI_DATA))
            importo = _to_amount(_cerca_chiave(nodo, CHIAVI_IMPORTO))
            if data is not None and importo is not None:
                if solo_contanti and _e_dividendo_in_azioni(nodo):
                    pass  # gli stock dividend non sono cassa: li ignoriamo
                else:
                    # Piu' stacchi nello stesso giorno si sommano.
                    raccolti[data] = raccolti.get(data, 0.0) + importo
            for valore in nodo.values():
                if isinstance(valore, (dict, list)):
                    visita(valore)
        elif isinstance(nodo, list):
            for elemento in nodo:
                visita(elemento)

    visita(dati)
    if not raccolti:
        return None
    return pd.Series(raccolti).sort_index()


def _e_dividendo_in_azioni(record: dict) -> bool:
    """Riconosce gli stock dividend, che non sono un pagamento in contanti."""
    testo = " ".join(str(v) for v in record.values() if isinstance(v, str)).lower()
    return any(parola in testo for parola in ("stock dividend", "share dividend", "หุ้นปันผล"))


def clean_series(serie: Optional[pd.Series], *, symbol: str = "") -> Optional[pd.Series]:
    """Ripulisce una serie di dividendi: date valide, importi plausibili, ordine."""
    if serie is None or len(serie) == 0:
        return None
    valori = pd.to_numeric(pd.Series(serie), errors="coerce").dropna()
    if valori.empty:
        return None
    try:
        indice = pd.to_datetime(valori.index)
    except (TypeError, ValueError):
        return None
    valori = pd.Series(valori.values, index=indice)
    if getattr(valori.index, "tz", None) is not None:
        valori.index = valori.index.tz_localize(None)
    valori = valori[(valori > 0) & (valori <= DPS_MAX)]
    valori = valori.groupby(valori.index.normalize()).sum().sort_index()
    return valori if not valori.empty else None


# --------------------------------------------------------------------------
# registro delle fonti
# --------------------------------------------------------------------------
@dataclass
class SourceSpec:
    key: str
    label: str
    trust: int
    env_key: Optional[str]          # variabile d'ambiente con la chiave API
    loader: Callable[[str], Optional[pd.Series]]
    note: str = ""

    @property
    def needs_key(self) -> bool:
        return self.env_key is not None

    @property
    def available(self) -> bool:
        return not self.needs_key or bool(os.environ.get(self.env_key))


def _registro() -> list[SourceSpec]:
    """Import ritardato: ogni fonte tira dentro solo cio' che le serve."""
    from setxray.sources import alphavantage, csvfile, eodhd, fmp, setofficial, yahoo

    return [
        SourceSpec("set", "SET (sito ufficiale)", 5, None, setofficial.dividends,
                   "fonte autorevole; interfaccia pubblica non documentata, "
                   "verificane l'esito al primo uso"),
        SourceSpec("csv", "File CSV locale", 5, None, csvfile.dividends,
                   "dati/<SIMBOLO>-dividendi.csv con colonne data,importo"),
        SourceSpec("eodhd", "EOD Historical Data", 4, "EODHD_API_KEY", eodhd.dividends),
        SourceSpec("fmp", "Financial Modeling Prep", 3, "FMP_API_KEY", fmp.dividends),
        SourceSpec("alphavantage", "Alpha Vantage", 3, "ALPHAVANTAGE_API_KEY",
                   alphavantage.dividends),
        SourceSpec("yahoo", "Yahoo Finance", 2, None, yahoo.dividends,
                   "sempre disponibile, ma sui titoli SET puo' saltare stacchi"),
    ]


def describe_sources() -> list[dict[str, Any]]:
    """Elenco delle fonti con stato, per l'interfaccia e la documentazione."""
    return [{
        "chiave": spec.key,
        "fonte": spec.label,
        "fiducia": spec.trust,
        "chiave_api": spec.env_key or "non serve",
        "attiva": spec.available,
        "nota": spec.note,
    } for spec in _registro()]


def available_sources() -> list[str]:
    return [spec.key for spec in _registro() if spec.available]


def requested_sources() -> Optional[list[str]]:
    """Fonti richieste con SETXRAY_SOURCES, per interrogarne solo alcune.

    Esempio: SETXRAY_SOURCES=csv,yahoo evita ogni chiamata di rete lenta.
    """
    grezzo = os.environ.get("SETXRAY_SOURCES", "").strip()
    if not grezzo:
        return None
    chiavi = {spec.key for spec in _registro()}
    return [pezzo.strip() for pezzo in grezzo.split(",")
            if pezzo.strip() in chiavi]


# --------------------------------------------------------------------------
# raccolta e confronto
# --------------------------------------------------------------------------
def collect_dividends(symbol: str, *, only: Optional[Iterable[str]] = None,
                      fallback: Optional[pd.Series] = None) -> DividendSet:
    """Interroga tutte le fonti disponibili e scegli la storia migliore.

    `fallback` e' una serie gia' in mano al chiamante (tipicamente quella di
    Yahoo, scaricata insieme al resto): viene trattata come una fonte in piu',
    cosi' non la si scarica due volte.
    """
    insieme = DividendSet(symbol=symbol)
    richieste = set(only) if only is not None else None

    if fallback is not None:
        pulita = clean_series(fallback, symbol=symbol)
        insieme.results.append(SourceResult(
            "yahoo", "Yahoo Finance", 2, series=pulita,
            error=None if pulita is not None else "nessun dividendo nello storico",
            note="scaricata con i prezzi",
        ))

    for spec in _registro():
        if richieste is not None and spec.key not in richieste:
            continue
        if any(r.key == spec.key for r in insieme.results):
            continue  # gia' fornita dal chiamante
        if not spec.available:
            insieme.results.append(SourceResult(
                spec.key, spec.label, spec.trust,
                error=f"manca la chiave API ({spec.env_key})", note=spec.note))
            continue
        try:
            serie = clean_series(spec.loader(symbol), symbol=symbol)
        except Exception as errore:
            insieme.results.append(SourceResult(
                spec.key, spec.label, spec.trust,
                error=f"{type(errore).__name__}: {errore}", note=spec.note))
            continue
        insieme.results.append(SourceResult(
            spec.key, spec.label, spec.trust, series=serie,
            error=None if serie is not None else "nessun dividendo restituito",
            note=spec.note))

    funzionanti = insieme.working_sources()
    if not funzionanti:
        insieme.notes.append(
            "Nessuna fonte ha restituito dividendi per questo titolo. Puo' essere un "
            "titolo che non distribuisce, oppure un problema di rete o di simbolo."
        )
        return insieme

    # Scelta: la storia piu' lunga; a pari lunghezza vince la fonte piu'
    # autorevole, poi quella con piu' stacchi registrati.
    migliore = max(funzionanti, key=lambda r: (round(r.span_years, 1), r.trust, r.payments))
    insieme.series = migliore.series
    insieme.chosen = migliore.key
    insieme.disagreements = _confronta(funzionanti, migliore)
    if len(funzionanti) == 1:
        insieme.notes.append(
            f"Una sola fonte disponibile ({migliore.label}): i dividendi non sono "
            "stati verificati contro nessun altro archivio."
        )
    return insieme


def _confronta(risultati: list[SourceResult], scelta: SourceResult) -> list[str]:
    """Confronta anno per anno la fonte scelta con le altre.

    Non tentiamo di riconciliare: segnaliamo. Su un dato come il dividendo,
    sapere che due archivi non concordano vale piu' di una media fra i due.
    """
    avvisi: list[str] = []
    per_anno_scelta = scelta.series.groupby(scelta.series.index.year).sum()
    for risultato in risultati:
        if risultato.key == scelta.key:
            continue
        per_anno = risultato.series.groupby(risultato.series.index.year).sum()
        comuni = per_anno_scelta.index.intersection(per_anno.index)
        if len(comuni) == 0:
            continue
        # Differenza di scala sistematica: quasi sempre baht contro satang.
        rapporti = (per_anno_scelta[comuni] / per_anno[comuni]).replace(
            [float("inf"), float("-inf")], pd.NA).dropna()
        if len(rapporti) >= 3 and (rapporti.between(95, 105).mean() > 0.6
                                   or rapporti.between(0.0095, 0.0105).mean() > 0.6):
            avvisi.append(
                f"{risultato.label} riporta importi in scala diversa (fattore ~100): "
                "probabile confusione fra baht e satang. Controlla quale delle due "
                "corrisponde al sito della SET."
            )
            continue
        discordanti = [int(anno) for anno in comuni
                       if abs(per_anno_scelta[anno] - per_anno[anno])
                       > 0.05 * max(abs(per_anno_scelta[anno]), 1e-9)]
        if discordanti:
            elenco = ", ".join(str(a) for a in sorted(discordanti)[:6])
            avvisi.append(
                f"{risultato.label} non concorda con {scelta.label} su {len(discordanti)} "
                f"anni ({elenco}): differenza oltre il 5%."
            )
    return avvisi
