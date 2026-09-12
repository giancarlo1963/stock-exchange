"""The charts: few, large, and each one answers a single question.

Rules followed here, because they are not obvious:
- never two vertical axes in the same chart. Two quantities with different
  units (baht and percentages) become two charts, or two panels side by side:
  overlaying them would invent a correlation the data does not contain;
- one series, one colour, always the same one: the colour identifies the
  quantity, not its position in a ranking;
- thin continuous grids and axes, thin markers, labels only where they are
  needed. A chart should be easy to read, not eager to be noticed;
- scores use the status colours (green/amber/red) always accompanied by the
  number, because colour alone is not enough for those who cannot tell it apart.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from setxray import fmt
from setxray.metrics import (RSI_IPERCOMPRATO, RSI_IPERVENDUTO, RSI_PERIODS,
                             Metrics, rsi)
from setxray.scoring import Verdict
from setxray.valuation import Valuation
from setxray.lang import L

# --- colour tokens (palette validated for colour blindness, light and dark) -
LIGHT = {
    "surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
    "grid": "#e1e0d9", "axis": "#c3c2b7", "band": "rgba(11,11,11,0.06)",
    "s1": "#2a78d6", "s2": "#eb6834", "s3": "#1baf7a", "s4": "#eda100",
    "good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b",
    "band_good": "rgba(12,163,12,0.10)", "band_bad": "rgba(208,59,59,0.10)",
}
DARK = {
    "surface": "#1a1a19", "ink": "#ffffff", "ink2": "#c3c2b7", "muted": "#898781",
    "grid": "#2c2c2a", "axis": "#383835", "band": "rgba(255,255,255,0.08)",
    "s1": "#3987e5", "s2": "#d95926", "s3": "#199e70", "s4": "#c98500",
    "good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b",
    "band_good": "rgba(12,163,12,0.16)", "band_bad": "rgba(208,59,59,0.16)",
}
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def tokens(dark: bool = False) -> dict:
    return DARK if dark else LIGHT


def _layout(fig: go.Figure, t: dict, *, title: str, subtitle: str = "",
            height: int = 380, percent_axis: bool = False, unit: str = "") -> go.Figure:
    """Shared frame: title, subtitle, light grid, legend on top."""
    heading = f"<b>{title}</b>"
    if subtitle:
        heading += f"<br><span style='font-size:12px;color:{t['ink2']}'>{subtitle}</span>"
    fig.update_layout(
        # Plotly formatta da se' i numeri sugli assi e nei riquadri al
        # passaggio del mouse: `separators` e' l'unico modo di dirgli quale
        # lingua stiamo parlando (decimale prima, migliaia dopo).
        separators=L(".,", ",."),
        title=dict(text=heading, x=0, xanchor="left", font=dict(size=16, color=t["ink"])),
        paper_bgcolor=t["surface"], plot_bgcolor=t["surface"],
        font=dict(family=FONT, size=12, color=t["ink2"]),
        height=height, margin=dict(l=56, r=24, t=84 if subtitle else 64, b=48),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
        hovermode="x unified",
        hoverlabel=dict(bgcolor=t["surface"], font=dict(family=FONT, size=12, color=t["ink"]),
                        bordercolor=t["axis"]),
        bargap=0.45, bargroupgap=0.12,  # thin bars: less mass, more air
        showlegend=len(fig.data) > 1,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=t["axis"], linewidth=1,
                     ticks="outside", tickcolor=t["axis"], tickfont=dict(color=t["muted"], size=11))
    fig.update_yaxes(showgrid=True, gridcolor=t["grid"], gridwidth=1, zeroline=True,
                     zerolinecolor=t["axis"], zerolinewidth=1, linewidth=0,
                     tickfont=dict(color=t["muted"], size=11),
                     title=dict(text=unit, font=dict(size=11, color=t["muted"])))
    if percent_axis:
        fig.update_yaxes(tickformat=".0%")
    return fig


def _empty(message: str, t: dict, height: int = 220) -> go.Figure:
    """Explicit placeholder: better to say the data is missing than to show an empty chart."""
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5,
                       font=dict(family=FONT, size=13, color=t["muted"]))
    fig.update_layout(paper_bgcolor=t["surface"], plot_bgcolor=t["surface"], height=height,
                      margin=dict(l=20, r=20, t=20, b=20),
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def _bar(x, y, name, color, t, *, unit="", hover_pct=False):
    template = "%{y:.1%}" if hover_pct else "%{y:,.2f}"
    return go.Bar(
        x=x, y=y, name=name, marker=dict(color=color, cornerradius=4,
                                         line=dict(color=t["surface"], width=2)),
        hovertemplate=f"{name}: {template}{unit}<extra></extra>",
    )


def _line(x, y, name, color, t, *, width=2, pct=False, end_label: Optional[str] = None):
    """One line series. `end_label` writes the value beside the last point.

    The label travels inside the trace rather than as an annotation: on a
    categorical axis (the financial years) an annotation with a text x does
    not position itself.
    """
    template = "%{y:.1%}" if pct else "%{y:,.2f}"
    trace = go.Scatter(
        x=x, y=y, name=name, mode="lines",
        line=dict(color=color, width=width),
        hovertemplate=f"{name}: {template}<extra></extra>",
    )
    if end_label is not None:
        texts = [""] * (len(x) - 1) + [f"  {end_label}"]
        trace.update(mode="lines+markers+text", text=texts, textposition="middle right",
                     textfont=dict(size=11, color=color),
                     marker=dict(color=color, size=7, line=dict(color=t["surface"], width=2)))
    return trace


# --------------------------------------------------------------------------
# 1. price, moving averages and the value range
# --------------------------------------------------------------------------
def price_chart(m: Metrics, v: Valuation, prices: Optional[pd.DataFrame], dark: bool = False) -> go.Figure:
    t = tokens(dark)
    if prices is None or prices.empty:
        return _empty(L("Price history not available", "Storico prezzi non disponibile"), t)
    close = prices["Close"].dropna()
    fig = go.Figure()

    # The value range as a horizontal band: you see at once whether the price
    # sits inside it, below it or above it.
    if v.fair_bear and v.fair_bull:
        fig.add_hrect(y0=v.fair_bear, y1=v.fair_bull, fillcolor=t["band"], line_width=0, layer="below")
    fig.add_trace(_line(close.index, close.values, L("Price", "Prezzo"), t["s1"], t, width=2))
    if len(close) >= 200:
        fig.add_trace(_line(close.index, close.rolling(200).mean(), L("200-day average",
                                                                      "Media 200 giorni"), t["s3"], t, width=1.5))
    if len(close) >= 50:
        fig.add_trace(_line(close.index, close.rolling(50).mean(), L("50-day average",
                                                                     "Media 50 giorni"), t["s2"], t, width=1.5))
    if v.fair_base:
        fig.add_hline(y=v.fair_base, line=dict(color=t["ink2"], width=1.5),
                      annotation_text=L(f"estimated value {fmt.num(v.fair_base)}",
                                        f"valore stimato {fmt.num(v.fair_base)}"),
                      annotation_position="top right",
                      annotation_font=dict(size=11, color=t["ink2"]))
    if m.price:
        fig.add_trace(go.Scatter(
            x=[close.index[-1]], y=[m.price], mode="markers+text", name=L("today", "oggi"),
            marker=dict(color=t["s1"], size=9, line=dict(color=t["surface"], width=2)),
            text=[f" {fmt.num(m.price)}"], textposition="middle right",
            textfont=dict(size=12, color=t["ink"]), showlegend=False,
            hovertemplate=L("today: %{y:,.2f}<extra></extra>", "oggi: %{y:,.2f}<extra></extra>"),
        ))
    return _layout(fig, t, title=L("Price and estimated value", "Prezzo e valore stimato"),
                   subtitle=L(f"Closing prices in {m.currency}. The grey band is the value range "
                              "estimated by the models, from the pessimistic to the optimistic "
                              "scenario.",
                              f"Chiusure in {m.currency}. La fascia grigia e' la forchetta di "
                              f"valore "
                              "stimata dai modelli, dallo scenario pessimistico a quello "
                              "ottimistico."),
                   height=420, unit=m.currency)


# --------------------------------------------------------------------------
# 2. comparison against the SET index
# --------------------------------------------------------------------------
def relative_chart(m: Metrics, prices: Optional[pd.DataFrame],
                   benchmark: Optional[pd.DataFrame], dark: bool = False) -> go.Figure:
    t = tokens(dark)
    if prices is None or prices.empty:
        return _empty(L("Price history not available", "Storico prezzi non disponibile"), t)
    if benchmark is None or benchmark.empty:
        return _empty(L("SET index not available for the comparison",
                        "Indice SET non disponibile per il confronto"), t)
    stock = prices["AdjClose"].dropna()
    index = benchmark["AdjClose"].dropna()
    joined = pd.concat([stock.rename("t"), index.rename("i")], axis=1).dropna()
    if joined.empty:
        return _empty(L("No period in common between the stock and the index",
                        "Nessun periodo in comune fra titolo e indice"), t)
    # Both series rebased to 100: the only correct way to compare two
    # quantities of different scale without a second axis.
    joined = joined / joined.iloc[0] * 100
    fig = go.Figure()
    fig.add_trace(_line(joined.index, joined["t"], m.symbol, t["s1"], t))
    fig.add_trace(_line(joined.index, joined["i"], L("SET index",
                                                     "Indice SET"), t["s2"], t, width=1.5))
    for column, color, label in (("t", t["s1"], m.symbol), ("i", t["s2"], "SET")):
        fig.add_annotation(x=joined.index[-1], y=joined[column].iloc[-1], text=f" {label}",
                           showarrow=False, xanchor="left", font=dict(size=11, color=color))
    return _layout(fig, t, title=L("Stock against the SET index", "Titolo contro indice SET"),
                   subtitle=L("Total return, both rebased to 100 at the start date",
                              "Rendimento totale, entrambi ribasati a 100 alla data iniziale"),
                   height=340, unit=L("index = 100", "indice = 100"))


# --------------------------------------------------------------------------
# 3. revenue and net income
# --------------------------------------------------------------------------
def revenue_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty or "revenue" not in years:
        return _empty(L("Income statement not available", "Conto economico non disponibile"), t)
    labels = m.year_labels()
    scale, unit = (1e9, L(f"bn {m.currency}",
                          f"mld {m.currency}")) if years["revenue"].max() >= 1e9 else (1e6, L(f"m {m.currency}",
                                                                                          f"mln {m.currency}"))
    fig = go.Figure()
    fig.add_trace(_bar(labels, years["revenue"] / scale, L("Revenue",
                                                           "Ricavi"), t["s1"], t, unit=f" {unit}"))
    if "net_income" in years:
        fig.add_trace(_bar(labels, years["net_income"] / scale, L("Net income",
                                                                  "Utile netto"), t["s2"], t, unit=f" {unit}"))
    return _layout(fig, t, title=L("Revenue and net income by financial year",
                                   "Ricavi e utile netto per esercizio"),
                   subtitle=L("What it bills and what is left of it, year by year",
                              "Quanto fattura e quanto ne resta, anno per anno"), height=340, unit=unit)


# --------------------------------------------------------------------------
# 4. margins
# --------------------------------------------------------------------------
def margins_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty:
        return _empty(L("Margins cannot be computed without an income statement",
                        "Margini non calcolabili senza conto economico"), t)
    labels = m.year_labels()
    fig = go.Figure()
    for column, name, color in (("gross_margin", L("Gross margin", "Margine lordo"), t["s1"]),
                                ("operating_margin", L("Operating margin",
                                                       "Margine operativo"), t["s2"]),
                                ("net_margin", L("Net margin", "Margine netto"), t["s3"])):
        if column in years and years[column].notna().any():
            series = years[column]
            last = series.dropna()
            # The value written beside the last point: it identifies the series
            # even for those who cannot tell the colours apart.
            label = fmt.pct(last.iloc[-1]) if not last.empty else None
            fig.add_trace(_line(labels, series.values, name, color, t, pct=True, end_label=label))
    if not fig.data:
        return _empty(L("Margins not available", "Margini non disponibili"), t)
    fig = _layout(fig, t, title=L("Margins", "Margini"),
                  subtitle=L("How much of the revenue survives at each level of the income "
                             "statement",
                             "Quanta parte dei ricavi resta a ogni livello del conto economico"),
                  height=320, percent_axis=True)
    # Room on the right for the labels written beside the last point.
    fig.update_xaxes(range=[-0.4, len(labels) - 0.25])
    return fig


# --------------------------------------------------------------------------
# 5. returns on capital
# --------------------------------------------------------------------------
def returns_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty:
        return _empty(L("Returns cannot be computed without financial statements",
                        "Redditivita' non calcolabile senza bilanci"), t)
    labels = m.year_labels()
    fig = go.Figure()
    for column, name, color in (("roe", L("ROE (on equity)", "ROE (sul patrimonio)"), t["s1"]),
                                ("roic", L("ROIC (on invested capital)",
                                           "ROIC (sul capitale investito)"), t["s2"]),
                                ("roa", L("ROA (on assets)", "ROA (sull'attivo)"), t["s3"])):
        if column in years and years[column].notna().any():
            fig.add_trace(_bar(labels, years[column], name, color, t, hover_pct=True))
    if not fig.data:
        return _empty(L("Return ratios not available", "Indici di redditivita' non disponibili"), t)
    return _layout(fig, t, title=L("Returns on capital", "Redditivita' del capitale"),
                   subtitle=L("What the capital employed earns: above 10-12% the company creates "
                              "value by reinvesting",
                              "Quanto rende il capitale impiegato: sopra il 10-12% l'azienda crea "
                              "valore reinvestendo"),
                   height=320, percent_axis=True)


# --------------------------------------------------------------------------
# 6. cash flows
# --------------------------------------------------------------------------
def cashflow_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty or "cfo" not in years:
        return _empty(L("Cash flow statement not available",
                        "Rendiconto finanziario non disponibile"), t)
    labels = m.year_labels()
    scale, unit = (1e9, L(f"bn {m.currency}",
                          f"mld {m.currency}")) if years["cfo"].abs().max() >= 1e9 else (1e6, L(f"m {m.currency}",
                                                                                            f"mln {m.currency}"))
    fig = go.Figure()
    fig.add_trace(_bar(labels, years["cfo"] / scale, L("Cash from operations",
                                                       "Cassa dall'attivita'"), t["s1"], t, unit=f" {unit}"))
    if "capex" in years:
        fig.add_trace(_bar(labels, years["capex"] / scale, L("Capital spending",
                                                             "Investimenti"), t["s2"], t, unit=f" {unit}"))
    if "fcf" in years:
        # A third bar, not a line: it is the same unit as the other two, and a
        # line laid over bars reads badly.
        fig.add_trace(_bar(labels, years["fcf"] / scale, L("Free cash flow",
                                                           "Cassa libera"), t["s3"], t, unit=f" {unit}"))
    return _layout(fig, t, title=L("Where the cash comes from and where it goes",
                                   "Da dove viene e dove va la cassa"),
                   subtitle=L("Cash generated by operations, capital spending (negative) and the "
                              "free cash left over",
                              "Cassa generata dall'attivita', investimenti (negativi) e cassa "
                              "libera che resta"),
                   height=340, unit=unit)


# --------------------------------------------------------------------------
# 7. earnings and dividend per share
# --------------------------------------------------------------------------
def eps_dividend_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty or "eps" not in years:
        return _empty(L("Earnings per share not available", "Utile per azione non disponibile"), t)
    labels = m.year_labels()
    fig = go.Figure()
    fig.add_trace(_bar(labels, years["eps"], L("Earnings per share",
                                               "Utile per azione"), t["s1"], t, unit=f" {m.currency}"))
    if "dps" in years and years["dps"].notna().any():
        fig.add_trace(_bar(labels, years["dps"], L("Dividend per share",
                                                   "Dividendo per azione"), t["s2"], t, unit=f" {m.currency}"))
    return _layout(fig, t, title=L("Earnings and dividend per share",
                                   "Utile e dividendo per azione"),
                   subtitle=L("The gap between the two bars is the profit reinvested in the "
                              "business",
                              "La differenza fra le due barre e' l'utile reinvestito nell'azienda"),
                   height=320, unit=m.currency)


# --------------------------------------------------------------------------
# 8. financial strength (panels side by side, different scales)
# --------------------------------------------------------------------------
def health_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty:
        return _empty(L("Balance sheet data not available", "Dati di bilancio non disponibili"), t)
    labels = m.year_labels()
    panels = [
        ("net_debt_ebitda", L("Net debt / EBITDA",
                              "Debito netto / EBITDA"), L("times",
                                                                               "volte"), False),
        ("interest_coverage", L("Interest coverage",
                                "Copertura interessi"), L("times",
                                                                               "volte"), False),
        ("debt_equity", L("Debt / equity", "Debito / patrimonio"), L("times", "volte"), False),
        ("payout", L("Share of earnings paid out", "Utili distribuiti"), "%", True),
    ]
    available = [p for p in panels if p[0] in years and years[p[0]].notna().any()]
    if not available:
        return _empty(L("Financial strength indicators cannot be computed",
                        "Indicatori di solidita' non calcolabili"), t)
    # Four quantities, four panels: different units and scales cannot share
    # the same axis.
    fig = make_subplots(rows=1, cols=len(available), subplot_titles=[p[1] for p in available],
                        horizontal_spacing=0.07)
    for i, (column, name, _unit, is_pct) in enumerate(available, start=1):
        series = years[column]
        fig.add_trace(
            go.Bar(x=labels, y=series, width=0.5,
                   marker=dict(color=t["s1"], cornerradius=4,
                               line=dict(color=t["surface"], width=2)),
                   name=name, showlegend=False,
                   hovertemplate=("%{y:.0%}" if is_pct else "%{y:,.2f}x") + "<extra></extra>"),
            row=1, col=i,
        )
        fig.update_yaxes(tickformat=".0%" if is_pct else ".1f", row=1, col=i)
    fig = _layout(fig, t, title=L("Financial strength over time",
                                  "Solidita' finanziaria nel tempo"),
                  subtitle=L("Four measures with different units, hence four separate panels",
                             "Quattro misure con unita' diverse, quindi quattro riquadri separati"),
                  height=360)
    for annotation in fig.layout.annotations:
        annotation.font = dict(size=12, color=t["ink2"], family=FONT)
        # Panel titles are born stuck to the chart title: we push them down
        # and widen the margin to fit them.
        if annotation.yref == "paper" and annotation.y and annotation.y > 0.9:
            annotation.y = 0.93
    fig.update_layout(showlegend=False, margin=dict(l=56, r=24, t=120, b=48))
    return fig


# --------------------------------------------------------------------------
# 8b. RSI: il prezzo e' corso troppo in fretta?
# --------------------------------------------------------------------------
def rsi_chart(m: Metrics, prices: Optional[pd.DataFrame], dark: bool = False,
              anni: float = 2.0) -> go.Figure:
    """L'RSI con le due zone, ipercomprato e ipervenduto.

    Due anni e non dieci: l'RSI e' un indicatore di settimane, e dieci anni di
    valori giornalieri diventano una matassa in cui non si legge niente.
    """
    t = tokens(dark)
    if prices is None or prices.empty:
        return _empty(L("Price history not available", "Storico prezzi non disponibile"), t)
    serie = rsi(prices["Close"])
    if serie is None or serie.empty:
        return _empty(L("Price history too short to compute the RSI",
                        "Storico prezzi troppo corto per calcolare l'RSI"), t)
    finestra = serie[serie.index >= serie.index[-1] - pd.Timedelta(days=int(365.25 * anni))]
    if len(finestra) < 30:
        finestra = serie

    fig = go.Figure()
    # Le zone come fasce, non come linee tratteggiate: la fascia dice "qui
    # dentro" mentre una linea dice solo "sopra questo".
    fig.add_hrect(y0=RSI_IPERCOMPRATO, y1=100, fillcolor=t["band_bad"], line_width=0, layer="below")
    fig.add_hrect(y0=0, y1=RSI_IPERVENDUTO, fillcolor=t["band_good"], line_width=0, layer="below")
    fig.add_hline(y=50, line=dict(color=t["axis"], width=1))
    fig.add_trace(_line(finestra.index, finestra.values, L("RSI", "RSI"), t["s1"], t, width=1.8))

    for valore, colore, testo in (
            (RSI_IPERCOMPRATO, t["critical"], L("overbought 70", "ipercomprato 70")),
            (RSI_IPERVENDUTO, t["good"], L("oversold 30", "ipervenduto 30"))):
        fig.add_hline(y=valore, line=dict(color=colore, width=1.2),
                      annotation_text=testo, annotation_position="top left",
                      annotation_font=dict(size=11, color=colore))

    attuale = float(finestra.iloc[-1])
    zona = (L("overbought", "ipercomprato") if attuale >= RSI_IPERCOMPRATO
            else L("oversold", "ipervenduto") if attuale <= RSI_IPERVENDUTO
            else L("neutral", "zona neutra"))
    colore = (t["critical"] if attuale >= RSI_IPERCOMPRATO
              else t["good"] if attuale <= RSI_IPERVENDUTO else t["ink2"])
    fig.add_trace(go.Scatter(
        x=[finestra.index[-1]], y=[attuale], mode="markers+text", showlegend=False,
        marker=dict(color=colore, size=9, line=dict(color=t["surface"], width=2)),
        text=[f"  {fmt.num(attuale, 0)}"], textposition="middle right",
        textfont=dict(size=12, color=colore),
        hovertemplate=L("today: %{y:.0f}<extra></extra>", "oggi: %{y:.0f}<extra></extra>"),
    ))

    fig = _layout(
        fig, t,
        title=L(f"RSI at {RSI_PERIODS} days: has the price run too fast?",
                f"RSI a {RSI_PERIODS} giorni: il prezzo e' corso troppo?"),
        # Il sottotitolo va a capo a mano: Plotly non manda a capo il titolo, e
        # su uno schermo strétto la riga finirebbe fuori dal riquadro.
        subtitle=L(f"Today {fmt.num(attuale, 0)}, {zona}. Above 70 the recent rise has been "
                   "one-sided, below 30 the fall has."
                   "<br>It measures weeks, not years: it helps pick the day to buy, not what "
                   "to buy.",
                   f"Oggi {fmt.num(attuale, 0)}, {zona}. Sopra 70 la salita recente e' stata "
                   "tutta in una direzione, sotto 30 lo e' stata la discesa."
                   "<br>Misura settimane, non anni: serve a scegliere il giorno in cui "
                   "comprare, non cosa comprare."),
        height=320)
    fig.update_yaxes(range=[0, 100], tickvals=[0, 30, 50, 70, 100])
    # due righe di sottotitolo hanno bisogno di piu' spazio in alto
    fig.update_layout(showlegend=False, margin=dict(l=56, r=44, t=104, b=48))
    return fig


# --------------------------------------------------------------------------
# 9. history of the multiple
# --------------------------------------------------------------------------
def multiple_history_chart(m: Metrics, key: str = "pe", dark: bool = False) -> go.Figure:
    t = tokens(dark)
    names = {"pe": L("P/E (price / earnings)",
                     "P/E (prezzo / utili)"), "pb": L("P/B (price / book value)",
                                                     "P/B (prezzo / patrimonio)"),
             "ps": L("P/S (price / revenue)", "P/S (prezzo / ricavi)"), "ev_ebitda": "EV/EBITDA"}
    hist = m.multiple_history.get(key)
    if not hist:
        return _empty(L(f"History of the {names.get(key, key)} not available",
                        f"Storico del {names.get(key, key)} non disponibile"), t)
    series = hist["series"]
    fig = go.Figure()
    fig.add_hrect(y0=hist["p25"], y1=hist["p75"], fillcolor=t["band"], line_width=0, layer="below")
    fig.add_trace(go.Scatter(
        x=series.index, y=series.values, mode="lines+markers", name=names.get(key, key),
        line=dict(color=t["s1"], width=2),
        marker=dict(color=t["s1"], size=8, line=dict(color=t["surface"], width=2)),
        hovertemplate="%{x|%m/%Y}: %{y:.1f}x<extra></extra>",
    ))
    fig.add_hline(y=hist["median"], line=dict(color=t["ink2"], width=1.5),
                  annotation_text=L(f"median {fmt.mult(hist['median'])}",
                                    f"mediana {fmt.mult(hist['median'])}"), annotation_position="top right",
                  annotation_font=dict(size=11, color=t["ink2"]))
    current = m.valuation.get(key)
    if current:
        colour = t["good"] if current < hist["median"] else t["critical"]
        fig.add_hline(y=current, line=dict(color=colour, width=2),
                      annotation_text=L(f"today {fmt.mult(current)}",
                                        f"oggi {fmt.mult(current)}"), annotation_position="bottom right",
                      annotation_font=dict(size=11, color=colour))
    percentile = hist.get("percentile")
    # "in the bottom 0%" means nothing: better to say how many observations it beats.
    where = ("" if percentile is None
             else L(f" Today it is cheaper than {1 - percentile:.0%} of its historical "
                    f"observations.",
                    f" Oggi e' piu' economico del {1 - percentile:.0%} delle osservazioni storiche."))
    return _layout(fig, t, title=L(f"{names.get(key, key)}: what it costs against its own past",
                                   f"{names.get(key, key)}: quanto costa rispetto al suo passato"),
                   subtitle=L(f"Grey zone: the central half of the historical values.{where}",
                              f"Zona grigia: meta' centrale dei valori storici.{where}"),
                   height=330, unit=L("times", "volte"))


# --------------------------------------------------------------------------
# 10. score by area
# --------------------------------------------------------------------------
def pillars_chart(verdict: Verdict, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    pillars = [p for p in verdict.pillars if p.score is not None]
    if not pillars:
        return _empty(L("Scores cannot be computed", "Punteggi non calcolabili"), t)
    pillars = sorted(pillars, key=lambda p: p.score)
    labels = [p.label for p in pillars]
    scores = [p.score for p in pillars]
    # Status colours, not series colours: here the colour means
    # "pass / watch closely / fail". The number is always written out.
    colors = [t["good"] if s >= 65 else t["warning"] if s >= 45 else t["critical"] for s in scores]
    # Colour alone is not enough for those who cannot tell it apart: beside the
    # number we always put the word.
    words = [L("good",
               "buono") if s >= 65 else L("middling",
                                                  "medio") if s >= 45 else L("weak",
                                                                                         "debole") for s in scores]
    fig = go.Figure(go.Bar(
        x=scores, y=labels, orientation="h", width=0.5,
        marker=dict(color=colors, cornerradius=4, line=dict(color=t["surface"], width=2)),
        text=[f"{s:.0f} - {w}" for s, w in zip(scores, words)], textposition="outside",
        textfont=dict(size=12, color=t["ink"]),
        hovertemplate="%{y}: %{x:.0f}/100<extra></extra>", showlegend=False,
    ))
    fig.add_vline(x=50, line=dict(color=t["axis"], width=1))
    fig = _layout(fig, t, title=L("Score by area", "Punteggio per area"),
                  subtitle=L("0-100. Green above 65, amber between 45 and 65, red below 45. The "
                             "line marks the halfway point.",
                             "0-100. Verde sopra 65, giallo fra 45 e 65, rosso sotto 45. La linea "
                             "segna la meta'."),
                  height=300)
    # The axis stops at 100, but the scale leaves room for the label beside the
    # longest bar.
    fig.update_xaxes(range=[0, 132], showgrid=True, gridcolor=t["grid"], linewidth=0,
                     tickvals=[0, 20, 40, 60, 80, 100])
    fig.update_yaxes(showgrid=False, zeroline=False, tickfont=dict(size=12, color=t["ink2"]))
    fig.update_layout(showlegend=False, hovermode="closest",
                      margin=dict(l=220, r=32, t=84, b=40))
    return fig


# --------------------------------------------------------------------------
# 11. the valuation methods side by side
# --------------------------------------------------------------------------
def methods_chart(m: Metrics, v: Valuation, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    usable = [method for method in v.methods if method.usable]
    if not usable:
        return _empty(L("No valuation model applicable",
                        "Nessun modello di valutazione applicabile"), t)
    # Plotly draws horizontal bars from the bottom up: we reverse the order so
    # they read from the top, as the text describes them.
    labels = [method.label for method in usable][::-1]
    values = [method.fair_value for method in usable][::-1]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=values, y=labels, orientation="h", width=0.55, name=L("Individual models",
                                                                "Singoli modelli"),
        marker=dict(color=t["s1"], cornerradius=4, line=dict(color=t["surface"], width=2)),
        text=[fmt.num(value) for value in values], textposition="outside",
        textfont=dict(size=12, color=t["ink"]),
        hovertemplate="%{y}: %{x:,.2f}<extra></extra>",
    ))
    if v.fair_base:
        # The weighted average is the conclusion, not one model among the
        # others: its own colour, on top.
        fig.add_trace(go.Bar(
            x=[v.fair_base], y=[L("Weighted average (conclusion)",
                                  "Media ponderata (conclusione)")], orientation="h",
            width=0.55, name=L("Weighted average", "Media ponderata"),
            marker=dict(color=t["s3"], cornerradius=4, line=dict(color=t["surface"], width=2)),
            text=[fmt.num(v.fair_base)], textposition="outside",
            textfont=dict(size=12, color=t["ink"]),
            hovertemplate="%{y}: %{x:,.2f}<extra></extra>",
        ))
    if v.analyst_target:
        # An outside reference, with its own colour: this one is not our sum.
        fig.add_trace(go.Bar(
            x=[v.analyst_target], y=[L("Average analyst target",
                                       "Obiettivo medio analisti")], orientation="h",
            width=0.55, name=L("Analyst reference", "Riferimento analisti"),
            marker=dict(color=t["s2"], cornerradius=4, line=dict(color=t["surface"], width=2)),
            text=[fmt.num(v.analyst_target)], textposition="outside",
            textfont=dict(size=12, color=t["ink"]),
            hovertemplate="%{y}: %{x:,.2f}<extra></extra>",
        ))
    if m.price:
        # The price line sits behind the bars, otherwise it cuts through the
        # labels; its value is written in the subtitle, where it does not
        # collide with the legend.
        fig.add_shape(type="line", x0=m.price, x1=m.price, y0=0, y1=1, yref="paper",
                      line=dict(color=t["critical"], width=2), layer="below")
    rows = len(labels) + (1 if v.fair_base else 0) + (1 if v.analyst_target else 0)
    upper = max([value for value in values if value]
                + [m.price or 0, v.fair_base or 0, v.analyst_target or 0])
    fig = _layout(fig, t, title=L("What it is worth, according to each method",
                                  "Quanto vale, secondo ogni metodo"),
                  subtitle=L(f"Per-share values in {m.currency}. The vertical red line is the "
                             f"market "
                             f"price ({fmt.num(m.price)}): bars to the right of it mean the stock "
                             "trades at a discount.",
                             f"Valori per azione in {m.currency}. La linea rossa verticale e' il "
                             f"prezzo "
                             f"di mercato ({fmt.num(m.price)}): le barre alla sua destra indicano "
                             f"un "
                             "titolo a sconto."),
                  height=max(320, 76 * rows + 130))
    fig.update_xaxes(range=[0, upper * 1.32], showgrid=True, gridcolor=t["grid"], linewidth=0)
    fig.update_yaxes(showgrid=False, zeroline=False, tickfont=dict(size=12, color=t["ink2"]))
    fig.update_layout(hovermode="closest", showlegend=True, barmode="group",
                      margin=dict(l=280, r=52, t=104, b=52))
    return fig


# --------------------------------------------------------------------------
# 12. dividend history
# --------------------------------------------------------------------------
def dividend_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    by_year = m.dividend.get("by_year")
    if by_year is None or len(by_year) == 0:
        return _empty(L("No dividend recorded for this stock",
                        "Nessun dividendo registrato per questo titolo"), t)
    series = pd.Series(by_year).sort_index()
    fig = go.Figure()
    fig.add_trace(_bar([str(int(y)) for y in series.index], series.values,
                       L("Dividend per share",
                         "Dividendo per azione"), t["s1"], t, unit=f" {m.currency}"))
    return _layout(fig, t, title=L("Dividend per share, year by year",
                                   "Dividendo per azione, anno per anno"),
                   subtitle=L("Sum of every payment in each calendar year. The last year may be "
                              "incomplete.",
                              "Somma degli stacchi di ogni anno solare. L'ultimo anno puo' essere "
                              "incompleto."),
                   height=300, unit=m.currency)


def all_charts(analysis, dark: bool = False) -> dict[str, go.Figure]:
    """Every chart in one go: used by the CLI to export them."""
    m, v, d = analysis.metrics, analysis.valuation, analysis.verdict
    prices, benchmark = analysis.data.prices, analysis.data.benchmark
    return {
        "price": price_chart(m, v, prices, dark),
        "relative": relative_chart(m, prices, benchmark, dark),
        "scores": pillars_chart(d, dark),
        "methods": methods_chart(m, v, dark),
        "revenue": revenue_chart(m, dark),
        "margins": margins_chart(m, dark),
        "returns": returns_chart(m, dark),
        "cash": cashflow_chart(m, dark),
        "eps_dividend": eps_dividend_chart(m, dark),
        "strength": health_chart(m, dark),
        "rsi": rsi_chart(m, prices, dark),
        "multiple_pe": multiple_history_chart(m, "pe", dark),
        "dividend": dividend_chart(m, dark),
    }


# ==========================================================================
# DIVIDEND CHARTS
# ==========================================================================
# The colours of the two diverging series (points for / against) are the
# blue-red pair documented for signed scales, with zero in grey: they are not
# status colours, and must not be confused with the green/amber/red of the
# scores.
DIVERGING_POSITIVE = {"light": "#2a78d6", "dark": "#3987e5"}
DIVERGING_NEGATIVE = {"light": "#e34948", "dark": "#e66767"}


def dividend_history_chart(analisi, dark: bool = False) -> go.Figure:
    """Dividend per share by year, with the cuts marked and the forecast."""
    t = tokens(dark)
    if analisi is None or not analisi.pays_dividends or analisi.years.empty:
        return _empty(L("No dividend recorded for this stock",
                        "Nessun dividendo registrato per questo titolo"), t, height=300)
    tabella = analisi.years
    cur = analisi.currency

    anni = [str(int(a)) for a in tabella.index]
    valori = tabella["dps"].tolist()
    completo = tabella["completo"].tolist()
    variazioni = tabella["variazione"].tolist()

    # A year that was cut or skipped only stands out if it has a colour of its
    # own: a dividend cut is the event that matters most in this series.
    colori, etichette = [], []
    for valore, chiuso, variazione in zip(valori, completo, variazioni):
        # The year in progress has to be judged first: it is incomplete by
        # definition, hence lower than the one before it. Flagging it as a cut
        # would be a false alarm on every stock, every year.
        if not chiuso:
            colori.append(t["muted"]); etichette.append(L("year in progress, incomplete",
                                                          "anno in corso, incompleto"))
        elif valore <= 0:
            colori.append(t["critical"]); etichette.append(L("no dividend", "nessun dividendo"))
        elif variazione is not None and variazione == variazione and variazione < -0.02:
            colori.append(t["critical"]); etichette.append(L("cut", "taglio"))
        else:
            colori.append(t["s1"]); etichette.append(L("paid", "pagato"))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=anni, y=valori, name=L("Dividend paid", "Dividendo pagato"),
        marker=dict(color=colori, cornerradius=4, line=dict(color=t["surface"], width=2)),
        customdata=etichette,
        hovertemplate="%{x}: %{y:,.2f} " + cur + " (%{customdata})<extra></extra>",
    ))

    previsione = analisi.forecast
    if previsione is not None and previsione.ok:
        ultimo = int(tabella.index[-1])
        anni_futuri = [str(ultimo + 1), str(ultimo + 2)]
        base = [previsione.year1_base, previsione.year2_base]
        basso = [previsione.year1_low, previsione.year2_low]
        alto = [previsione.year1_high, previsione.year2_high]
        fig.add_trace(go.Bar(
            x=anni_futuri, y=base, name=L("Forecast", "Previsione"),
            marker=dict(color=t["s3"], cornerradius=4, line=dict(color=t["surface"], width=2)),
            error_y=dict(type="data", symmetric=False,
                         array=[a - b for a, b in zip(alto, base)],
                         arrayminus=[b - l for b, l in zip(base, basso)],
                         color=t["ink2"], thickness=1.5, width=6),
            hovertemplate="%{x}: %{y:,.2f} " + cur + L(" forecast<extra></extra>",
                                                       " previsto<extra></extra>"),
        ))

    tagli = analisi.streaks.get("tagli") or 0
    sottotitolo = (L("Red bars: years with a cut or with no dividend at all. "
                     f"{'No cuts' if not tagli else str(tagli) + (' cut' if tagli == 1 else ' cuts')} "
                     "over the period. The green bars are the estimate for the next two years, "
                     "with their range.",
                     f"Barre rosse: anni di taglio o senza dividendo. "
                     f"{'Nessun taglio' if not tagli else str(tagli) + ' taglio/i'} nel periodo. "
                     "La barra verde e' la stima dei prossimi due anni, con la sua forchetta."))
    return _layout(fig, t, title=L("Dividend per share, year by year",
                                   "Dividendo per azione, anno per anno"),
                   subtitle=sottotitolo, height=380, unit=cur)


def yield_history_chart(analisi, dark: bool = False) -> go.Figure:
    """Yield over time: is today's price generous or expensive?"""
    t = tokens(dark)
    if analisi is None or analisi.daily_yield is None or analisi.daily_yield.empty:
        # Fallback: the annual averages, coarser but better than nothing.
        if analisi is not None and not analisi.years.empty and analisi.years["rendimento"].notna().any():
            serie = analisi.years[analisi.years["completo"]]["rendimento"].dropna()
            if len(serie) >= 3:
                fig = go.Figure()
                fig.add_trace(_bar([str(int(a)) for a in serie.index], serie.values,
                                   L("Average yield for the year",
                                     "Rendimento medio dell'anno"), t["s1"], t, hover_pct=True))
                return _layout(fig, t, title=L("Dividend yield, year by year",
                                               "Rendimento da dividendo, anno per anno"),
                               subtitle=L("The year's dividend over the average price of that same "
                                          "year (no daily history available for a finer series)",
                                          "Dividendo dell'anno sul prezzo medio dello stesso anno "
                                          "(manca lo storico giornaliero per una serie piu' fine)"),
                               height=320, percent_axis=True)
        return _empty(L("Yield history not available",
                        "Storico del rendimento non disponibile"), t, height=300)

    serie = analisi.daily_yield
    stat = analisi.yield_stats
    fig = go.Figure()
    if stat.get("p25") and stat.get("p75"):
        fig.add_hrect(y0=stat["p25"], y1=stat["p75"], fillcolor=t["band"], line_width=0,
                      layer="below")
    fig.add_trace(go.Scatter(
        x=serie.index, y=serie.values, name=L("Yield", "Rendimento"), mode="lines",
        line=dict(color=t["s1"], width=2),
        hovertemplate="%{x|%m/%Y}: %{y:.2%}<extra></extra>",
    ))
    if stat.get("mediana"):
        fig.add_hline(y=stat["mediana"], line=dict(color=t["ink2"], width=1.5),
                      annotation_text=L(f"median {fmt.pct(stat['mediana'])}",
                                        f"mediana {fmt.pct(stat['mediana'])}"),
                      annotation_position="top right",
                      annotation_font=dict(size=11, color=t["ink2"]))
    attuale = stat.get("attuale")
    if attuale:
        colore = t["good"] if attuale > (stat.get("mediana") or 0) else t["critical"]
        fig.add_hline(y=attuale, line=dict(color=colore, width=2),
                      annotation_text=L(f"today {fmt.pct(attuale)}", f"oggi {fmt.pct(attuale)}"),
                      annotation_position="bottom right",
                      annotation_font=dict(size=11, color=colore))
    percentile = stat.get("percentile")
    coda = ("" if percentile is None else
            L(f" Today it is more generous than {fmt.pct(percentile)} of the observations.",
              f" Oggi e' piu' generoso del {fmt.pct(percentile)} delle osservazioni."))
    cadenza = analisi.cadence or 1
    return _layout(fig, t, title=L("Dividend yield over time",
                                   "Rendimento da dividendo nel tempo"),
                   subtitle=L(f"Annualised dividend (the last {cadenza} payments as of each date) "
                              "divided by the price on that day. Grey zone: the central half of "
                              f"the historical values.{coda}",
                              f"Dividendo su base annua (gli ultimi {cadenza} stacchi a ogni data) "
                              "diviso il prezzo di quel giorno. Zona grigia: meta' centrale dei "
                              f"valori storici.{coda}"),
                   height=340, percent_axis=True)


