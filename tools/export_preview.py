"""Esporta i dati dei profili dimostrativi per l'anteprima da telefono.

    python tools/export_preview.py mobile/dati.js

L'anteprima e' una pagina HTML statica: non puo' far girare Python, quindi i
risultati del motore vengono calcolati qui una volta e scritti come un file
JavaScript che la pagina carica. Le chiavi del JSON sono quelle interne
(italiane) perche' la pagina le legge cosi'; il testo dentro i valori arriva
dal motore, quindi e' in inglese come tutto il resto dell'interfaccia.
"""

from __future__ import annotations

import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from setxray.demo import PROFILE_KEYS, profiles  # noqa: E402
from setxray.engine import analyze  # noqa: E402
from setxray.lang import CODES, using  # noqa: E402

# L'ordine e' una scelta dell'anteprima, non del motore: la pagina mostra
# prima i casi che insegnano di piu'. Le descrizioni arrivano da demo.py, che
# le tiene nelle due lingue.
ORDINE = ("dividendo", "tagliato", "irregolare", "solida", "cara", "difficolta")
assert set(ORDINE) == set(PROFILE_KEYS), "l'anteprima deve coprire tutti i profili"
# Una serie giornaliera intera pesa troppo per una pagina: un punto ogni due
# settimane e' piu' di quanto uno schermo da telefono possa distinguere.
PASSO_SERIE = 10


