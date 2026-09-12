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
from setxray.demo import PROFILES
from setxray.engine import NoDataError, analyze
from setxray.scoring import BUY, HOLD, SELL
from setxray.valuation import EQUITY_RISK_PREMIUM_TH, RISK_FREE_TH

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
    print(_heading("Dividends: ten years"))
    if d is None or not d.pays_dividends:
        print("  No dividend on record for this stock in the sources available.")
        for nota in (d.notes if d else []):
            print(f"  {nota}")
        return

    segnale, sicurezza, rendimento = d.signal, d.safety, d.yield_stats
    colore = ACTION_COLOUR.get(segnale.action, "")
    print(f"\n{colore}{BOLD}  ==> {segnale.headline}{OFF}")
    print(f"  Yield today                  {fmt.pct(rendimento.get('attuale'))}"
          f"   (historical median {fmt.pct(rendimento.get('mediana'))}, "
          f"percentile {fmt.pct(rendimento.get('percentile'))})")
    print(f"  Dividend, annualised         {fmt.money(rendimento.get('dps_indicato'), valuta)}")
    if d.forecast and d.forecast.ok:
        print(f"  Next 12 months estimated     {fmt.money(d.forecast.year1_base, valuta)}"
              f"   ({fmt.num(d.forecast.year1_low)} to {fmt.num(d.forecast.year1_high)})")
    banda = {"solid": GREEN, "watch closely": AMBER, "at risk": RED}.get(sicurezza.band, "")
    print(f"  Dividend safety              {banda}{fmt.num(sicurezza.score, 0)}/100 "
          f"({sicurezza.band}){OFF}, cut risk {sicurezza.cut_risk_band}")
    print(f"  Expected return over 2 years {fmt.pct(segnale.expected_return_2y, sign=True)}"
          f"   ({fmt.pct(segnale.income_component, sign=True)} coupons, "
          f"{fmt.pct(segnale.price_component, sign=True)} price)")
    etichetta = ("Would become interesting below" if segnale.action == SELL else "Buy below")
    print(f"  {etichetta:28s} {fmt.money(segnale.entry_price, valuta)}"
          f"   (value {fmt.num(segnale.fair_price)}, "
          f"trim above {fmt.num(segnale.exit_price)})")

    crescita, streaks = d.growth, d.streaks
    print(f"\n  Average dividend growth: 10 years {fmt.pct(crescita.get('cagr_10y'), sign=True)}"
          f" · 5 years {fmt.pct(crescita.get('cagr_5y'), sign=True)}"
          f" · 3 years {fmt.pct(crescita.get('cagr_3y'), sign=True)}")
    print(f"  Years paid {streaks.get('anni_pagati')} of {streaks.get('anni_osservati')}"
          f" · cuts {streaks.get('tagli')}"
          f" · consecutive increases {streaks.get('aumenti_consecutivi')}")
    tr = d.total_return
    if tr.get("totale_reinvestito") is not None:
        print(f"  Over {tr.get('anni', 10):.0f} years: price "
              f"{fmt.pct(tr.get('solo_prezzo'), sign=True)}, with dividends reinvested "
              f"{fmt.pct(tr.get('totale_reinvestito'), sign=True)}")

    print(_heading("Dividend safety, factor by factor"))
    for fattore in sicurezza.factors:
        tinta = GREEN if fattore.points > 0 else RED if fattore.points < 0 else ""
        valore = (fmt.pct(fattore.value) if fattore.fmt == "pct"
                  else fmt.mult(fattore.value) if fattore.fmt == "x"
                  else fmt.num(fattore.value, 0))
        print(f"  {fattore.label:48s} {valore:>9s}  {tinta}{fattore.points:+5.0f}{OFF}  "
              f"{fattore.explanation}")

    print(_heading("The story"))
    for paragrafo in analisi.narrative.get("dividends", []):
        print(f"  {paragrafo}")

    if d.source is not None:
        print(_heading("Where the dividends came from"))
        print(f"  {d.source.provenance()}")
        for risultato in d.source.results:
            esito = (f"{risultato.payments} payments over {risultato.span_years:.1f} years"
                     if risultato.ok else (risultato.error or "no data"))
            marca = " <-- used" if risultato.key == d.source.chosen else ""
            print(f"    {risultato.label:28s} {esito}{marca}")
        for avviso in d.source.disagreements:
            print(f"  {AMBER}[watch out]{OFF} {avviso}")


