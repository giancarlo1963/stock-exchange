"""From the terminal, without opening a browser.

    python -m setxray PTT
    python -m setxray AOT --report analysis-aot.md
    python -m setxray demo:difficolta
    python -m setxray CPALL --charts folder/
"""

from __future__ import annotations

import argparse
import os
import sys

from setxray import __version__, fmt
from setxray.datasource import clear_cache
from setxray.demo import PROFILE_KEYS
from setxray.engine import NoDataError, analyze
from setxray.scoring import BUY, HOLD, SELL
from setxray.valuation import EQUITY_RISK_PREMIUM_TH, RISK_FREE_TH
from setxray.lang import CODES, L, action_label, set_language

# ANSI colours: switched off when the output is not a terminal (pipe, file, CI).
_TTY = sys.stdout.isatty()
GREEN, AMBER, RED, BOLD, OFF = (
    ("\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[0m") if _TTY else ("", "", "", "", "")
)
ACTION_COLOUR = {BUY: GREEN, HOLD: AMBER, SELL: RED}


def _heading(title: str) -> str:
    return f"\n{BOLD}{title}{OFF}\n" + "-" * max(24, len(title))


def print_dividends(analisi) -> None:
    """The dividend section: this is the tool's main answer."""
    d = analisi.dividends
    valuta = analisi.metrics.currency
    print(_heading(L("Dividends: ten years", "Dividendi: dieci anni")))
    if d is None or not d.pays_dividends:
        print(L("  No dividend on record for this stock in the sources available.",
                "  Nessun dividendo registrato per questo titolo nelle fonti disponibili."))
        for nota in (d.notes if d else []):
            print(f"  {nota}")
        return

    segnale, sicurezza, rendimento = d.signal, d.safety, d.yield_stats
    colore = ACTION_COLOUR.get(segnale.action, "")
    print(f"\n{colore}{BOLD}  ==> {segnale.headline}{OFF}")
    print(L(f"  Yield today                  {fmt.pct(rendimento.get('attuale'))}"
            f"   (historical median {fmt.pct(rendimento.get('mediana'))}, "
            f"percentile {fmt.pct(rendimento.get('percentile'))})",
            f"  Rendimento oggi              {fmt.pct(rendimento.get('attuale'))}"
            f"   (mediana storica {fmt.pct(rendimento.get('mediana'))}, "
            f"percentile {fmt.pct(rendimento.get('percentile'))})"))
    print(L(f"  Dividend, annualised         {fmt.money(rendimento.get('dps_indicato'), valuta)}",
            f"  Dividendo su base annua      {fmt.money(rendimento.get('dps_indicato'), valuta)}"))
    if d.forecast and d.forecast.ok:
        print(L(f"  Next 12 months estimated     {fmt.money(d.forecast.year1_base, valuta)}"
                f"   ({fmt.num(d.forecast.year1_low)} to {fmt.num(d.forecast.year1_high)})",
                f"  Stima prossimi 12 mesi       {fmt.money(d.forecast.year1_base, valuta)}"
                f"   (da {fmt.num(d.forecast.year1_low)} a {fmt.num(d.forecast.year1_high)})"))
    banda = {L("solid",
               "solido"): GREEN, L("watch closely",
                                            "da tenere d'occhio"): AMBER, L("at risk",
                                                                                             "a rischio"): RED}.get(sicurezza.band, "")
    print(L(f"  Dividend safety              {banda}{fmt.num(sicurezza.score, 0)}/100 "
            f"({sicurezza.band}){OFF}, cut risk {sicurezza.cut_risk_band}",
            f"  Solidita' del dividendo      {banda}{fmt.num(sicurezza.score, 0)}/100 "
            f"({sicurezza.band}){OFF}, rischio di taglio {sicurezza.cut_risk_band}"))
    print(L(f"  Expected return over 2 years {fmt.pct(segnale.expected_return_2y, sign=True)}"
            f"   ({fmt.pct(segnale.income_component, sign=True)} coupons, "
            f"{fmt.pct(segnale.price_component, sign=True)} price)",
            f"  Rendimento atteso a 2 anni   {fmt.pct(segnale.expected_return_2y, sign=True)}"
            f"   ({fmt.pct(segnale.income_component, sign=True)} cedole, "
            f"{fmt.pct(segnale.price_component, sign=True)} prezzo)"))
    etichetta = (L("Would become interesting below",
                   "Tornerebbe interessante sotto") if segnale.action == SELL else L("Buy below",
                                                                                   "Compra sotto"))
    print(L(f"  {etichetta:28s} {fmt.money(segnale.entry_price, valuta)}"
            f"   (value {fmt.num(segnale.fair_price)}, "
            f"trim above {fmt.num(segnale.exit_price)})",
            f"  {etichetta:28s} {fmt.money(segnale.entry_price, valuta)}"
            f"   (valore {fmt.num(segnale.fair_price)}, "
            f"alleggerisci sopra {fmt.num(segnale.exit_price)})"))

    crescita, streaks = d.growth, d.streaks
    print(L(f"\n  Average dividend growth: 10 years {fmt.pct(crescita.get('cagr_10y'), sign=True)}"
            f" · 5 years {fmt.pct(crescita.get('cagr_5y'), sign=True)}"
            f" · 3 years {fmt.pct(crescita.get('cagr_3y'), sign=True)}",
            f"\n  Crescita media del dividendo: 10 anni "
            f"{fmt.pct(crescita.get('cagr_10y'), sign=True)}"
            f" · 5 anni {fmt.pct(crescita.get('cagr_5y'), sign=True)}"
            f" · 3 anni {fmt.pct(crescita.get('cagr_3y'), sign=True)}"))
    print(L(f"  Years paid {streaks.get('anni_pagati')} of {streaks.get('anni_osservati')}"
            f" · cuts {streaks.get('tagli')}"
            f" · consecutive increases {streaks.get('aumenti_consecutivi')}",
            f"  Anni pagati {streaks.get('anni_pagati')} su {streaks.get('anni_osservati')}"
            f" · tagli {streaks.get('tagli')}"
            f" · aumenti consecutivi {streaks.get('aumenti_consecutivi')}"))
    tr = d.total_return
    if tr.get("totale_reinvestito") is not None:
        print(L(f"  Over {tr.get('anni', 10):.0f} years: price "
                f"{fmt.pct(tr.get('solo_prezzo'), sign=True)}, with dividends reinvested "
                f"{fmt.pct(tr.get('totale_reinvestito'), sign=True)}",
                f"  In {tr.get('anni', 10):.0f} anni: prezzo "
                f"{fmt.pct(tr.get('solo_prezzo'), sign=True)}, con dividendi reinvestiti "
                f"{fmt.pct(tr.get('totale_reinvestito'), sign=True)}"))

    print(_heading(L("Dividend safety, factor by factor",
                     "Solidita' del dividendo, fattore per fattore")))
    for fattore in sicurezza.factors:
        tinta = GREEN if fattore.points > 0 else RED if fattore.points < 0 else ""
        valore = (fmt.pct(fattore.value) if fattore.fmt == "pct"
                  else fmt.mult(fattore.value) if fattore.fmt == "x"
                  else fmt.num(fattore.value, 0))
        print(f"  {fattore.label:48s} {valore:>9s}  {tinta}{fattore.points:+5.0f}{OFF}  "
                f"{fattore.explanation}")

    print(_heading(L("The story", "Il racconto")))
    for paragrafo in analisi.narrative.get(L("dividends", "dividendi"), []):
        print(f"  {paragrafo}")

    if d.source is not None:
        print(_heading(L("Where the dividends came from", "Provenienza dei dividendi")))
        print(f"  {d.source.provenance()}")
        for risultato in d.source.results:
            esito = (L(f"{risultato.payments} payments over {fmt.num(risultato.span_years, 1)} "
                       f"years",
                       f"{risultato.payments} stacchi su {fmt.num(risultato.span_years, 1)} anni")
                     if risultato.ok else (risultato.error or L("no data", "nessun dato")))
            marca = L(" <-- used", " <-- usata") if risultato.key == d.source.chosen else ""
            print(f"    {risultato.label:28s} {esito}{marca}")
        for avviso in d.source.disagreements:
            print(L(f"  {AMBER}[watch out]{OFF} {avviso}",
                    f"  {AMBER}[attenzione]{OFF} {avviso}"))


