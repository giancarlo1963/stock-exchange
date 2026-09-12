"""Un client HTTP minimo, sulla libreria standard.

Non usiamo `requests` per non aggiungere una dipendenza solo per tre GET, e
perche' `urllib` legge da se' le variabili d'ambiente del proxy. Ogni chiamata
ha un timeout: una fonte lenta non deve bloccare l'analisi.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional
from setxray.lang import L

TIMEOUT = 12
USER_AGENT = "setxray/1.1 (analisi dividendi SET; https://github.com/topics/stock-analysis)"


class FetchError(RuntimeError):
    """The source did not answer, or answered with something unusable."""


def get_json(url: str, params: Optional[dict[str, Any]] = None, *,
             timeout: int = TIMEOUT, headers: Optional[dict[str, str]] = None) -> Any:
    """GET che ritorna JSON decodificato, o solleva `FetchError`."""
    if params:
        pulito = {k: v for k, v in params.items() if v is not None}
        url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(pulito)}"
    richiesta = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en,th;q=0.8",
        **(headers or {}),
    })
    try:
        with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:
            corpo = risposta.read()
    except urllib.error.HTTPError as errore:
        raise FetchError(L(f"HTTP {errore.code} from {urllib.parse.urlparse(url).netloc}",
                           f"HTTP {errore.code} da {urllib.parse.urlparse(url).netloc}")) from errore
    except Exception as errore:  # rete assente, DNS, TLS, timeout
        raise FetchError(f"{type(errore).__name__}: {errore}") from errore
    if not corpo:
        raise FetchError(L("empty response", "risposta vuota"))
    try:
        return json.loads(corpo.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as errore:
        raise FetchError(L("the response is not JSON (the source may have changed its "
                           "interface)",
                           "la risposta non e' JSON (la fonte potrebbe aver cambiato interfaccia)")) from errore


def get_text(url: str, *, timeout: int = TIMEOUT) -> str:
    richiesta = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:
            return risposta.read().decode("utf-8", errors="replace")
    except Exception as errore:
        raise FetchError(f"{type(errore).__name__}: {errore}") from errore