def payout_coverage_chart(analisi, dark: bool = False) -> go.Figure:
    """Is the dividend covered by earnings and by cash?"""
    t = tokens(dark)
    if analisi is None or analisi.years.empty:
        return _empty(L("Coverage data not available",
                        "Dati di copertura non disponibili"), t, height=300)
    completi = analisi.complete_years()
    if completi.empty:
        return _empty(L("No complete year available",
                        "Nessun anno completo disponibile"), t, height=300)
    anni = [str(int(a)) for a in completi.index]

    pannelli = []
    if completi["payout"].notna().any():
        pannelli.append(("payout", L("Share of earnings paid out",
                                     "Quota di utili distribuita"), True, 1.0))
    if completi["copertura_cassa"].notna().any():
        pannelli.append(("copertura_cassa", L("Cover from free cash flow",
                                              "Copertura con la cassa libera"), False, 1.0))
    if not pannelli:
        return _empty(L("Coverage cannot be computed: earnings or cash flows are missing",
                        "Copertura non calcolabile: mancano utili o flussi di cassa"), t, height=300)

    # Two quantities, two units (percentage and times): two panels.
    fig = make_subplots(rows=1, cols=len(pannelli),
                        subplot_titles=[p[1] for p in pannelli], horizontal_spacing=0.10)
    for i, (colonna, nome, percentuale, soglia) in enumerate(pannelli, start=1):
        serie = completi[colonna]
        # Above the threshold the dividend is not covered: the colour says so,
        # and not a dashed line, because dashed lines are reserved.
        colori = [t["critical"] if (v is not None and v == v and
                                    ((percentuale and v > 1.0) or (not percentuale and v < 1.0)))
                  else t["s1"] for v in serie]
        fig.add_trace(go.Bar(
            x=anni, y=serie, width=0.55, showlegend=False, name=nome,
            marker=dict(color=colori, cornerradius=4, line=dict(color=t["surface"], width=2)),
            hovertemplate=("%{y:.0%}" if percentuale else "%{y:,.2f}x") + "<extra></extra>",
        ), row=1, col=i)
        fig.add_hline(y=soglia, line=dict(color=t["axis"], width=1.5), row=1, col=i)
        fig.update_yaxes(tickformat=".0%" if percentuale else ".1f", row=1, col=i)

    fig = _layout(fig, t, title=L("Is the dividend covered?", "Il dividendo e' coperto?"),
                  subtitle=L("The line marks the breaking point: above 100% of earnings, or below "
                             "1 times free cash flow, the dividend is not funded by the business. "
                             "The red bars are the years when that happened.",
                             "La linea segna il punto di rottura: sopra il 100% degli utili, o "
                             "sotto "
                             "1 volta la cassa libera, il dividendo non e' finanziato "
                             "dall'attivita'. "
                             "Le barre rosse sono gli anni in cui e' accaduto."),
                  height=350)
    for annotazione in fig.layout.annotations:
        annotazione.font = dict(size=12, color=t["ink2"], family=FONT)
        if annotazione.yref == "paper" and annotazione.y and annotazione.y > 0.9:
            annotazione.y = 0.93
    fig.update_layout(showlegend=False, margin=dict(l=56, r=24, t=124, b=48))
    return fig