def print_analysis(analisi) -> None:
    m, v, d = analisi.metrics, analisi.valuation, analisi.verdict
    valuta = m.currency
    colore = ACTION_COLOUR.get(d.action, "")

    print(f"\n{BOLD}{m.name}{OFF}  [{m.symbol}]")
    dettagli = [x for x in (m.sector, m.industry,
                            L(f"data as of {fmt.date(m.trend.get('last_date'))}",
                              f"dati al {fmt.date(m.trend.get('last_date'))}")) if x]
    print("  " + " · ".join(dettagli))
    if analisi.data.is_demo:
        print(L(f"\n  {AMBER}SYNTHETIC DEMO DATA: invented company, the numbers are not real.{OFF}",
                f"\n  {AMBER}DATI DIMOSTRATIVI SINTETICI: societa' inventata, numeri non "
                f"reali.{OFF}"))

    print(L(f"\n{colore}{BOLD}  ==> {d.headline}{OFF}   (general fundamental analysis)",
            f"\n{colore}{BOLD}  ==> {d.headline}{OFF}   (analisi fondamentale generale)"))
    print(L(f"      score {fmt.num(d.composite, 0)}/100 · data quality: {d.data_quality}",
            f"      punteggio {fmt.num(d.composite, 0)}/100 · qualita' dei dati: {d.data_quality}"))

    print(_heading(L("Key numbers", "Numeri chiave")))
    print(L(f"  Price                        {fmt.money(m.price, valuta)}",
            f"  Prezzo                       {fmt.money(m.price, valuta)}"))
    print(L(f"  Estimated value              {fmt.money(v.fair_base, valuta)}"
            f"   ({fmt.num(v.fair_bear)} to {fmt.num(v.fair_bull)}, reliability {v.reliability})",
            f"  Valore stimato               {fmt.money(v.fair_base, valuta)}"
            f"   (da {fmt.num(v.fair_bear)} a {fmt.num(v.fair_bull)}, affidabilita' "
            f"{v.reliability})"))
    print(L(f"  Expected return over 2 years {fmt.pct(d.expected_return_2y, sign=True)}"
            f"   ({fmt.pct(d.expected_annualized, sign=True)} a year)",
            f"  Rendimento atteso a 2 anni   {fmt.pct(d.expected_return_2y, sign=True)}"
            f"   ({fmt.pct(d.expected_annualized, sign=True)} all'anno)"))
    if d.entry_price:
        print(L(f"  Entry price                  below {fmt.money(d.entry_price, valuta)}",
                f"  Prezzo d'ingresso            sotto {fmt.money(d.entry_price, valuta)}"))
    print(L(f"  P/E · P/B · dividend         {fmt.mult(m.valuation.get('pe'))} · "
            f"{fmt.mult(m.valuation.get('pb'))} · {fmt.pct(m.dividend.get('yield_current'))}",
            f"  P/E · P/B · dividendo        {fmt.mult(m.valuation.get('pe'))} · "
            f"{fmt.mult(m.valuation.get('pb'))} · {fmt.pct(m.dividend.get('yield_current'))}"))

    print(_heading(L("Score by area", "Punteggio per area")))
    for pilastro in d.pillars:
        punteggio = pilastro.score
        segno = fmt.na().rjust(5) if punteggio is None else fmt.num(punteggio, 1).rjust(5)
        tinta = "" if punteggio is None else (GREEN if punteggio >= 65
                                              else AMBER if punteggio >= 45 else RED)
        parola = "" if punteggio is None else (L("good", "buono") if punteggio >= 65
                                              else L("middling",
                                                     "medio") if punteggio >= 45 else L("weak",
                                                                                        "debole"))
        print(f"  {pilastro.label:34s} {tinta}{segno}{OFF}  {parola}")

    print(_heading(L("Why", "Perche'")))
    for motivo in d.reasons:
        print(f"  · {motivo}")
    print(f"\n  {d.position_note}")

    if d.flags:
        print(_heading(L("Red flags", "Campanelli d'allarme")))
        for segnale in d.flags:
            tinta = RED if segnale.severity == "grave" else AMBER
            etichetta = L("SERIOUS",
                          "GRAVE ") if segnale.severity == "grave" else L("warning",
                                                                                     "avviso")
            print(f"  {tinta}[{etichetta}]{OFF} {segnale.text}")

    for titolo, chiave in ((L("Past",
                              "Passato"), L("past",
                                                    "passato")), (L("Present",
                                                                            "Presente"), L("present",
                                                                                                      "presente")), (L("Future",
                                                                                                                                  "Futuro"), L("future",
                                                                                  "futuro"))):
        print(_heading(titolo))
        for paragrafo in analisi.narrative[chiave]:
            print(f"  {paragrafo}")

    print(_heading(L("When to revisit the decision", "Quando rivedere la decisione")))
    for innesco in d.review_triggers:
        print(f"  · {innesco}")

    dividendi = analisi.dividends
    if dividendi is not None and dividendi.pays_dividends and dividendi.signal:
        if dividendi.signal.action != d.action:
            print(L(f"\n  {AMBER}The two models disagree:{OFF} on dividends "
                    f"{action_label(dividendi.signal.action)}, on general fundamentals "
                    f"{action_label(d.action)}. "
                    "They look at different things: the first weighs how sustainable the coupon "
                    "is, the second earnings and equity.",
                    f"\n  {AMBER}I due modelli non concordano:{OFF} sui dividendi "
                    f"{action_label(dividendi.signal.action)}, sui fondamentali generali "
                    f"{action_label(d.action)}. "
                    "Guardano cose diverse: il primo pesa la sostenibilita' della cedola, "
                    "il secondo utili e patrimonio."))

    print(L("\n  Automated processing of public data: this is not financial advice.\n",
            "\n  Elaborazione automatica di dati pubblici: non e' consulenza finanziaria.\n"))


