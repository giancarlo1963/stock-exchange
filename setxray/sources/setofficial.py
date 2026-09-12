"""Il sito ufficiale della Stock Exchange of Thailand.

E' la fonte autorevole per i dividendi di un titolo SET: le date di stacco e
gli importi sono quelli comunicati dalla societa'.

ATTENZIONE, e va detto chiaramente: la SET non pubblica un'API documentata per
uso esterno. Gli indirizzi qui sotto sono quelli usati dal suo sito web e
possono cambiare senza preavviso. Per questo:

- proviamo piu' indirizzi in ordine, non uno solo;
- la lettura del JSON non assume una struttura fissa (vedi
  `parse_dividend_records`), cosi' un cambio di forma non la rompe subito;
- se hai un indirizzo che funziona, puoi imporlo con la variabile d'ambiente
  SETXRAY_SET_API (usa {symbol} come segnaposto);
- se niente funziona, resta il percorso CSV, che non dipende da nessuna API.
"""

from __future__ import annotations

import os
from typing import Optional

import pandas as pd

from setxray.sources.base import parse_dividend_records
from setxray.sources.http import FetchError, get_json
from setxray.lang import L

# Quattro indirizzi da provare: il timeout deve restare basso, altrimenti
# un sito lento blocca l'analisi per un minuto.
TIMEOUT_PER_INDIRIZZO = 6

# Indirizzi noti del sito SET, dal piu' specifico al piu' generico.
INDIRIZZI = (
    "https://www.set.or.th/api/set/stock/{symbol}/rights-benefit",
    "https://www.set.or.th/api/set/stock/{symbol}/corporate-action",
    "https://www.set.or.th/api/set/factsheet/{symbol}/rights-benefit",
    "https://www.set.or.th/api/set/company/{symbol}/rights-benefit",
)


def endpoints() -> tuple[str, ...]:
    """Gli indirizzi da provare, con l'eventuale sostituzione dell'utente davanti."""
    personalizzato = os.environ.get("SETXRAY_SET_API")
    if personalizzato:
        return (personalizzato,) + INDIRIZZI
    return INDIRIZZI


def dividends(symbol: str) -> Optional[pd.Series]:
    from setxray.datasource import normalize_symbol

    set_symbol, _ = normalize_symbol(symbol)
    errori: list[str] = []
    for modello in endpoints():
        url = modello.format(symbol=set_symbol)
        try:
            dati = get_json(url, {"lang": "en"}, timeout=TIMEOUT_PER_INDIRIZZO)
        except FetchError as errore:
            errori.append(f"{url.split('/api/')[-1]}: {errore}")
            # Un HTTP 404 significa "indirizzo sbagliato": vale provare il
            # prossimo. Un errore di connessione significa che l'host non
            # risponde: insistere costerebbe solo secondi di attesa.
            if not str(errore).startswith("HTTP "):
                break
            continue
        serie = parse_dividend_records(dati)
        if serie is not None and not serie.empty:
            return serie
        errori.append(L(f"{url.split('/api/')[-1]}: no dividend recognised in the response",
                        f"{url.split('/api/')[-1]}: nessun dividendo riconosciuto nella risposta"))
    raise FetchError("; ".join(errori[:3]) if errori else L("no endpoint available",
                                                            "nessun indirizzo disponibile"))
