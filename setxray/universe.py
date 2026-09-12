"""L'elenco dei titoli quotati alla SET: tutti, non i sedici che conosco io.

Il resto dello strumento analizza un simbolo alla volta e non ha bisogno di
sapere quali esistono. Serve all'interfaccia, per far scegliere da un elenco
invece di far indovinare una sigla, e serve a chiunque voglia passare in
rassegna il mercato.

Come per i dividendi, non c'e' una fonte sola di cui fidarsi: la SET non
documenta la propria interfaccia pubblica e Yahoo cambia i suoi filtri senza
avvisare. Quindi tre strade indipendenti, in ordine di fiducia, e una che
funziona sempre:

    1. il sito ufficiale della SET, che e' l'arbitro;
    2. lo screener di Yahoo filtrato sulla borsa thailandese;
    3. un CSV locale - data/set-symbols.csv - che non dipende da nessuna API.

Se cadono tutte e tre resta l'elenco dei titoli molto scambiati che sta in
`datasource`: sedici nomi, dichiarati come tali. Un elenco corto e vero e'
meglio di un elenco lungo e inventato.

L'elenco cambia di rado - qualche quotazione nuova al mese - quindi la cache
su disco dura una settimana: nessuno vuole aspettare una chiamata di rete per
aprire un menu a tendina.
"""

from __future__ import annotations

import csv
import io
import os
import pickle
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

from setxray.datasource import _CACHE_DIR, normalize_symbol, popular_set_symbols
from setxray.lang import L
from setxray.sources.http import FetchError, get_json

# Una settimana: le quotazioni nuove sono poche, e un elenco vecchio di sette
# giorni sbaglia meno di una chiamata di rete che non arriva.
CACHE_TTL_ORE = 24 * 7
CACHE_FILE = "set-universe.pkl"

# Alla SET sono quotate centinaia di societa'. Un elenco piu' corto di cosi'
# puo' essere legittimo - la lista dei propri titoli in un CSV - ma non e' il
# mercato, e va detto: chi non lo sapesse penserebbe che la SET e' quella.
SOGLIA_MERCATO = 100

# Dove cercare il CSV, nell'ordine. Gli stessi posti del CSV dei dividendi,
# cosi' chi ne usa uno sa dov'e' l'altro.
CARTELLE_CSV = ("data", "dati", os.path.join(os.path.expanduser("~"), ".setxray"))
NOMI_CSV = ("set-symbols.csv", "set-simboli.csv")

# Il sito della SET non documenta queste vie: proviamo quelle note, la prima
# che risponde con qualcosa di riconoscibile vince.
URL_SET = (
    "https://www.set.or.th/api/set/stock/list",
    "https://www.set.or.th/api/set/stock/list?securityType=S",
    "https://www.set.or.th/api/set/index/sSET/composition",
)


@dataclass
class Titolo:
    """Un titolo quotato: la sigla, il nome, e dove sta."""

    symbol: str
    name: str = ""
    sector: str = ""
    market: str = ""          # SET o mai (Market for Alternative Investment)

    def etichetta(self) -> str:
        """Come si legge in un elenco: 'PTT - PTT Public Company Limited'."""
        return f"{self.symbol} - {self.name}" if self.name else self.symbol


