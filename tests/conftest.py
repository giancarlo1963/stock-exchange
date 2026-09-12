"""Ogni prova parte in inglese, la lingua predefinita dello strumento.

Senza questo, una prova che cambia lingua lascerebbe la lingua cambiata a
quelle dopo, e l'ordine dei test diventerebbe parte del risultato: il tipo di
guasto che si manifesta solo quando lo si esegue tutto insieme.
"""

import pytest

from setxray.lang import set_language


@pytest.fixture(autouse=True)
def _lingua_pulita():
    set_language("en")
    yield
    set_language("en")