def _lingua_da_argv(argv: list[str] | None) -> str:
    """Legge --lang prima di costruire il parser.

    Serve un giro in piu' perche' il testo dell'aiuto nasce insieme al parser:
    se la lingua si leggesse dopo, `--lang it --help` stamperebbe un aiuto in
    inglese. Qui si guarda solo quel parametro, e il parser vero lo dichiara
    comunque, cosi' finisce nell'aiuto e viene validato come gli altri.
    """
    voci = list(sys.argv[1:] if argv is None else argv)
    for i, voce in enumerate(voci):
        if voce.startswith("--lang="):
            return set_language(voce.split("=", 1)[1])
        if voce == "--lang" and i + 1 < len(voci):
            return set_language(voci[i + 1])
    return set_language(os.environ.get("SETXRAY_LANG"))


def print_symbols(destinazione: str | None) -> int:
    """Stampa l'elenco dei titoli SET, o lo salva in un CSV.

    Salvarlo e' la mossa che lo rende indipendente dalla rete: si scarica una
    volta, si mette accanto all'app, e da quel momento l'elenco c'e' anche se
    domani la SET cambia interfaccia.
    """
    from setxray.universe import load_universe, salva_csv

    universo = load_universe(ttl_ore=0)
    if universo.parziale:
        print(f"{AMBER}" + L("No source answered: this is the built-in short list.",
                             "Nessuna fonte ha risposto: questo e' l'elenco corto incluso.")
              + f"{OFF}", file=sys.stderr)
    for nota in universo.note:
        print(f"  {nota}", file=sys.stderr)

    if destinazione and destinazione != "-":
        quanti = salva_csv(universo, destinazione)
        print(L(f"{quanti} symbols saved to {destinazione}",
                f"{quanti} simboli salvati in {destinazione}"))
        print(L("  The app reads it from there: no network needed for the list.",
                "  L'app lo legge da li': per l'elenco non serve piu' la rete."))
        return 0

    print()
    print(f"{BOLD}{universo.provenienza()}{OFF}")
    print()
    for titolo in universo.titoli:
        print(f"  {titolo.symbol:12s} {titolo.name[:52]:52s} {titolo.sector[:18]}")
    print()
    print(L("  Save it with:  python -m setxray --symbols data/set-symbols.csv",
            "  Salvalo con:   python -m setxray --symbols data/set-symbols.csv"))
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    lingua = _lingua_da_argv(argv)
    parser = argparse.ArgumentParser(
        prog="setxray",
        description=L("Analyses a Stock Exchange of Thailand (SET) share and says whether to buy, "
                      "hold or sell, over a one to two year horizon.",
                      "Analizza un'azione della Borsa di Thailandia (SET) e dice se comprare, "
                      "mantenere o vendere, con orizzonte 1-2 anni."),
        epilog=L("Demo profiles available without internet: ",
                 "Profili dimostrativi disponibili senza internet: ")
               + ", ".join(f"demo:{p}" for p in PROFILE_KEYS),
    )
    parser.add_argument("symbol", nargs="?", help=L("SET symbol, for example PTT, AOT, CPALL",
                                                    "simbolo SET, per esempio PTT, AOT, CPALL"))
    parser.add_argument("--dividends", action="store_true",
                        help=L("print only the ten-year dividend analysis",
                               "stampa solo l'analisi dei dividendi a dieci anni"))
    parser.add_argument("--sources", action="store_true",
                        help=L("list the data sources available and exit",
                               "elenca le fonti di dati disponibili ed esce"))
    parser.add_argument("--report", metavar="FILE", help=L("save the full report as markdown",
                                                           "salva il report completo in markdown"))
    parser.add_argument("--charts", metavar=L("FOLDER", "CARTELLA"),
                        help=L("save the charts as PNG in the folder given (needs kaleido)",
                               "salva i grafici in PNG nella cartella indicata (richiede kaleido)"))
    parser.add_argument("--risk-free", type=float, default=RISK_FREE_TH * 100,
                        metavar=L("PERCENT", "PERCENTO"), help=L("risk-free rate, in percent "
                          f"(default {RISK_FREE_TH * 100:.1f})",
                                                  "tasso privo di rischio, in percento "
                         f"(predefinito {RISK_FREE_TH * 100:.1f})"))
    parser.add_argument("--premium", type=float, default=EQUITY_RISK_PREMIUM_TH * 100,
                        metavar=L("PERCENT", "PERCENTO"), help=L("equity risk premium, in percent "
                          f"(default {EQUITY_RISK_PREMIUM_TH * 100:.1f})",
                                                  "premio per il rischio azionario, in percento "
                         f"(predefinito {EQUITY_RISK_PREMIUM_TH * 100:.1f})"))
    parser.add_argument("--no-cache", action="store_true", help=L("ignore the cache and refetch",
                                                                  "ignora la cache e riscarica"))
    parser.add_argument("--clear-cache", action="store_true", help=L("clear the cache and exit",
                                                                     "svuota la cache ed esce"))
    parser.add_argument("--symbols", nargs="?", const="-", metavar="FILE",
                        help=L("list every SET symbol, or save them to FILE as CSV",
                               "elenca tutti i simboli della SET, o li salva in FILE come CSV"))
    parser.add_argument("--lang", choices=list(CODES), default=lingua,
                        help=L(f"interface language (default {lingua}, or SETXRAY_LANG)",
                               f"lingua dell'interfaccia (predefinita {lingua}, o SETXRAY_LANG)"))
    parser.add_argument("--version", action="version", version=f"setxray {__version__}")
    args = parser.parse_args(argv)

    if args.sources:
        from setxray.sources import describe_sources

        print(L("\nDividend data sources, in order of trust:\n",
                "\nFonti di dati sui dividendi, in ordine di fiducia:\n"))
        for riga in describe_sources():
            stato = (L(f"{GREEN}active{OFF}", f"{GREEN}attiva{OFF}") if riga["active"]
                     else L(f"{AMBER}inactive{OFF}", f"{AMBER}inattiva{OFF}"))
            print(L(f"  {'*' * riga['trust']:5s} {riga['source']:26s} {stato:18s} "
                    f"key: {riga['api_key']}",
                    f"  {'*' * riga['trust']:5s} {riga['source']:26s} {stato:18s} "
                    f"chiave: {riga['api_key']}"))
            if riga["note"]:
                print(f"        {riga['note']}")
        print(L("\n  You can restrict the sources with SETXRAY_SOURCES=csv,yahoo",
                "\n  Puoi limitare le fonti con SETXRAY_SOURCES=csv,yahoo"))
        print(L("  The CSV goes in data/<SYMBOL>-dividends.csv with columns date,dividend\n",
                "  Il file CSV va in data/<SIMBOLO>-dividends.csv con colonne date,dividend\n"))
        return 0

    if args.symbols is not None:
        return print_symbols(args.symbols)

    if args.clear_cache:
        print(L(f"Cache cleared ({clear_cache()} files).",
                f"Cache svuotata ({clear_cache()} file)."))
        return 0
    if not args.symbol:
        parser.error(L("give a symbol, for example: python -m setxray PTT",
                       "indica un simbolo, per esempio: python -m setxray PTT"))

    try:
        analisi = analyze(args.symbol, cache_ttl_min=0 if args.no_cache else 60,
                          risk_free=args.risk_free / 100, erp=args.premium / 100)
    except (NoDataError, ValueError) as errore:
        print(L(f"{RED}Error:{OFF} {errore}", f"{RED}Errore:{OFF} {errore}"), file=sys.stderr)
        return 2
    except Exception as errore:
        print(L(f"{RED}Analysis not completed:{OFF} {type(errore).__name__} - {errore}",
                f"{RED}Analisi non completata:{OFF} {type(errore).__name__} - {errore}"),
              file=sys.stderr)
        print(L("If it keeps happening try --no-cache, or come back later: Yahoo Finance limits "
                "how many requests it accepts.",
                "Se il problema si ripete prova con --no-cache, o riprova piu' tardi: "
                "Yahoo Finance limita il numero di richieste."), file=sys.stderr)
        return 3

    if args.dividends:
        print_dividends(analisi)
    else:
        print_analysis(analisi)
        print_dividends(analisi)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as file:
            file.write(analisi.report())
        print(L(f"Report saved to {args.report}", f"Report salvato in {args.report}"))

    if args.charts:
        from setxray.charts import all_charts

        os.makedirs(args.charts, exist_ok=True)
        try:
            for nome, figura in all_charts(analisi).items():
                percorso = os.path.join(args.charts, f"{analisi.symbol}-{nome}.png")
                figura.write_image(percorso, width=1100,
                                   height=int(figura.layout.height or 380), scale=2)
            print(L(f"Charts saved to {args.charts}", f"Grafici salvati in {args.grafici}"))
        except Exception as errore:
            print(L(f"{AMBER}Charts not saved:{OFF} {type(errore).__name__} - {errore}",
                    f"{AMBER}Grafici non salvati:{OFF} {type(errore).__name__} - {errore}"),
                  file=sys.stderr)
            print(L("Exporting to PNG needs kaleido and a Chrome browser: "
                    "pip install kaleido && plotly_get_chrome",
                    "L'esportazione in PNG richiede kaleido e un browser Chrome: "
                    "pip install kaleido && plotly_get_chrome"), file=sys.stderr)
            return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