def total_return_chart(analisi, prices, dark: bool = False) -> go.Figure:
    """How much of the return came from the coupons and how much from the price."""
    t = tokens(dark)
    if analisi is None or prices is None or prices.empty or not analisi.pays_dividends:
        return _empty(L("Price history too short for the breakdown",
                        "Storico prezzi insufficiente per la scomposizione"), t, height=300)
    chiusure = prices["Close"].dropna()
    tr = analisi.total_return
    anni = tr.get("anni") or 10
    inizio = chiusure.index[-1] - pd.Timedelta(days=int(365.25 * anni))
    finestra = chiusure[chiusure.index >= inizio]
    if len(finestra) < 100:
        return _empty(L("Price history too short for the breakdown",
                        "Storico prezzi insufficiente per la scomposizione"), t, height=300)

    solo_prezzo = finestra / finestra.iloc[0] * 100
    # Day by day we rebuild the value with the coupons reinvested.
    pagamenti = analisi.payments
    quote = pd.Series(1.0, index=finestra.index)
    fattore = 1.0
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

    fig = go.Figure()
    fig.add_trace(_line(finestra.index, solo_prezzo.values, L("Price only",
                                                              "Solo prezzo"), t["s2"], t, width=1.5))
    fig.add_trace(_line(finestra.index, totale.values, L("With dividends reinvested",
                                                         "Con dividendi reinvestiti"), t["s1"], t))
    for valori, colore, etichetta in ((totale, t["s1"], L("with dividends", "con dividendi")),
                                      (solo_prezzo, t["s2"], L("price only", "solo prezzo"))):
        fig.add_annotation(x=finestra.index[-1], y=float(valori.iloc[-1]), text=f" {etichetta}",
                           showarrow=False, xanchor="left", font=dict(size=11, color=colore))

    quota = tr.get("quota_dividendi")
    coda = ""
    if quota is not None and 0 < quota <= 1:
        coda = L(f" Dividends are {fmt.pct(quota)} of the total return over the period.",
                 f" I dividendi sono il {fmt.pct(quota)} del rendimento totale del periodo.")
    elif tr.get("contributo_dividendi") is not None:
        coda = (L(f" Dividends added "
                  f"{fmt.num(tr['contributo_dividendi'] * 100, 1)} percentage points.",
                  f" I dividendi hanno aggiunto "
                  f"{fmt.num(tr['contributo_dividendi'] * 100, 1)} punti percentuali."))
    return _layout(fig, t, title=L("Where the return came from",
                                   "Da dove e' venuto il rendimento"),
                   subtitle=L(f"Both lines start at 100 {anni:.0f} years ago. The gap between them "
                              f"is the effect of the coupons reinvested.{coda}",
                              f"Entrambe le linee partono da 100 a {anni:.0f} anni fa. La distanza "
                              f"fra le due e' l'effetto delle cedole reinvestite.{coda}"),
                   height=360, unit=L("index = 100", "indice = 100"))


