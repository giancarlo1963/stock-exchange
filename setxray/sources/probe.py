"""Prova gli indirizzi delle fonti e dice cosa risponde, uno per uno.

Serve a un problema preciso. Ne' la SET ne' Settrade pubblicano un'API
documentata per uso esterno: gli indirizzi che questo strumento prova sono
quelli con cui i loro siti riempiono le proprie pagine, e nessuno garantisce
che restino dov'erano. Chi ha scritto il codice, poi, puo' non avere la rete
verso quei siti - e' esattamente il caso in cui `setofficial.py` e
`settrade.py` sono nati - e allora non e' in grado di verificare niente.

Chi *puo'* verificare e' chi fa girare l'app, perche' la sua macchina quei
siti li raggiunge. Questo modulo gli mette in mano una sonda: prova ogni
indirizzo e riporta, per ciascuno, il codice HTTP, il tipo di risposta e se i
dividendi sono stati riconosciuti. Tre esiti, tre significati diversi:

- *irraggiungibile*: non e' un problema di indirizzo, e' la rete;
- *risponde HTML*: quell'indirizzo e' una pagina, non un'API - indirizzo
  sbagliato;
- *JSON che non riconosco*: l'indirizzo e' quello giusto e il lettore va
  adeguato. In questo caso la sonda stampa anche la forma del JSON (le chiavi
  in cima, le chiavi del primo record), che e' tutto quello che serve per
  scrivere il lettore.

Chiude il cerchio `prova_indirizzo`: si incolla un indirizzo trovato con la
scheda Rete del proprio browser e si sa subito se l'app lo sa leggere. Se
funziona, lo si fissa con SETXRAY_SET_API o SETXRAY_SETTRADE_API e la fonte
diventa buona senza cambiare una riga di codice.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from setxray.lang import L, plural
from setxray.sources.base import parse_dividend_records
from setxray.sources.http import USER_AGENT

TIMEOUT_SONDA = 8
# Il corpo va letto intero, non a morsi: un JSON valido tagliato a meta' non si
# parsa, e la sonda direbbe "non e' JSON" di una risposta buona. Il tetto e'
# solo contro una risposta senza fine; se lo si raggiunge la sonda lo dice
# invece di dare la colpa al formato.
LIMITE = 8_000_000


@dataclass
class Esito:
    """Com'e' andato un singolo indirizzo."""

    source: str
    url: str
    stato: str                       # chiave stabile, non testo da leggere
    dettaglio: str
    dividendi: int = 0
    millisecondi: int = 0
    forma: str = ""                  # chiavi del JSON, quando non lo riconosciamo
    campione: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.stato == "ok"

    def riga(self) -> dict[str, Any]:
        """Per una tabella: chiavi in inglese, testi nella lingua attiva."""
        return {
            L("Source", "Fonte"): self.source,
            L("Endpoint", "Indirizzo"): self.url,
            L("Outcome", "Esito"): STATI[self.stato](),
            L("Dividends", "Dividendi"): self.dividendi or "",
            L("ms", "ms"): self.millisecondi,
            L("Detail", "Dettaglio"): self.dettaglio,
        }


# I testi degli esiti sono funzioni perche' la lingua si decide a ogni lettura,
# non all'import del modulo.
STATI = {
    "ok": lambda: L("works", "funziona"),
    "unrecognised": lambda: L("JSON not recognised", "JSON non riconosciuto"),
    "html": lambda: L("answers, but not JSON", "risponde, ma non JSON"),
    "http": lambda: L("HTTP error", "errore HTTP"),
    "unreachable": lambda: L("unreachable", "irraggiungibile"),
    "empty": lambda: L("empty response", "risposta vuota"),
    "troppo-grande": lambda: L("answers, too large to check",
                               "risponde, troppo grande per controllarla"),
}


def _chiavi(dato: Any, limite: int = 12) -> str:
    """La forma di un JSON in una riga: nomi, non valori."""
    if isinstance(dato, dict):
        nomi = list(dato.keys())[:limite]
        return "{" + ", ".join(str(n) for n in nomi) + ("...}" if len(dato) > limite else "}")
    if isinstance(dato, list):
        if not dato:
            return "[]"
        return f"[{len(dato)} x {_chiavi(dato[0], limite)}]"
    return type(dato).__name__


def prova_indirizzo(url: str, *, source: str = "?", timeout: int = TIMEOUT_SONDA) -> Esito:
    """Un GET, e la lettura di cosa e' tornato.

    Non passa da `get_json` perche' qui interessa anche cio' che `get_json`
    considera un fallimento: un HTML e un 404 dicono due cose diverse, e la
    differenza e' tutto quello che si vuole sapere.
    """
    richiesta = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en,th;q=0.8",
    })
    partenza = time.monotonic()
    try:
        with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:
            corpo = risposta.read(LIMITE)
            tipo = risposta.headers.get("Content-Type", "?")
            codice = risposta.status
    except urllib.error.HTTPError as errore:
        return Esito(source, url, "http", f"HTTP {errore.code} {errore.reason}",
                     millisecondi=int((time.monotonic() - partenza) * 1000))
    except Exception as errore:
        return Esito(source, url, "unreachable", f"{type(errore).__name__}: {errore}",
                     millisecondi=int((time.monotonic() - partenza) * 1000))
    millisecondi = int((time.monotonic() - partenza) * 1000)

    if not corpo:
        return Esito(source, url, "empty", f"HTTP {codice}, {L('no body', 'corpo vuoto')}",
                     millisecondi=millisecondi)
    testo = corpo.decode("utf-8", errors="replace")
    try:
        dato = json.loads(testo)
    except json.JSONDecodeError:
        inizio = testo.lstrip()[:40].replace("\n", " ")
        if len(corpo) >= LIMITE:
            return Esito(source, url, "troppo-grande",
                         L(f"HTTP {codice}, {tipo}, over {LIMITE // 1_000_000} MB: not checked",
                           f"HTTP {codice}, {tipo}, oltre {LIMITE // 1_000_000} MB: non "
                           "controllata"),
                         millisecondi=millisecondi)
        return Esito(source, url, "html", f"HTTP {codice}, {tipo}, \"{inizio}...\"",
                     millisecondi=millisecondi)

    serie = parse_dividend_records(dato)
    if serie is not None and not serie.empty:
        primo, ultimo = serie.index.min().date(), serie.index.max().date()
        return Esito(source, url, "ok",
                     L(f"HTTP {codice}, {len(serie)} payments from {primo} to {ultimo}",
                       f"HTTP {codice}, {len(serie)} stacchi dal {primo} al {ultimo}"),
                     dividendi=len(serie), millisecondi=millisecondi,
                     forma=_chiavi(dato))
    # Il caso piu' utile di tutti: l'indirizzo c'e', il lettore no. La forma del
    # JSON e le chiavi del primo record sono quello che serve per scriverlo.
    dentro = dato
    if isinstance(dentro, dict):
        for chiave in ("data", "result", "results", "items", "rightsBenefits", "dividends"):
            if isinstance(dentro.get(chiave), (list, dict)):
                dentro = dentro[chiave]
                break
    campione: list[str] = []
    if isinstance(dentro, list) and dentro and isinstance(dentro[0], dict):
        campione = [str(k) for k in dentro[0].keys()][:20]
    return Esito(source, url, "unrecognised",
                 L(f"HTTP {codice}, JSON with no dividend this reader understands",
                   f"HTTP {codice}, JSON senza dividendi che questo lettore capisca"),
                 millisecondi=millisecondi, forma=_chiavi(dato), campione=campione)


def indirizzi(source: str, symbol: str) -> list[str]:
    """Gli indirizzi che una fonte proverebbe per quel titolo."""
    from setxray.datasource import normalize_symbol

    from setxray.sources import setofficial, settrade

    set_symbol, _ = normalize_symbol(symbol)
    modulo = {"set": setofficial, "settrade": settrade}.get(source)
    if modulo is None:
        return []
    return [modello.format(symbol=set_symbol) for modello in modulo.endpoints()]


def probe(symbol: str, sources: tuple[str, ...] = ("set", "settrade"), *,
          timeout: int = TIMEOUT_SONDA, fermati_al_primo: bool = False) -> list[Esito]:
    """Prova tutti gli indirizzi delle fonti indicate.

    `fermati_al_primo` serve a chi vuole solo sapere *se* una strada funziona;
    per capire il resto conviene invece provarli tutti, perche' un 404 su tre
    indirizzi e un 200 sul quarto e' un'informazione diversa da quattro 404.
    """
    esiti: list[Esito] = []
    for source in sources:
        for url in indirizzi(source, symbol):
            esito = prova_indirizzo(url, source=source, timeout=timeout)
            esiti.append(esito)
            if esito.ok and fermati_al_primo:
                return esiti
    return esiti


def riassunto(esiti: list[Esito]) -> str:
    """Una riga per fonte: la conclusione, non i dettagli."""
    if not esiti:
        return L("no endpoint to try", "nessun indirizzo da provare")
    righe = []
    for source in dict.fromkeys(e.source for e in esiti):
        suoi = [e for e in esiti if e.source == source]
        buoni = [e for e in suoi if e.ok]
        if buoni:
            righe.append(L(f"{source}: works - {buoni[0].url}",
                           f"{source}: funziona - {buoni[0].url}"))
            continue
        parlanti = [e for e in suoi if e.stato == "unrecognised"]
        if parlanti:
            quanti = f"{len(parlanti)} " + plural(
                len(parlanti), L("endpoint answers", "indirizzo risponde"),
                L("endpoints answer", "indirizzi rispondono"))
            righe.append(
                L(f"{source}: {quanti} JSON but this reader does not recognise the dividends "
                  f"- shape {parlanti[0].forma}",
                  f"{source}: {quanti} JSON ma questo lettore non riconosce i dividendi "
                  f"- forma {parlanti[0].forma}"))
            continue
        stati = {e.stato for e in suoi}
        if stati == {"unreachable"}:
            righe.append(L(f"{source}: unreachable from here (network or egress policy)",
                           f"{source}: irraggiungibile da qui (rete o politica di uscita)"))
        else:
            righe.append(L(f"{source}: no endpoint works ({', '.join(sorted(stati))})",
                           f"{source}: nessun indirizzo funziona ({', '.join(sorted(stati))})"))
    return "\n".join(righe)
