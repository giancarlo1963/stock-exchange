"""Il percorso che funziona sempre: un CSV scritto a mano.

Nessuna API puo' essere garantita nel tempo. Questa fonte no: se copi dal sito
della SET la tabella dei dividendi in un file di testo, l'app la legge e non
dipende da niente.

Dove mettere il file (il primo che esiste vince):

    1. il percorso nella variabile d'ambiente SETXRAY_DIVIDEND_CSV
    2. data/<SIMBOLO>-dividends.csv          (accanto all'app)
    3. dati/<SIMBOLO>-dividendi.csv          (i nomi vecchi restano validi)
    4. ~/.setxray/<SIMBOLO>-dividends.csv

Formato: due colonne, intestazione libera purche' riconoscibile.

    date,dividend
    2016-04-25,1.10
    2016-09-05,1.10
    2017-04-24,1.20

Vanno bene anche `data,importo`, il punto e virgola come separatore e la
virgola come segno decimale.
"""

from __future__ import annotations

import csv
import io
import os
from typing import Optional

import pandas as pd

from setxray.lang import L

from setxray.sources.base import CHIAVI_DATA, CHIAVI_IMPORTO, _to_date, clean_series
from setxray.sources.http import FetchError

CARTELLE = ("data", "dati", os.path.join(os.path.expanduser("~"), ".setxray"))


def candidate_paths(symbol: str) -> list[str]:
    percorsi = []
    imposto = os.environ.get("SETXRAY_DIVIDEND_CSV")
    if imposto:
        percorsi.append(imposto)
    for cartella in CARTELLE:
        # Accettiamo anche i nomi italiani: chi ha creato il file con la
        # versione precedente non deve rinominarlo.
        for nome in (f"{symbol}-dividends.csv", f"{symbol.lower()}-dividends.csv",
                     f"{symbol}-dividendi.csv", f"{symbol.lower()}-dividendi.csv"):
            percorsi.append(os.path.join(cartella, nome))
    return percorsi


def dividends(symbol: str) -> Optional[pd.Series]:
    from setxray.datasource import normalize_symbol

    set_symbol, _ = normalize_symbol(symbol)
    for percorso in candidate_paths(set_symbol):
        if os.path.isfile(percorso):
            with open(percorso, "r", encoding="utf-8-sig") as file:
                return parse_csv(file.read())
    return None


def parse_csv(testo: str) -> Optional[pd.Series]:
    """Legge il CSV riconoscendo separatore e nomi di colonna."""
    if not testo.strip():
        return None
    try:
        dialetto = csv.Sniffer().sniff(testo[:2048], delimiters=",;\t|")
        separatore = dialetto.delimiter
    except csv.Error:
        separatore = ","
    righe = list(csv.reader(io.StringIO(testo), delimiter=separatore))
    righe = [r for r in righe if any(campo.strip() for campo in r)]
    if not righe:
        return None

    intestazione = [campo.strip().lower() for campo in righe[0]]
    colonna_data = _indice(intestazione, CHIAVI_DATA + ("data", "giorno", "xd"))
    colonna_importo = _indice(intestazione, CHIAVI_IMPORTO + ("importo", "dividendo", "valore"))
    if colonna_data is None or colonna_importo is None:
        # Nessuna intestazione riconosciuta: assumiamo data nella prima
        # colonna e importo nella seconda, come nel formato documentato.
        colonna_data, colonna_importo, corpo = 0, 1, righe
    else:
        corpo = righe[1:]
    if len(intestazione) < 2:
        raise FetchError(L("the CSV needs at least two columns: date and amount",
                           "il CSV deve avere almeno due colonne: data e importo"))

    importi: dict = {}
    for riga in corpo:
        if len(riga) <= max(colonna_data, colonna_importo):
            continue
        importi[riga[colonna_data].strip()] = riga[colonna_importo].strip()
    if not importi:
        return None
    # Stessa conversione delle date usata per le API: una convenzione sola in
    # tutta l'app (giorno prima del mese, come scrive la SET).
    convertiti = {}
    for chiave, valore in importi.items():
        data, numero = _to_date(chiave), _numero(valore)
        if data is not None and numero is not None:
            convertiti[data] = convertiti.get(data, 0.0) + numero
    if not convertiti:
        return None
    return clean_series(pd.Series(convertiti))


def _indice(intestazione: list[str], candidate) -> Optional[int]:
    for nome in candidate:
        chiave = nome.lower().replace("_", "").replace(" ", "")
        for i, campo in enumerate(intestazione):
            if campo.replace("_", "").replace(" ", "") == chiave:
                return i
    return None


def _numero(valore: str) -> Optional[float]:
    testo = str(valore).strip().replace(" ", "")
    if not testo:
        return None
    if "," in testo and "." not in testo:
        testo = testo.replace(",", ".")
    try:
        return float(testo)
    except ValueError:
        return None
