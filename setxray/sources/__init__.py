"""Piu' fonti per lo stesso dato, e un confronto fra loro.

Perche' non basta una fonte sola. Sui titoli thailandesi i dividendi sono il
dato piu' facile da sbagliare: Yahoo Finance a volte ne salta qualcuno, a volte
sbaglia la scala (baht contro satang), a volte registra lo stacco con qualche
giorno di ritardo. Su dieci anni di storia questi errori cambiano le
conclusioni. Quindi interroghiamo tutte le fonti disponibili, teniamo la serie
piu' lunga, e *diciamo all'utente* dove le fonti non vanno d'accordo.

Fonti previste, in ordine di fiducia:

1. `set`   - sito ufficiale della Stock Exchange of Thailand. Autorevole.
2. `csv`   - un file scritto a mano dall'utente. Autorevole per definizione:
             se lo ha copiato dal sito della SET, e' la verita'.
3. `eodhd`, `fmp`, `alphavantage` - servizi commerciali con piano gratuito.
4. `yahoo` - sempre disponibile e senza chiave, ma il meno affidabile sui
             titoli SET: resta la riserva.

Tutte le fonti sono facoltative e nessuna interruzione di rete puo' far
fallire l'analisi: una fonte che non risponde viene solo annotata.
"""

from __future__ import annotations

from setxray.sources.base import (
    DividendSet,
    SourceResult,
    available_sources,
    collect_dividends,
    describe_sources,
    requested_sources,
)

__all__ = [
    "DividendSet",
    "SourceResult",
    "available_sources",
    "collect_dividends",
    "describe_sources",
    "requested_sources",
]