@dataclass
class Universo:
    """L'elenco, piu' il racconto di come e' stato ottenuto."""

    titoli: list[Titolo] = field(default_factory=list)
    fonte: str = ""
    parziale: bool = False     # vero quando e' la riserva corta, non il mercato
    note: list[str] = field(default_factory=list)
    da_cache: bool = False

    def __len__(self) -> int:
        return len(self.titoli)

    def simboli(self) -> list[str]:
        return [t.symbol for t in self.titoli]

    def cerca(self, testo: str, limite: int = 50) -> list[Titolo]:
        """I titoli che corrispondono, sigla prima e nome dopo.

        Chi scrive "ptt" vuole PTT in cima, non PTTEP ne' un'azienda che ha
        "ptt" in mezzo al nome: quindi prima le sigle che cominciano cosi',
        poi le sigle che lo contengono, poi i nomi.
        """
        if not testo:
            return self.titoli[:limite]
        cercato = testo.strip().upper()
        inizio_sigla, dentro_sigla, dentro_nome = [], [], []
        for titolo in self.titoli:
            if titolo.symbol.startswith(cercato):
                inizio_sigla.append(titolo)
            elif cercato in titolo.symbol:
                dentro_sigla.append(titolo)
            elif cercato in titolo.name.upper():
                dentro_nome.append(titolo)
        return (inizio_sigla + dentro_sigla + dentro_nome)[:limite]

    def provenienza(self) -> str:
        pezzi = [L(f"{len(self.titoli)} symbols from {self.fonte}",
                    f"{len(self.titoli)} simboli da {self.fonte}")]
        if self.da_cache:
            pezzi.append(L("from local cache", "da cache locale"))
        if self.parziale:
            pezzi.append(L("a short fallback list, not the whole market",
                           "elenco di riserva, non tutto il mercato"))
        return " · ".join(pezzi)


# --------------------------------------------------------------------------
# le tre strade
# --------------------------------------------------------------------------
def _pulisci(simbolo: object) -> Optional[str]:
    """Da un campo qualsiasi a un simbolo SET, o niente."""
    if simbolo is None:
        return None
    testo = str(simbolo).strip().upper()
    if not testo or len(testo) > 12:
        return None
    try:
        base, _ = normalize_symbol(testo)
    except ValueError:
        return None
    # Una sigla SET e' fatta di lettere, cifre e qualche punto: tutto il resto
    # e' un'intestazione di colonna o una riga di commento finita qui.
    if not all(c.isalnum() or c in ".-&" for c in base):
        return None
    return base


def _campo(riga: dict, *nomi: str) -> str:
    """Il primo campo presente fra quelli proposti, letto in modo difensivo."""
    for nome in nomi:
        for chiave in (nome, nome.lower(), nome.upper()):
            if isinstance(riga, dict) and riga.get(chiave) not in (None, ""):
                return str(riga[chiave]).strip()
    return ""


def _da_json_set(dati: object) -> list[Titolo]:
    """Riconosce l'elenco dentro una risposta della SET, qualunque forma abbia."""
    # Le risposte viste hanno la lista sotto una chiave diversa a seconda
    # dell'endpoint: si prova a trovarla invece di darla per scontata.
    candidate: Iterable = ()
    if isinstance(dati, list):
        candidate = dati
    elif isinstance(dati, dict):
        for chiave in ("securitySymbols", "stocks", "securities", "data",
                       "composition", "items", "list"):
            valore = dati.get(chiave)
            if isinstance(valore, list) and valore:
                candidate = valore
                break
    fuori: list[Titolo] = []
    visti: set[str] = set()
    for voce in candidate:
        if not isinstance(voce, dict):
            simbolo = _pulisci(voce)
            if simbolo and simbolo not in visti:
                visti.add(simbolo)
                fuori.append(Titolo(symbol=simbolo))
            continue
        simbolo = _pulisci(_campo(voce, "symbol", "securitySymbol", "ticker", "name_en"))
        if not simbolo or simbolo in visti:
            continue
        visti.add(simbolo)
        fuori.append(Titolo(
            symbol=simbolo,
            name=_campo(voce, "nameEN", "name_en", "companyName", "securityName", "name"),
            sector=_campo(voce, "sectorName", "sector", "industryName", "industry"),
            market=_campo(voce, "market", "marketName") or "SET",
        ))
    return fuori


# Tre indirizzi da provare a dodici secondi l'uno fanno trentasei secondi di
# attesa nel caso peggiore, e questa chiamata sta dietro un pulsante che
# qualcuno ha appena premuto. Otto secondi bastano a un sito che risponde.
TIMEOUT_SET = 8