def safety_factors_chart(analisi, dark: bool = False) -> go.Figure:
    """The points that make up the safety score, one by one."""
    t = tokens(dark)
    modo = "dark" if dark else "light"
    if analisi is None or analisi.safety is None or not analisi.safety.factors:
        return _empty(L("Safety score cannot be computed",
                        "Punteggio di solidita' non calcolabile"), t, height=300)
    fattori = [f for f in analisi.safety.factors if f.points != 0]
    if not fattori:
        return _empty(L("No factor moved the score",
                        "Nessun fattore ha inciso sul punteggio"), t, height=260)
    fattori = sorted(fattori, key=lambda f: f.points)

    etichette = [f.label for f in fattori]
    punti = [f.points for f in fattori]
    colori = [DIVERGING_POSITIVE[modo] if p > 0 else DIVERGING_NEGATIVE[modo] for p in punti]
    testi = [f"{p:+.0f}" for p in punti]
    spiegazioni = [f.explanation for f in fattori]

    fig = go.Figure(go.Bar(
        x=punti, y=etichette, orientation="h", width=0.6,
        marker=dict(color=colori, cornerradius=4, line=dict(color=t["surface"], width=2)),
        text=testi, textposition="outside", textfont=dict(size=12, color=t["ink"]),
        customdata=spiegazioni,
        hovertemplate=L("%{y}: %{x:+.0f} points<br>%{customdata}<extra></extra>",
                        "%{y}: %{x:+.0f} punti<br>%{customdata}<extra></extra>"),
        showlegend=False,
    ))
    fig.add_vline(x=0, line=dict(color=t["axis"], width=1.5))
    limite = max(abs(min(punti)), abs(max(punti))) * 1.45
    fig = _layout(fig, t, title=L("Where the safety score comes from",
                                  "Da dove viene il punteggio di solidita'"),
                  subtitle=L(f"It starts at 50 and ends at {fmt.num(analisi.safety.score, 0)}. "
                             "Blue to the right: points in favour. Red to the left: points "
                             "against. "
                             "Hover over a bar for the explanation.",
                             f"Si parte da 50 e si arriva a {fmt.num(analisi.safety.score, 0)}. "
                             "Blu a destra: punti a favore. Rosso a sinistra: punti contro. "
                             "Passa sopra una barra per la spiegazione."),
                  height=max(300, 56 * len(fattori) + 130))
    fig.update_xaxes(range=[-limite, limite], showgrid=True, gridcolor=t["grid"], linewidth=0,
                     title=dict(text=L("points", "punti"), font=dict(size=11, color=t["muted"])))
    fig.update_yaxes(showgrid=False, zeroline=False, tickfont=dict(size=12, color=t["ink2"]))
    fig.update_layout(showlegend=False, hovermode="closest",
                      margin=dict(l=300, r=60, t=104, b=52))
    return fig


