"""La lingua dell'interfaccia: una scelta, due parole per ogni frase.

Lo strumento parla inglese o italiano. La scelta non e' un dizionario di
chiavi (`t("verdetto.compra")`) ma una coppia scritta nel punto in cui la
frase nasce:

    L("no cuts in the 10 years observed",
      "nessun taglio nei 10 anni osservati")

Costa qualche colonna in piu', e in cambio la frase resta leggibile dove viene
costruita: chi cambia la versione inglese vede quella italiana sulla riga
sotto, e non puo' modificarne una sola senza accorgersene. Con un catalogo di
chiavi le due lingue vivrebbero in file diversi e divergerebbero in silenzio.

Il racconto dell'analista costruisce le frasi con la grammatica dentro
(singolari, plurali, accordi), quindi non esiste un modo di tenere una sola
frase con dei segnaposti: le due lingue sono due frasi.

La lingua attiva sta in un ContextVar, non in una variabile globale: Streamlit
serve ogni sessione in un thread suo, e due utenti con due lingue diverse non
devono vedersi l'uno la lingua dell'altro.
"""

from __future__ import annotations

import contextlib
import contextvars
import os

CODES = ("en", "it")
NAMES = {"en": "English", "it": "Italiano"}
FALLBACK = "en"

_active: contextvars.ContextVar[str | None] = contextvars.ContextVar("setxray_lang", default=None)


def normalize(code: str | None) -> str:
    """Da qualunque cosa somigli a una lingua al codice che usiamo.

    Accetta 'it', 'IT', 'it-IT', 'italiano': la variabile d'ambiente e il
    parametro dell'indirizzo li scrive una persona, non il programma.
    """
    if not code:
        return FALLBACK
    testo = str(code).strip().lower().replace("_", "-")
    if testo.startswith("it"):
        return "it"
    if testo.startswith("en"):
        return "en"
    return FALLBACK


def language() -> str:
    """La lingua attiva: la scelta della sessione, o SETXRAY_LANG, o inglese."""
    scelta = _active.get()
    if scelta is not None:
        return scelta
    return normalize(os.environ.get("SETXRAY_LANG"))


def set_language(code: str | None) -> str:
    """Fissa la lingua per questo thread. Ritorna il codice normalizzato."""
    codice = normalize(code)
    _active.set(codice)
    return codice


@contextlib.contextmanager
def using(code: str | None):
    """Esegue un blocco in una lingua, e rimette quella di prima.

    Serve a chi genera entrambe le lingue in un colpo (l'esportatore
    dell'anteprima, i test) senza sporcare lo stato di chi chiama.
    """
    segnaposto = _active.set(normalize(code))
    try:
        yield language()
    finally:
        _active.reset(segnaposto)


def L(en: str, it: str) -> str:
    """La stessa frase nelle due lingue: inglese prima, italiano dopo."""
    return it if language() == "it" else en


def plural(n: float | None, one: str, many: str) -> str:
    """Singolare o plurale secondo `n`, per non scrivere '1 tagli'."""
    return one if n is not None and abs(n) == 1 else many


# Le tre azioni sono identificatori stabili ("BUY"), non testo: il codice le
# confronta, le usa come chiavi, i test le controllano. Qui c'e' la parola che
# l'utente legge al loro posto, che invece cambia con la lingua.
ACTION_LABELS = {
    "BUY": ("BUY", "COMPRA"),
    "HOLD": ("HOLD", "MANTIENI"),
    "SELL": ("SELL", "VENDI"),
}


def action_label(action: str) -> str:
    """Da BUY / HOLD / SELL alla parola da mostrare."""
    coppia = ACTION_LABELS.get(action)
    return L(*coppia) if coppia else str(action)
