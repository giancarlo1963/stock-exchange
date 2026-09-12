"""Stampa ogni stringa che l'app mostra all'utente, in una lingua.

Serve a due cose, entrambe difficili a occhio:

1. confrontare le due lingue e trovare quello che e' rimasto indietro: una
   frase che esce identica in inglese e in italiano, e che contiene parole, o
   non e' tradotta o e' un termine tecnico;
2. fare da rete di sicurezza quando si tocca la forma del codice (rientri,
   andate a capo dentro le stringhe): se l'uscita non cambia di un byte, la
   riformattazione non ha cambiato il significato.

    python tools/dump_strings.py en > /tmp/en.txt
    python tools/dump_strings.py it > /tmp/it.txt
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from setxray import charts                                   # noqa: E402
from setxray.demo import PROFILE_KEYS                         # noqa: E402
from setxray.engine import analyze                           # noqa: E402
from setxray.lang import using                               # noqa: E402
from setxray.sources import describe_sources                 # noqa: E402


def testi(profilo: str) -> list[str]:
    a = analyze(f"demo:{profilo}")
    m, v, d = a.metrics, a.valuation, a.verdict
    fuori: list[str] = [a.report()]
    for sezione in ("past", "present", "future", "dividends"):
        fuori += a.narrative.get(sezione, [])
    fuori += [d.headline, d.conviction, d.data_quality, d.position_note]
    fuori += list(d.reasons) + list(d.review_triggers) + [f.text for f in d.flags]
    fuori += [p.label for p in d.pillars] + [p.question for p in d.pillars]
    fuori += [c.label for p in d.pillars for c in p.criteria]
    fuori += [c.note or "" for p in d.pillars for c in p.criteria]
    fuori += [c.formatted() for p in d.pillars for c in p.criteria]
    fuori += [v.reliability] + list(v.notes) + list(m.notes) + list(a.data.warnings)
    fuori += [me.label for me in v.methods]
    fuori += [(me.detail or "") + "|" + (me.skipped_reason or "") for me in v.methods]
    fuori += list(a.data.data_coverage().keys())

    div = a.dividends
    if div is not None:
        fuori += list(div.notes)
        if div.safety:
            fuori += [div.safety.band, div.safety.cut_risk_band] + list(div.safety.hard_triggers)
            fuori += [f.label for f in div.safety.factors]
            fuori += [f.explanation for f in div.safety.factors]
        if div.forecast:
            fuori += [div.forecast.note or ""] + [me.label for me in div.forecast.methods]
            fuori += [(me.detail or "") + "|" + (me.skipped_reason or "")
                      for me in div.forecast.methods]
        if div.signal:
            fuori += [div.signal.headline, div.signal.action, div.signal.conviction]
            fuori += list(div.signal.reasons)
        if div.backtest:
            fuori += [div.backtest.note or ""] + [b.label for b in div.backtest.buckets]
        if div.source:
            fuori += [div.source.provenance()] + list(div.source.disagreements)
            fuori += [f"{r.label}|{r.note or ''}|{r.error or ''}" for r in div.source.results]

    for nome, fig in sorted({**charts.all_charts(a), **charts.dividend_charts(a)}.items()):
        j = fig.layout.to_plotly_json()
        fuori.append(f"[grafico {nome}] " + str(j.get("title", {}).get("text", "")))
        for ann in j.get("annotations", []) or []:
            fuori.append(f"[grafico {nome}] " + str(ann.get("text", "")))
        for tr in fig.data:
            fuori.append(f"[grafico {nome}] " + str(getattr(tr, "name", "") or ""))
            for campo in ("customdata", "text"):
                valori = getattr(tr, campo, None)
                if valori is not None and not isinstance(valori, str):
                    fuori += [f"[grafico {nome}] {x}" for x in valori]
    return fuori


def main(argv: list[str]) -> int:
    lingua = argv[1] if len(argv) > 1 else "en"
    with using(lingua):
        for riga in describe_sources():
            print(f"[fonte] {riga['source']} | {riga['api_key']} | {riga['note']}")
        for profilo in PROFILE_KEYS:
            for testo in testi(profilo):
                for riga in str(testo).splitlines() or [""]:
                    print(f"[{profilo}] {riga}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