def dal_sito_set() -> tuple[list[Titolo], str]:
    """Strada 1: il sito ufficiale. E' l'arbitro, quando risponde."""
    errori = []
    for url in URL_SET:
        try:
            titoli = _da_json_set(get_json(url, timeout=TIMEOUT_SET))
        except FetchError as errore:
            errori.append(f"{url.rsplit('/', 1)[-1]}: {errore}")
            continue
        if len(titoli) >= 50:      # meno di cosi' non e' il listino
            return titoli, L("SET (official website)", "SET (sito ufficiale)")
        errori.append(L(f"{url.rsplit('/', 1)[-1]}: {len(titoli)} symbols recognised, too few",
                        f"{url.rsplit('/', 1)[-1]}: {len(titoli)} simboli riconosciuti, troppo pochi"))
    raise FetchError("; ".join(errori[:3]) or L("no endpoint answered",
                                                "nessun indirizzo ha risposto"))


def da_yahoo(pagine: int = 8, per_pagina: int = 250) -> tuple[list[Titolo], str]:
    """Strada 2: lo screener di Yahoo, filtrato sulla borsa thailandese.

    Yahoo risponde a pagine: si chiede finche' ne arrivano, con un tetto per
    non restare appesi se il filtro cambia significato e inizia a ritornare
    tutto il pianeta. Otto pagine da 250 fanno duemila titoli, e alla SET ne
    sono quotati meno di mille: se servissero piu' pagine vorrebbe dire che il
    filtro non filtra piu'.
    """
    import yfinance as yf

    filtro = yf.EquityQuery("and", [
        yf.EquityQuery("eq", ["region", "th"]),
        yf.EquityQuery("is-in", ["exchange", "SET"]),
    ])
    titoli: list[Titolo] = []
    visti: set[str] = set()
    for pagina in range(pagine):
        try:
            risposta = yf.screen(filtro, offset=pagina * per_pagina, size=per_pagina)
        except Exception as errore:
            if titoli:
                break              # abbiamo gia' qualcosa: meglio parziale che niente
            raise FetchError(f"{type(errore).__name__}: {errore}") from errore
        quotes = (risposta or {}).get("quotes") or []
        if not quotes:
            break
        for voce in quotes:
            simbolo = _pulisci(_campo(voce, "symbol"))
            if not simbolo or simbolo in visti:
                continue
            visti.add(simbolo)
            titoli.append(Titolo(
                symbol=simbolo,
                name=_campo(voce, "longName", "shortName", "displayName"),
                sector=_campo(voce, "sector", "sectorDisp"),
                market=_campo(voce, "fullExchangeName", "exchange") or "SET",
            ))
        if len(quotes) < per_pagina:
            break
    if not titoli:
        raise FetchError(L("the screener returned no Thai stock",
                           "lo screener non ha restituito nessun titolo thailandese"))
    return titoli, "Yahoo Finance"


def percorsi_csv() -> list[str]:
    fuori = []
    dalla_variabile = os.environ.get("SETXRAY_SYMBOLS_CSV")
    if dalla_variabile:
        fuori.append(dalla_variabile)
    for cartella in CARTELLE_CSV:
        for nome in NOMI_CSV:
            fuori.append(os.path.join(cartella, nome))
    return fuori


def dal_csv(percorso: Optional[str] = None) -> tuple[list[Titolo], str]:
    """Strada 3: un file locale. Non dipende da nessuna API, quindi non scade.

    Formato: una colonna con la sigla, facoltativamente nome e settore.
    L'intestazione e' libera purche' riconoscibile, e si accetta anche un
    file con la sola sigla per riga.
    """
    candidati = [percorso] if percorso else percorsi_csv()
    for via in candidati:
        if not via or not os.path.exists(via):
            continue
        with open(via, "r", encoding="utf-8-sig", errors="replace") as fh:
            testo = fh.read()
        titoli = _da_testo_csv(testo)
        if titoli:
            return titoli, L(f"local CSV file ({via})", f"file CSV locale ({via})")
    raise FetchError(L("no CSV file found", "nessun file CSV trovato"))


