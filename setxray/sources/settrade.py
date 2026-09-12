"""Settrade: la piattaforma di trading della SET, dove guarda il retail thailandese.

Settrade e' gestita da una societa' del gruppo SET e fa da front-end a quasi
tutti i broker locali: le tabelle degli stacchi che un investitore thailandese
legge davvero sono queste. Per i dividendi di un titolo SET e' una fonte di
prima fila, allo stesso livello del sito della borsa.

DA VERIFICARE AL PRIMO USO, e va detto senza girarci intorno: Settrade non
pubblica un'API documentata per uso esterno, e dall'ambiente in cui questo
modulo e' stato scritto la rete verso i siti di mercato e' bloccata. Gli
indirizzi qui sotto sono quelli che il sito usa per riempire le proprie
pagine, provati in ordine, ma nessuno di loro e' stato confermato contro il
servizio vivo. Quindi, come per il sito della SET:

- si provano piu' indirizzi, non uno solo;
- la lettura del JSON non assume una struttura fissa (`parse_dividend_records`
  cerca i campi dove sono, non dove dovrebbero essere);
- se ne conosci uno che funziona, lo imponi con SETXRAY_SETTRADE_API, usando
  {symbol} come segnaposto;
- l'esito di ogni tentativo finisce nella scheda *Fonti dei dati*, con
  l'errore per intero: al primo titolo analizzato si sa se questa strada
  funziona, e se non funziona si sa perche';
- e nella stessa scheda c'e' il pulsante che prova gli indirizzi uno per uno
  (`setxray.sources.probe`) e dice per ognuno se risponde, se risponde JSON e
  se i dividendi sono stati riconosciuti. La verifica la fa chi la rete verso
  Settrade ce l'ha, cioe' chi fa girare l'app, non chi ha scritto il codice.

La pagina da cui partire e' quella delle quotazioni,
https://www.settrade.com/th/get-quote : con la scheda Rete del browser aperta
si vede quale indirizzo interroga per riempirsi, e quello e' l'indirizzo buono.
Si incolla nella sonda, e se la sonda dice che funziona si fissa con
SETXRAY_SETTRADE_API.

Esiste anche una strada ufficiale, la Settrade Open API
(developer.settrade.com): e' documentata e mantenuta, ma e' pensata per il
trading e richiede un conto presso un broker che la abiliti, con credenziali
proprie. Per la storia degli stacchi di un titolo e' molto piu' apparato di
quanto serva; resta la strada giusta per chi quel conto ce l'ha.

Una nota che non riguarda il codice: le pagine di Settrade sono pubbliche, ma
sono di un operatore privato. Interrogarne gli indirizzi interni per uno
strumento personale e' una cosa, farne un servizio e' un'altra: nel secondo
caso vanno guardate le loro condizioni d'uso.
"""

from __future__ import annotations

import os
from typing import Optional

import pandas as pd

from setxray.lang import L
from setxray.sources.base import parse_dividend_records
from setxray.sources.http import FetchError, get_json

TIMEOUT_PER_INDIRIZZO = 6

# Dal piu' specifico al piu' generico: il primo che risponde con qualcosa di
# riconoscibile vince. `{symbol}` e' la sigla SET senza suffisso.
INDIRIZZI = (
    "https://www.settrade.com/api/set/stock/{symbol}/rights-benefit",
    "https://www.settrade.com/api/set/stock/{symbol}/corporate-action",
    "https://www.settrade.com/api/set/factsheet/{symbol}/rights-benefit",
    "https://api.settrade.com/api/set/stock/{symbol}/rights-benefit",
    # Le due qui sotto vengono dalla forma della pagina pubblica, che ha la
    # lingua nel percorso (/th/get-quote): un sito fatto cosi' a volte tiene
    # anche le proprie chiamate sotto la lingua. Sono ipotesi come le altre - la
    # sonda dira' quale delle sei e' quella vera.
    "https://www.settrade.com/th/api/set/stock/{symbol}/rights-benefit",
    "https://www.settrade.com/api/set/stock/{symbol}/rights-benefit-history",
)


def pagina(symbol: str) -> str:
    """La pagina delle quotazioni, per guardare la tabella con i propri occhi.

    Quando la lettura automatica non funziona il dato non e' perduto: e' scritto
    su una pagina, e un collegamento che la apre sul titolo giusto vale piu' di
    una spiegazione.
    """
    return f"https://www.settrade.com/th/get-quote?symbol={symbol}"


def endpoints() -> tuple[str, ...]:
    """Gli indirizzi da provare, con l'eventuale sostituzione dell'utente davanti."""
    personalizzato = os.environ.get("SETXRAY_SETTRADE_API")
    if personalizzato:
        return (personalizzato,) + INDIRIZZI
    return INDIRIZZI


def dividends(symbol: str) -> Optional[pd.Series]:
    from setxray.datasource import normalize_symbol

    set_symbol, _ = normalize_symbol(symbol)
    errori: list[str] = []
    for modello in endpoints():
        url = modello.format(symbol=set_symbol)
        etichetta = url.split("/api/")[-1]
        try:
            dati = get_json(url, {"lang": "en"}, timeout=TIMEOUT_PER_INDIRIZZO)
        except FetchError as errore:
            errori.append(f"{etichetta}: {errore}")
            # Un 404 vuol dire "indirizzo sbagliato": vale provare il prossimo.
            # Un errore di connessione vuol dire che l'host non risponde, e
            # insistere costerebbe solo secondi di attesa.
            if not str(errore).startswith("HTTP "):
                break
            continue
        serie = parse_dividend_records(dati)
        if serie is not None and not serie.empty:
            return serie
        errori.append(L(f"{etichetta}: no dividend recognised in the response",
                        f"{etichetta}: nessun dividendo riconosciuto nella risposta"))
    raise FetchError("; ".join(errori[:3]) if errori else L("no endpoint available",
                                                            "nessun indirizzo disponibile"))