def backtest_chart(analisi, dark: bool = False) -> go.Figure:
    """Has the yield signal worked on this stock?"""
    t = tokens(dark)
    verifica = analisi.backtest if analisi else None
    if verifica is None or not verifica.buckets:
        messaggio = (verifica.note if verifica and verifica.note
                     else L("Backtest not available", "Verifica retrospettiva non disponibile"))
        return _empty(messaggio, t, height=280)
    gruppi = [b for b in verifica.buckets if b.observations]
    if not gruppi:
        return _empty(verifica.note or L("No usable observation",
                                         "Nessuna osservazione utilizzabile"), t, height=280)

    # The bucket labels carry their signal in brackets ("High yield (buy
    # signal)"): we break the line there so the tick does not run wide.
    etichette = [b.label.replace(L(" (", " (segnale di "), "<br>(") for b in gruppi]
    valori = [b.avg_return_2y for b in gruppi]
    conteggi = [b.observations for b in gruppi]
    modo = "dark" if dark else "light"
    colori = [DIVERGING_POSITIVE[modo] if (v or 0) >= 0 else DIVERGING_NEGATIVE[modo]
              for v in valori]
    fig = go.Figure(go.Bar(
        x=etichette, y=valori, width=0.5,
        marker=dict(color=colori, cornerradius=4, line=dict(color=t["surface"], width=2)),
        text=[f"{v:+.0%}" if v is not None else fmt.na() for v in valori],
        textposition="outside", textfont=dict(size=13, color=t["ink"]),
        customdata=conteggi,
        hovertemplate=L("%{x}<br>2-year average: %{y:+.1%}<br>%{customdata} "
                        "observations<extra></extra>",
                        "%{x}<br>media 2 anni: %{y:+.1%}<br>%{customdata} "
                        "osservazioni<extra></extra>"),
        showlegend=False,
    ))
    fig.add_hline(y=0, line=dict(color=t["axis"], width=1.5))
    fig = _layout(fig, t, title=L("Has the signal worked on this stock?",
                                  "Il segnale ha funzionato su questo titolo?"),
                  subtitle=L("Average total return over the following two years, depending on "
                             "where "
                             "the dividend yield stood against its own history. "
                             f"{verifica.observations} monthly observations with overlapping "
                             "windows: a hint, not a proof.",
                             "Rendimento totale medio dei due anni successivi, a seconda di dove "
                             "stava il rendimento da dividendo rispetto alla propria storia. "
                             f"{verifica.observations} osservazioni mensili con finestre "
                             f"sovrapposte: "
                             "un indizio, non una dimostrazione."),
                  height=360, percent_axis=True)
    fig.update_layout(showlegend=False, hovermode="closest")
    return fig


def dividend_charts(analysis, dark: bool = False) -> dict[str, go.Figure]:
    """The six charts on the dividend tab."""
    d = analysis.dividends
    return {
        "dividend_history": dividend_history_chart(d, dark),
        "dividend_yield": yield_history_chart(d, dark),
        "dividend_coverage": payout_coverage_chart(d, dark),
        "dividend_total_return": total_return_chart(d, analysis.data.prices, dark),
        "dividend_safety": safety_factors_chart(d, dark),
        "dividend_backtest": backtest_chart(d, dark),
    }