def _da_testo_csv(testo: str) -> list[Titolo]:
    if not testo.strip():
        return []
    # Il separatore lo decide il file: il punto e virgola e' comune quando il
    # CSV nasce da un Excel italiano o thailandese.
    prima = testo.splitlines()[0]
    separatore = ";" if prima.count(";") > prima.count(",") else ","
    righe = list(csv.reader(io.StringIO(testo), delimiter=separatore))
    if not righe:
        return []
    intestazione = [c.strip().lower() for c in righe[0]]
    colonne = {"symbol": 0, "name": None, "sector": None}
    corpo = righe
    if any(c in intestazione for c in ("symbol", "simbolo", "ticker", "sigla")):
        corpo = righe[1:]
        for indice, nome in enumerate(intestazione):
            if nome in ("symbol", "simbolo", "ticker", "sigla"):
                colonne["symbol"] = indice
            elif nome in ("name", "nome", "company", "società", "societa", "nameen"):
                colonne["name"] = indice
            elif nome in ("sector", "settore", "industry", "industria"):
                colonne["sector"] = indice
    fuori, visti = [], set()
    for riga in corpo:
        if not riga:
            continue
        simbolo = _pulisci(riga[colonne["symbol"]] if len(riga) > colonne["symbol"] else None)
        if not simbolo or simbolo in visti:
            continue
        visti.add(simbolo)
        def prendi(chiave: str) -> str:
            indice = colonne[chiave]
            return riga[indice].strip() if indice is not None and len(riga) > indice else ""
        fuori.append(Titolo(symbol=simbolo, name=prendi("name"), sector=prendi("sector")))
    return fuori


def di_riserva() -> tuple[list[Titolo], str]:
    """L'ultima spiaggia: i titoli molto scambiati che stanno nel codice."""
    return ([Titolo(symbol=codice, name=descrizione)
             for codice, descrizione in popular_set_symbols()],
            L("built-in short list", "elenco corto incluso nel codice"))


# --------------------------------------------------------------------------
# cache su disco
# --------------------------------------------------------------------------
def _percorso_cache() -> str:
    return os.path.join(_CACHE_DIR, CACHE_FILE)


def _leggi_cache(ttl_ore: float) -> Optional[Universo]:
    if ttl_ore <= 0:
        return None
    via = _percorso_cache()
    try:
        if not os.path.exists(via) or time.time() - os.path.getmtime(via) > ttl_ore * 3600:
            return None
        with open(via, "rb") as fh:
            universo = pickle.load(fh)
    except Exception:
        return None
    if isinstance(universo, Universo) and universo.titoli:
        universo.da_cache = True
        return universo
    return None


def _scrivi_cache(universo: Universo) -> None:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        tmp = _percorso_cache() + ".tmp"
        with open(tmp, "wb") as fh:
            pickle.dump(universo, fh)
        os.replace(tmp, _percorso_cache())
    except Exception:
        pass  # una cache che non scrive non deve far fallire niente


