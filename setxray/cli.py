"""Da terminale, senza aprire il browser.

    python -m setxray PTT
    python -m setxray AOT --report analisi-aot.md
    python -m setxray demo:difficolta
    python -m setxray CPALL --grafici cartella/
"""

from __future__ import annotations

import argparse
import os
import sys

from setxray import __version__, fmt
from setxray.datasource import clear_cache
from setxray.demo import PROFILES
from setxray.engine import NoDataError, analyze
from setxray.scoring import BUY, HOLD, SELL
from setxray.valuation import EQUITY_RISK_PREMIUM_TH, RISK_FREE_TH

# Colori ANSI: spenti se l'output non e' un terminale (pipe, file, CI).
_TTY = sys.stdout.isatty()
VERDE, GIALLO, ROSSO, GRASSETTO, SPENTO = (
    ("\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[0m") if _TTY else ("", "", "", "", "")
)
COLORE_AZIONE = {BUY: VERDE, HOLD: GIALLO, SELL: ROSSO}


def _riga(titolo: str) -> str:
    return f"\n{GRASSETTO}{titolo}{SPENTO}\n" + "-" * max(24, len(titolo))


def stampa(analisi) -> None:
    m, v, d = analisi.metrics, analisi.valuation, analisi.verdict
    valuta = m.currency
    colore = COLORE_AZIONE.get(d.action, "")

    print(f"\n{GRASSETTO}{m.name}{SPENTO}  [{m.symbol}]")
    dettagli = [x for x in (m.sector, m.industry, f"dati al {fmt.date(m.trend.get('last_date'))}") if x]
    print("  " + " · ".join(dettagli))
    if analisi.data.is_demo:
        print(f"\n  {GIALLO}DATI DIMOSTRATIVI SINTETICI: societa' inventata, numeri non reali.{SPENTO}")

    print(f"\n{colore}{GRASSETTO}  ==> {d.headline}{SPENTO}")
    print(f"      punteggio {fmt.num(d.composite, 0)}/100 · qualita' dei dati: {d.data_quality}")

    print(_riga("Numeri chiave"))
    print(f"  Prezzo                       {fmt.money(m.price, valuta)}")
    print(f"  Valore stimato               {fmt.money(v.fair_base, valuta)}"
          f"   (da {fmt.num(v.fair_bear)} a {fmt.num(v.fair_bull)}, affidabilita' {v.reliability})")
    print(f"  Rendimento atteso a 2 anni   {fmt.pct(d.expected_return_2y, sign=True)}"
          f"   ({fmt.pct(d.expected_annualized, sign=True)} all'anno)")
    if d.entry_price:
        print(f"  Prezzo d'ingresso            sotto {fmt.money(d.entry_price, valuta)}")
    print(f"  P/E · P/B · dividendo        {fmt.mult(m.valuation.get('pe'))} · "
          f"{fmt.mult(m.valuation.get('pb'))} · {fmt.pct(m.dividend.get('yield_current'))}")

    print(_riga("Punteggio per area"))
    for pilastro in d.pillars:
        punteggio = pilastro.score
        segno = "n/d".rjust(5) if punteggio is None else fmt.num(punteggio, 1).rjust(5)
        tinta = "" if punteggio is None else (VERDE if punteggio >= 65 else GIALLO if punteggio >= 45 else ROSSO)
        parola = "" if punteggio is None else ("buono" if punteggio >= 65 else "medio" if punteggio >= 45 else "debole")
        print(f"  {pilastro.label:34s} {tinta}{segno}{SPENTO}  {parola}")

    print(_riga("Perche'"))
    for motivo in d.reasons:
        print(f"  · {motivo}")
    print(f"\n  {d.position_note}")

    if d.flags:
        print(_riga("Campanelli d'allarme"))
        for segnale in d.flags:
            tinta = ROSSO if segnale.severity == "grave" else GIALLO
            etichetta = "GRAVE " if segnale.severity == "grave" else "avviso"
            print(f"  {tinta}[{etichetta}]{SPENTO} {segnale.text}")

    for titolo, chiave in (("Passato", "passato"), ("Presente", "presente"), ("Futuro", "futuro")):
        print(_riga(titolo))
        for paragrafo in analisi.narrative[chiave]:
            print(f"  {paragrafo}")

    print(_riga("Quando rivedere la decisione"))
    for innesco in d.review_triggers:
        print(f"  · {innesco}")

    print("\n  Elaborazione automatica di dati pubblici: non e' consulenza finanziaria.\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="setxray",
        description="Analizza un'azione della Borsa di Thailandia (SET) e dice se comprare, "
                    "mantenere o vendere, con orizzonte 1-2 anni.",
        epilog="Profili dimostrativi disponibili senza internet: "
               + ", ".join(f"demo:{p}" for p in PROFILES),
    )
    parser.add_argument("simbolo", nargs="?", help="simbolo SET, per esempio PTT, AOT, CPALL")
    parser.add_argument("--report", metavar="FILE", help="salva il report completo in markdown")
    parser.add_argument("--grafici", metavar="CARTELLA",
                        help="salva i grafici in PNG nella cartella indicata (richiede kaleido)")
    parser.add_argument("--tasso", type=float, default=RISK_FREE_TH * 100,
                        metavar="PERCENTO", help="tasso privo di rischio, in percento "
                        f"(predefinito {RISK_FREE_TH * 100:.1f})")
    parser.add_argument("--premio", type=float, default=EQUITY_RISK_PREMIUM_TH * 100,
                        metavar="PERCENTO", help="premio per il rischio azionario, in percento "
                        f"(predefinito {EQUITY_RISK_PREMIUM_TH * 100:.1f})")
    parser.add_argument("--no-cache", action="store_true", help="ignora la cache e riscarica")
    parser.add_argument("--svuota-cache", action="store_true", help="svuota la cache ed esce")
    parser.add_argument("--version", action="version", version=f"setxray {__version__}")
    args = parser.parse_args(argv)

    if args.svuota_cache:
        print(f"Cache svuotata ({clear_cache()} file).")
        return 0
    if not args.simbolo:
        parser.error("indica un simbolo, per esempio: python -m setxray PTT")

    try:
        analisi = analyze(args.simbolo, cache_ttl_min=0 if args.no_cache else 60,
                          risk_free=args.tasso / 100, erp=args.premio / 100)
    except (NoDataError, ValueError) as errore:
        print(f"{ROSSO}Errore:{SPENTO} {errore}", file=sys.stderr)
        return 2
    except Exception as errore:
        print(f"{ROSSO}Analisi non completata:{SPENTO} {type(errore).__name__} - {errore}",
              file=sys.stderr)
        print("Se il problema si ripete prova con --no-cache, o riprova piu' tardi: "
              "Yahoo Finance limita il numero di richieste.", file=sys.stderr)
        return 3

    stampa(analisi)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as file:
            file.write(analisi.report())
        print(f"Report salvato in {args.report}")

    if args.grafici:
        from setxray.charts import all_charts

        os.makedirs(args.grafici, exist_ok=True)
        try:
            for nome, figura in all_charts(analisi).items():
                percorso = os.path.join(args.grafici, f"{analisi.symbol}-{nome}.png")
                figura.write_image(percorso, width=1100,
                                   height=int(figura.layout.height or 380), scale=2)
            print(f"Grafici salvati in {args.grafici}")
        except Exception as errore:
            print(f"{GIALLO}Grafici non salvati:{SPENTO} {type(errore).__name__} - {errore}",
                  file=sys.stderr)
            print("L'esportazione in PNG richiede kaleido e un browser Chrome: "
                  "pip install kaleido && plotly_get_chrome", file=sys.stderr)
            return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