def print_analysis(analisi) -> None:
    m, v, d = analisi.metrics, analisi.valuation, analisi.verdict
    valuta = m.currency
    colore = ACTION_COLOUR.get(d.action, "")

    print(f"\n{BOLD}{m.name}{OFF}  [{m.symbol}]")
    dettagli = [x for x in (m.sector, m.industry,
                            f"data as of {fmt.date(m.trend.get('last_date'))}") if x]
    print("  " + " · ".join(dettagli))
    if analisi.data.is_demo:
        print(f"\n  {AMBER}SYNTHETIC DEMO DATA: invented company, the numbers are not real.{OFF}")

    print(f"\n{colore}{BOLD}  ==> {d.headline}{OFF}   (general fundamental analysis)")
    print(f"      score {fmt.num(d.composite, 0)}/100 · data quality: {d.data_quality}")

    print(_heading("Key numbers"))
    print(f"  Price                        {fmt.money(m.price, valuta)}")
    print(f"  Estimated value              {fmt.money(v.fair_base, valuta)}"
          f"   ({fmt.num(v.fair_bear)} to {fmt.num(v.fair_bull)}, reliability {v.reliability})")
    print(f"  Expected return over 2 years {fmt.pct(d.expected_return_2y, sign=True)}"
          f"   ({fmt.pct(d.expected_annualized, sign=True)} a year)")
    if d.entry_price:
        print(f"  Entry price                  below {fmt.money(d.entry_price, valuta)}")
    print(f"  P/E · P/B · dividend         {fmt.mult(m.valuation.get('pe'))} · "
          f"{fmt.mult(m.valuation.get('pb'))} · {fmt.pct(m.dividend.get('yield_current'))}")

    print(_heading("Score by area"))
    for pilastro in d.pillars:
        punteggio = pilastro.score
        segno = fmt.NA.rjust(5) if punteggio is None else fmt.num(punteggio, 1).rjust(5)
        tinta = "" if punteggio is None else (GREEN if punteggio >= 65
                                              else AMBER if punteggio >= 45 else RED)
        parola = "" if punteggio is None else ("good" if punteggio >= 65
                                              else "middling" if punteggio >= 45 else "weak")
        print(f"  {pilastro.label:34s} {tinta}{segno}{OFF}  {parola}")

    print(_heading("Why"))
    for motivo in d.reasons:
        print(f"  · {motivo}")
    print(f"\n  {d.position_note}")

    if d.flags:
        print(_heading("Red flags"))
        for segnale in d.flags:
            tinta = RED if segnale.severity == "grave" else AMBER
            etichetta = "SERIOUS" if segnale.severity == "grave" else "warning"
            print(f"  {tinta}[{etichetta}]{OFF} {segnale.text}")

    for titolo, chiave in (("Past", "past"), ("Present", "present"), ("Future", "future")):
        print(_heading(titolo))
        for paragrafo in analisi.narrative[chiave]:
            print(f"  {paragrafo}")

    print(_heading("When to revisit the decision"))
    for innesco in d.review_triggers:
        print(f"  · {innesco}")

    dividendi = analisi.dividends
    if dividendi is not None and dividendi.pays_dividends and dividendi.signal:
        if dividendi.signal.action != d.action:
            print(f"\n  {AMBER}The two models disagree:{OFF} on dividends "
                  f"{dividendi.signal.action}, on general fundamentals {d.action}. "
                  "They look at different things: the first weighs how sustainable the coupon "
                  "is, the second earnings and equity.")

    print("\n  Automated processing of public data: this is not financial advice.\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="setxray",
        description="Analyses a Stock Exchange of Thailand (SET) share and says whether to buy, "
                    "hold or sell, over a one to two year horizon.",
        epilog="Demo profiles available without internet: "
               + ", ".join(f"demo:{p}" for p in PROFILES),
    )
    parser.add_argument("symbol", nargs="?", help="SET symbol, for example PTT, AOT, CPALL")
    parser.add_argument("--dividends", action="store_true",
                        help="print only the ten-year dividend analysis")
    parser.add_argument("--sources", action="store_true",
                        help="list the data sources available and exit")
    parser.add_argument("--report", metavar="FILE", help="save the full report as markdown")
    parser.add_argument("--charts", metavar="FOLDER",
                        help="save the charts as PNG in the folder given (needs kaleido)")
    parser.add_argument("--risk-free", type=float, default=RISK_FREE_TH * 100,
                        metavar="PERCENT", help="risk-free rate, in percent "
                        f"(default {RISK_FREE_TH * 100:.1f})")
    parser.add_argument("--premium", type=float, default=EQUITY_RISK_PREMIUM_TH * 100,
                        metavar="PERCENT", help="equity risk premium, in percent "
                        f"(default {EQUITY_RISK_PREMIUM_TH * 100:.1f})")
    parser.add_argument("--no-cache", action="store_true", help="ignore the cache and refetch")
    parser.add_argument("--clear-cache", action="store_true", help="clear the cache and exit")
    parser.add_argument("--version", action="version", version=f"setxray {__version__}")
    args = parser.parse_args(argv)

    if args.sources:
        from setxray.sources import describe_sources

        print("\nDividend data sources, in order of trust:\n")
        for riga in describe_sources():
            stato = f"{GREEN}active{OFF}" if riga["active"] else f"{AMBER}inactive{OFF}"
            print(f"  {'*' * riga['trust']:5s} {riga['source']:26s} {stato:18s} "
                  f"key: {riga['api_key']}")
            if riga["note"]:
                print(f"        {riga['note']}")
        print("\n  You can restrict the sources with SETXRAY_SOURCES=csv,yahoo")
        print("  The CSV goes in data/<SYMBOL>-dividends.csv with columns date,dividend\n")
        return 0

    if args.clear_cache:
        print(f"Cache cleared ({clear_cache()} files).")
        return 0
    if not args.symbol:
        parser.error("give a symbol, for example: python -m setxray PTT")

    try:
        analisi = analyze(args.symbol, cache_ttl_min=0 if args.no_cache else 60,
                          risk_free=args.risk_free / 100, erp=args.premium / 100)
    except (NoDataError, ValueError) as errore:
        print(f"{RED}Error:{OFF} {errore}", file=sys.stderr)
        return 2
    except Exception as errore:
        print(f"{RED}Analysis not completed:{OFF} {type(errore).__name__} - {errore}",
              file=sys.stderr)
        print("If it keeps happening try --no-cache, or come back later: Yahoo Finance limits "
              "how many requests it accepts.", file=sys.stderr)
        return 3

    if args.dividends:
        print_dividends(analisi)
    else:
        print_analysis(analisi)
        print_dividends(analisi)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as file:
            file.write(analisi.report())
        print(f"Report saved to {args.report}")

    if args.charts:
        from setxray.charts import all_charts

        os.makedirs(args.charts, exist_ok=True)
        try:
            for nome, figura in all_charts(analisi).items():
                percorso = os.path.join(args.charts, f"{analisi.symbol}-{nome}.png")
                figura.write_image(percorso, width=1100,
                                   height=int(figura.layout.height or 380), scale=2)
            print(f"Charts saved to {args.charts}")
        except Exception as errore:
            print(f"{AMBER}Charts not saved:{OFF} {type(errore).__name__} - {errore}",
                  file=sys.stderr)
            print("Exporting to PNG needs kaleido and a Chrome browser: "
                  "pip install kaleido && plotly_get_chrome", file=sys.stderr)
            return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