# --------------------------------------------------------------------------
# l'ingresso pubblico
# --------------------------------------------------------------------------
def load_universe(*, ttl_ore: float = CACHE_TTL_ORE, only: Optional[list[str]] = None,
                  offline: bool = False) -> Universo:
    """L'elenco dei titoli SET, dalla prima strada che risponde.

    `offline=True` prova solo le strade che non aspettano la rete - la cache su
    disco e il CSV - e poi si arrende all'elenco corto. Serve a chi disegna una
    pagina: interrogare la SET e lo screener di Yahoo puo' costare decine di
    secondi, e nessuno deve aspettarli per vedere apparire un menu.

    `only` limita le strade da provare ("set", "yahoo", "csv", "builtin") e
    serve ai test e a chi vuole forzare una fonte. Il CSV viene provato prima
    delle API: se qualcuno lo ha messo li', e' perche' si fida di quello.
    """
    dalla_cache = _leggi_cache(ttl_ore) if only is None else None
    if dalla_cache is not None:
        return dalla_cache

    strade = [("csv", dal_csv), ("set", dal_sito_set), ("yahoo", da_yahoo)]
    if offline:
        strade = [(nome, fn) for nome, fn in strade if nome == "csv"]
    if only is not None:
        strade = [(nome, fn) for nome, fn in strade if nome in only]

    note = []
    for nome, funzione in strade:
        try:
            titoli, etichetta = funzione()
        except FetchError as errore:
            note.append(L(f"{nome}: {errore}", f"{nome}: {errore}"))
            continue
        except Exception as errore:                      # una fonte non deve rompere l'app
            note.append(f"{nome}: {type(errore).__name__}: {errore}")
            continue
        universo = Universo(titoli=_ordina(titoli), fonte=etichetta, note=note,
                            parziale=len(titoli) < SOGLIA_MERCATO)
        if universo.parziale:
            universo.note.append(L(
                f"{len(titoli)} symbols only: this is not the whole market.",
                f"Solo {len(titoli)} simboli: questo non e' tutto il mercato."))
        # Una chiamata che forza una fonte non deve sporcare la cache condivisa:
        # serve a provare o a indagare, e il risultato non vale per tutti.
        if only is None:
            _scrivi_cache(universo)
        return universo

    if only is not None and "builtin" not in only:
        return Universo(titoli=[], fonte="", parziale=True, note=note)
    titoli, etichetta = di_riserva()
    if offline:
        note.append(L("The full list has not been fetched yet. The symbol box accepts any SET "
                      "ticker in the meantime.",
                      "L'elenco completo non e' ancora stato scaricato. Intanto la casella del "
                      "simbolo accetta qualunque sigla della SET."))
    else:
        note.append(L("No source answered: falling back to the built-in short list. The symbol "
                      "box still accepts any SET ticker.",
                      "Nessuna fonte ha risposto: si usa l'elenco corto incluso. La casella del "
                      "simbolo accetta comunque qualunque sigla della SET."))
    return Universo(titoli=_ordina(titoli), fonte=etichetta, parziale=True, note=note)


def _ordina(titoli: list[Titolo]) -> list[Titolo]:
    """I molto scambiati in cima, il resto in ordine alfabetico.

    Chi apre l'elenco cerca quasi sempre uno dei grossi: metterli in testa
    risparmia la ricerca nel caso frequente, senza nascondere gli altri.
    """
    popolari = [codice for codice, _ in popular_set_symbols()]
    rango = {codice: posizione for posizione, codice in enumerate(popolari)}
    return sorted(titoli, key=lambda t: (rango.get(t.symbol, len(rango)), t.symbol))


def salva_csv(universo: Universo, percorso: str) -> int:
    """Scrive l'elenco in un CSV, per averlo anche senza rete.

    E' la mossa che rende l'elenco indipendente da qualunque API: si scarica
    una volta, si mette nel repository, e da quel momento l'app parte con il
    mercato intero anche se domani la SET cambia interfaccia.
    """
    cartella = os.path.dirname(os.path.abspath(percorso))
    os.makedirs(cartella, exist_ok=True)
    with open(percorso, "w", encoding="utf-8", newline="") as fh:
        scrittore = csv.writer(fh)
        scrittore.writerow(["symbol", "name", "sector", "market"])
        for titolo in universo.titoli:
            scrittore.writerow([titolo.symbol, titolo.name, titolo.sector, titolo.market])
    return len(universo.titoli)
