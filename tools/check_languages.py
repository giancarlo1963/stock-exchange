"""Confronta le due lingue e segnala quello che e' rimasto indietro.

Una frase che esce identica in inglese e in italiano di solito non e' stata
tradotta. A volte invece e' giusto cosi': "EBITDA", "P/E", un nome proprio,
un numero. La differenza la fa il contenuto, non la lunghezza, quindi il
controllo cerca parole vere: due o piu' gruppi di lettere lunghi almeno tre
caratteri che non siano sigle tutte maiuscole.

    python tools/check_languages.py            # elenca i sospetti
    python tools/check_languages.py --strict    # esce con 1 se ne trova
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from setxray.lang import using                                # noqa: E402
from tools.dump_strings import testi                          # noqa: E402
from setxray.demo import PROFILE_KEYS                         # noqa: E402

# Parole che restano uguale nelle due lingue: sigle, nomi, unita'.
PASSAPORTO = {
    "ebitda", "roe", "roic", "roa", "capex", "set", "thb", "yahoo", "finance", "eur",
    "per", "share", "azione", "demo", "pcl", "utilities", "regulated", "electric",
    "real", "estate", "diversified", "basic", "materials", "steel", "industrials",
    "specialty", "industrial", "machinery", "consumer", "defensive", "packaged",
    "foods", "marine", "shipping", "thai", "regional", "power", "siam", "sample",
    "industries", "bangkok", "premium", "brands", "chao", "phraya", "heavy",
    "chiang", "mai", "property", "trust", "andaman", "services", "stock",
    "exchange", "thailand", "csv", "api", "kaleido", "streamlit", "markdown",
}
PAROLA = re.compile(r"[A-Za-z][A-Za-z'à-ÿ]{2,}")


ETICHETTA = re.compile(r"^\[grafico [a-z_]+\]\s*")


def ha_parole_vere(testo: str) -> bool:
    # L'etichetta che il dumper mette davanti ai grafici non e' contenuto
    testo = ETICHETTA.sub("", testo)
    parole = [p for p in PAROLA.findall(testo)
              if p.lower() not in PASSAPORTO and not p.isupper()]
    return len(parole) >= 2


def main(argv: list[str]) -> int:
    inglese, italiano = [], []
    for profilo in PROFILE_KEYS:
        with using("en"):
            inglese += testi(profilo)
        with using("it"):
            italiano += testi(profilo)
    if len(inglese) != len(italiano):
        print(f"ATTENZIONE: le due lingue producono un numero diverso di stringhe "
              f"({len(inglese)} contro {len(italiano)}): la struttura dell'analisi "
              f"non dovrebbe dipendere dalla lingua.")
    sospetti = {}
    for a, b in zip(inglese, italiano):
        for riga_a, riga_b in zip(str(a).splitlines(), str(b).splitlines()):
            if riga_a == riga_b and ha_parole_vere(riga_a):
                sospetti[riga_a.strip()] = sospetti.get(riga_a.strip(), 0) + 1
    for testo, n in sorted(sospetti.items(), key=lambda x: -x[1]):
        print(f"{n:3d}x  {testo[:150]}")
    print(f"--- {len(sospetti)} frasi identiche nelle due lingue")
    if "--strict" in argv and sospetti:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