def _f(value) -> float | None:
    """Float arrotondato e sicuro da serializzare (NaN -> None)."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return round(number, 6)


def _series(serie: pd.Series | None, step: int = PASSO_SERIE) -> list:
    if serie is None or serie.empty:
        return []
    ridotta = serie.iloc[::step]
    if serie.index[-1] not in ridotta.index:  # l'ultimo punto e' quello di oggi
        ridotta = pd.concat([ridotta, serie.iloc[[-1]]])
    return [[d.strftime("%Y-%m-%d"), _f(v)] for d, v in ridotta.items()]


def _total_return_series(analisi, anni: float) -> list:
    """Prezzo e prezzo-con-cedole-reinvestite, entrambi da 100, giorno per giorno."""
    prezzi = analisi.data.prices
    div = analisi.dividends
    if prezzi is None or prezzi.empty or div is None:
        return []
    chiusure = prezzi["Close"].dropna()
    inizio = chiusure.index[-1] - pd.Timedelta(days=int(365.25 * (anni or 10)))
    finestra = chiusure[chiusure.index >= inizio]
    if len(finestra) < 100:
        return []
    solo_prezzo = finestra / finestra.iloc[0] * 100
    quote = pd.Series(1.0, index=finestra.index)
    fattore = 1.0
    pagamenti = div.payments
    nel_periodo = pagamenti[(pagamenti.index >= finestra.index[0])
                            & (pagamenti.index <= finestra.index[-1])]
    for data, importo in nel_periodo.items():
        successivi = finestra.index[finestra.index >= data]
        if not len(successivi):
            continue
        prezzo = float(finestra.loc[successivi[0]])
        if prezzo > 0:
            fattore *= 1 + float(importo) / prezzo
            quote.loc[successivi[0]:] = fattore
    totale = solo_prezzo * quote
    ridotto = solo_prezzo.iloc[::PASSO_SERIE]
    if solo_prezzo.index[-1] not in ridotto.index:
        ridotto = pd.concat([ridotto, solo_prezzo.iloc[[-1]]])
    return [[d.strftime("%Y-%m-%d"), _f(solo_prezzo.loc[d]), _f(totale.loc[d])]
            for d in ridotto.index]


def export(profilo: str, descrizione: str) -> dict:
    analisi = analyze(f"demo:{profilo}")
    m, d, v = analisi.metrics, analisi.dividends, analisi.verdict
    fuori = {
        "nome": m.name,
        "simbolo": m.symbol,
        "settore": m.sector,
        "descrizione": descrizione,
        "prezzo": _f(m.price),
        "valuta": m.currency,
        "generale": {
            "azione": v.action,
            "titolo": v.headline,
            "punteggio": _f(v.composite),
            "atteso": _f(v.expected_return_2y),
            "gravi": [f.text for f in v.grave_flags],
            "avvisi": [f.text for f in v.warning_flags],
        },
        "racconto": list(analisi.narrative.get("dividends", [])),
    }
    if d is None or not d.pays_dividends or d.signal is None:
        fuori["paga"] = False
        fuori["note"] = list(d.notes) if d else []
        return fuori

    s, sic, p, ver = d.signal, d.safety, d.forecast, d.backtest
    fuori["paga"] = True
    fuori["segnale"] = {
        "azione": s.action, "titolo": s.headline, "convinzione": s.conviction,
        "motivi": list(s.reasons),
        "ingresso": _f(s.entry_price), "valore": _f(s.fair_price), "uscita": _f(s.exit_price),
        "atteso2a": _f(s.expected_return_2y), "annuo": _f(s.expected_annualized),
        "cedole": _f(s.income_component), "prezzoComp": _f(s.price_component),
        "obiettivo": _f(s.target_yield),
    }
    fuori["solidita"] = {
        "punteggio": _f(sic.score), "banda": sic.band, "rischio": sic.cut_risk_band,
        "fattori": [{"etichetta": f.label, "punti": _f(f.points),
                     "spiegazione": f.explanation, "valore": _f(f.value), "formato": f.fmt}
                    for f in sic.factors],
        "innesci": list(sic.hard_triggers),
    }
    ys = d.yield_stats
    fuori["rendimento"] = {
        "attuale": _f(ys.get("attuale")), "mediana": _f(ys.get("mediana")),
        "percentile": _f(ys.get("percentile")), "p25": _f(ys.get("p25")),
        "p75": _f(ys.get("p75")), "minimo": _f(ys.get("minimo")),
        "massimo": _f(ys.get("massimo")), "dpsIndicato": _f(ys.get("dps_indicato")),
        "serie": _series(d.daily_yield),
    }
    fuori["previsione"] = {
        "y1": _f(p.year1_base), "y1min": _f(p.year1_low), "y1max": _f(p.year1_high),
        "y2": _f(p.year2_base), "y2min": _f(p.year2_low), "y2max": _f(p.year2_high),
        "nota": p.note or "",
        "metodi": [{"etichetta": me.label, "valore": _f(me.value), "peso": _f(me.weight),
                    "dettaglio": me.detail or me.skipped_reason or ""} for me in p.methods],
    } if p and p.ok else {"y1": None}
    fuori["crescita"] = {k: _f(d.growth.get(k)) for k in ("cagr_3y", "cagr_5y", "cagr_10y")}
    fuori["storico"] = {
        k: d.streaks.get(k) for k in ("anni_pagati", "anni_osservati", "anni_saltati",
                                      "tagli", "aumenti_consecutivi", "anno_ultimo_taglio")
    }
    fuori["storico"]["taglio_massimo"] = _f(d.streaks.get("taglio_massimo"))
    tr = d.total_return
    fuori["totale"] = {
        "anni": _f(tr.get("anni")), "solo_prezzo": _f(tr.get("solo_prezzo")),
        "totale_reinvestito": _f(tr.get("totale_reinvestito")),
        "quota_dividendi": _f(tr.get("quota_dividendi")),
        "annualizzato": _f(tr.get("annualizzato")),
        "contributo_dividendi": _f(tr.get("contributo_dividendi")),
        "serie": _total_return_series(analisi, tr.get("anni") or 10),
    }
    fuori["verifica"] = {
        "osservazioni": ver.observations if ver else 0,
        "nota": (ver.note if ver else "") or "",
        "separazione": _f(ver.separation) if ver else None,
        "gruppi": [{"etichetta": b.label, "n": b.observations, "media": _f(b.avg_return_2y)}
                   for b in (ver.buckets if ver else [])],
    }
    fuori["anni"] = [{
        "anno": int(anno),
        "dps": _f(riga.get("dps")), "stacchi": int(riga.get("stacchi") or 0),
        "completo": bool(riga.get("completo")),
        "taglio": bool(riga.get("completo")) and (riga.get("variazione") or 0) < -0.02,
        "rendimento": _f(riga.get("rendimento")), "payout": _f(riga.get("payout")),
        "copertura": _f(riga.get("copertura_cassa")),
    } for anno, riga in d.years.iterrows()]
    return fuori


def main(argv: list[str]) -> int:
    destinazione = argv[1] if len(argv) > 1 else "mobile/dati.js"
    # L'interruttore della pagina non puo' far girare il motore: le due lingue
    # vanno calcolate qui, entrambe, e spedite insieme.
    dati = {}
    for lingua in CODES:
        with using(lingua):
            descrizioni = profiles()
            dati[lingua] = {profilo: export(profilo, descrizioni[profilo])
                            for profilo in ORDINE}
    corpo = json.dumps(dati, ensure_ascii=False, separators=(",", ":"))
    with open(destinazione, "w", encoding="utf-8") as file:
        file.write(f"window.DATI = {corpo};\n")
    print(f"{destinazione}: {len(ORDINE)} profili x {len(CODES)} lingue, "
          f"{len(corpo) / 1024:.0f} kB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
