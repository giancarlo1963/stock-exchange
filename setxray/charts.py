"""I grafici: pochi, grandi, e ognuno risponde a una domanda sola.

Regole seguite, perche' non sono ovvie:
- mai due assi verticali nello stesso grafico. Due grandezze con unita'
  diverse (baht e percentuali) diventano due grafici, o due riquadri affiancati:
  sovrapporle inventerebbe una correlazione che nei dati non c'e';
- una serie, un colore, sempre lo stesso: il colore identifica la grandezza,
  non la sua posizione in classifica;
- griglie e assi sottili e continui, marcatori sottili, etichette solo dove
  servono. Il grafico deve farsi leggere, non farsi notare;
- i punteggi usano i colori di stato (verde/giallo/rosso) accompagnati sempre
  dal numero, perche' il colore da solo non basta a chi non lo distingue.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from setxray import fmt
from setxray.metrics import Metrics
from setxray.scoring import Verdict
from setxray.valuation import Valuation

# --- token cromatici (palette validata per daltonismo, chiaro e scuro) -----
LIGHT = {
    "surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
    "grid": "#e1e0d9", "axis": "#c3c2b7", "band": "rgba(11,11,11,0.06)",
    "s1": "#2a78d6", "s2": "#eb6834", "s3": "#1baf7a", "s4": "#eda100",
    "good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b",
}
DARK = {
    "surface": "#1a1a19", "ink": "#ffffff", "ink2": "#c3c2b7", "muted": "#898781",
    "grid": "#2c2c2a", "axis": "#383835", "band": "rgba(255,255,255,0.08)",
    "s1": "#3987e5", "s2": "#d95926", "s3": "#199e70", "s4": "#c98500",
    "good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b",
}
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def tokens(dark: bool = False) -> dict:
    return DARK if dark else LIGHT


def _layout(fig: go.Figure, t: dict, *, title: str, subtitle: str = "",
            height: int = 380, percent_axis: bool = False, unit: str = "") -> go.Figure:
    """Cornice comune: titolo, sottotitolo, griglia leggera, legenda in alto."""
    heading = f"<b>{title}</b>"
    if subtitle:
        heading += f"<br><span style='font-size:12px;color:{t['ink2']}'>{subtitle}</span>"
    fig.update_layout(
        title=dict(text=heading, x=0, xanchor="left", font=dict(size=16, color=t["ink"])),
        paper_bgcolor=t["surface"], plot_bgcolor=t["surface"],
        font=dict(family=FONT, size=12, color=t["ink2"]),
        height=height, margin=dict(l=56, r=24, t=84 if subtitle else 64, b=48),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
        hovermode="x unified",
        hoverlabel=dict(bgcolor=t["surface"], font=dict(family=FONT, size=12, color=t["ink"]),
                        bordercolor=t["axis"]),
        bargap=0.45, bargroupgap=0.12,  # barre sottili: meno blocchi, piu' respiro
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
    """Segnaposto esplicito: meglio dire che il dato manca che mostrare un grafico vuoto."""
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
    """Una serie a linea. `end_label` scrive il valore accanto all'ultimo punto.

    L'etichetta viaggia dentro la traccia e non come annotazione: su un asse di
    categorie (gli esercizi) un'annotazione con x testuale non si posiziona.
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
# 1. prezzo, medie mobili e forchetta di valore
# --------------------------------------------------------------------------
def price_chart(m: Metrics, v: Valuation, prices: Optional[pd.DataFrame], dark: bool = False) -> go.Figure:
    t = tokens(dark)
    if prices is None or prices.empty:
        return _empty("Storico prezzi non disponibile", t)
    close = prices["Close"].dropna()
    fig = go.Figure()

    # La forchetta di valore come fascia orizzontale: si vede subito se il
    # prezzo sta dentro, sotto o sopra il valore stimato.
    if v.fair_bear and v.fair_bull:
        fig.add_hrect(y0=v.fair_bear, y1=v.fair_bull, fillcolor=t["band"], line_width=0, layer="below")
    fig.add_trace(_line(close.index, close.values, "Prezzo", t["s1"], t, width=2))
    if len(close) >= 200:
        fig.add_trace(_line(close.index, close.rolling(200).mean(), "Media 200 giorni", t["s3"], t, width=1.5))
    if len(close) >= 50:
        fig.add_trace(_line(close.index, close.rolling(50).mean(), "Media 50 giorni", t["s2"], t, width=1.5))
    if v.fair_base:
        fig.add_hline(y=v.fair_base, line=dict(color=t["ink2"], width=1.5),
                      annotation_text=f"valore stimato {fmt.num(v.fair_base)}",
                      annotation_position="top right",
                      annotation_font=dict(size=11, color=t["ink2"]))
    if m.price:
        fig.add_trace(go.Scatter(
            x=[close.index[-1]], y=[m.price], mode="markers+text", name="oggi",
            marker=dict(color=t["s1"], size=9, line=dict(color=t["surface"], width=2)),
            text=[f" {fmt.num(m.price)}"], textposition="middle right",
            textfont=dict(size=12, color=t["ink"]), showlegend=False,
            hovertemplate="oggi: %{y:,.2f}<extra></extra>",
        ))
    return _layout(fig, t, title="Prezzo e valore stimato",
                   subtitle=f"Chiusure in {m.currency}. La fascia grigia e' la forchetta di valore "
                            "stimata dai modelli, dallo scenario pessimistico a quello ottimistico.",
                   height=420, unit=m.currency)


# --------------------------------------------------------------------------
# 2. confronto con l'indice SET
# --------------------------------------------------------------------------
def relative_chart(m: Metrics, prices: Optional[pd.DataFrame],
                   benchmark: Optional[pd.DataFrame], dark: bool = False) -> go.Figure:
    t = tokens(dark)
    if prices is None or prices.empty:
        return _empty("Storico prezzi non disponibile", t)
    if benchmark is None or benchmark.empty:
        return _empty("Indice SET non disponibile per il confronto", t)
    stock = prices["AdjClose"].dropna()
    index = benchmark["AdjClose"].dropna()
    joined = pd.concat([stock.rename("t"), index.rename("i")], axis=1).dropna()
    if joined.empty:
        return _empty("Nessun periodo in comune fra titolo e indice", t)
    # Entrambe le serie ribasate a 100: unico modo corretto di confrontare due
    # grandezze di scala diversa senza un secondo asse.
    joined = joined / joined.iloc[0] * 100
    fig = go.Figure()
    fig.add_trace(_line(joined.index, joined["t"], m.symbol, t["s1"], t))
    fig.add_trace(_line(joined.index, joined["i"], "Indice SET", t["s2"], t, width=1.5))
    for column, color, label in (("t", t["s1"], m.symbol), ("i", t["s2"], "SET")):
        fig.add_annotation(x=joined.index[-1], y=joined[column].iloc[-1], text=f" {label}",
                           showarrow=False, xanchor="left", font=dict(size=11, color=color))
    return _layout(fig, t, title="Titolo contro indice SET",
                   subtitle="Rendimento totale, entrambi ribasati a 100 alla data iniziale",
                   height=340, unit="indice = 100")


# --------------------------------------------------------------------------
# 3. ricavi e utile netto
# --------------------------------------------------------------------------
def revenue_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty or "revenue" not in years:
        return _empty("Conto economico non disponibile", t)
    labels = m.year_labels()
    scale, unit = (1e9, f"mld {m.currency}") if years["revenue"].max() >= 1e9 else (1e6, f"mln {m.currency}")
    fig = go.Figure()
    fig.add_trace(_bar(labels, years["revenue"] / scale, "Ricavi", t["s1"], t, unit=f" {unit}"))
    if "net_income" in years:
        fig.add_trace(_bar(labels, years["net_income"] / scale, "Utile netto", t["s2"], t, unit=f" {unit}"))
    return _layout(fig, t, title="Ricavi e utile netto per esercizio",
                   subtitle="Quanto fattura e quanto ne resta, anno per anno", height=340, unit=unit)


# --------------------------------------------------------------------------
# 4. margini
# --------------------------------------------------------------------------
def margins_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty:
        return _empty("Margini non calcolabili senza conto economico", t)
    labels = m.year_labels()
    fig = go.Figure()
    for column, name, color in (("gross_margin", "Margine lordo", t["s1"]),
                                ("operating_margin", "Margine operativo", t["s2"]),
                                ("net_margin", "Margine netto", t["s3"])):
        if column in years and years[column].notna().any():
            series = years[column]
            last = series.dropna()
            # Valore scritto accanto all'ultimo punto: identifica la serie anche
            # a chi non distingue i colori.
            label = fmt.pct(last.iloc[-1]) if not last.empty else None
            fig.add_trace(_line(labels, series.values, name, color, t, pct=True, end_label=label))
    if not fig.data:
        return _empty("Margini non disponibili", t)
    fig = _layout(fig, t, title="Margini",
                  subtitle="Quanta parte dei ricavi resta a ogni livello del conto economico",
                  height=320, percent_axis=True)
    # Spazio a destra per le etichette scritte accanto all'ultimo punto.
    fig.update_xaxes(range=[-0.4, len(labels) - 0.25])
    return fig


# --------------------------------------------------------------------------
# 5. redditivita' del capitale
# --------------------------------------------------------------------------
def returns_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty:
        return _empty("Redditivita' non calcolabile senza bilanci", t)
    labels = m.year_labels()
    fig = go.Figure()
    for column, name, color in (("roe", "ROE (sul patrimonio)", t["s1"]),
                                ("roic", "ROIC (sul capitale investito)", t["s2"]),
                                ("roa", "ROA (sull'attivo)", t["s3"])):
        if column in years and years[column].notna().any():
            fig.add_trace(_bar(labels, years[column], name, color, t, hover_pct=True))
    if not fig.data:
        return _empty("Indici di redditivita' non disponibili", t)
    return _layout(fig, t, title="Redditivita' del capitale",
                   subtitle="Quanto rende il capitale impiegato: sopra il 10-12% l'azienda crea valore reinvestendo",
                   height=320, percent_axis=True)


# --------------------------------------------------------------------------
# 6. flussi di cassa
# --------------------------------------------------------------------------
def cashflow_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty or "cfo" not in years:
        return _empty("Rendiconto finanziario non disponibile", t)
    labels = m.year_labels()
    scale, unit = (1e9, f"mld {m.currency}") if years["cfo"].abs().max() >= 1e9 else (1e6, f"mln {m.currency}")
    fig = go.Figure()
    fig.add_trace(_bar(labels, years["cfo"] / scale, "Cassa dall'attivita'", t["s1"], t, unit=f" {unit}"))
    if "capex" in years:
        fig.add_trace(_bar(labels, years["capex"] / scale, "Investimenti", t["s2"], t, unit=f" {unit}"))
    if "fcf" in years:
        # Terza barra, non una linea: e' la stessa unita' delle altre due e una
        # linea sovrapposta alle barre si legge male.
        fig.add_trace(_bar(labels, years["fcf"] / scale, "Cassa libera", t["s3"], t, unit=f" {unit}"))
    return _layout(fig, t, title="Da dove viene e dove va la cassa",
                   subtitle="Cassa generata dall'attivita', investimenti (negativi) e cassa libera che resta",
                   height=340, unit=unit)


# --------------------------------------------------------------------------
# 7. utile e dividendo per azione
# --------------------------------------------------------------------------
def eps_dividend_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty or "eps" not in years:
        return _empty("Utile per azione non disponibile", t)
    labels = m.year_labels()
    fig = go.Figure()
    fig.add_trace(_bar(labels, years["eps"], "Utile per azione", t["s1"], t, unit=f" {m.currency}"))
    if "dps" in years and years["dps"].notna().any():
        fig.add_trace(_bar(labels, years["dps"], "Dividendo per azione", t["s2"], t, unit=f" {m.currency}"))
    return _layout(fig, t, title="Utile e dividendo per azione",
                   subtitle="La differenza fra le due barre e' l'utile reinvestito nell'azienda",
                   height=320, unit=m.currency)


# --------------------------------------------------------------------------
# 8. solidita' finanziaria (riquadri affiancati, scale diverse)
# --------------------------------------------------------------------------
def health_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty:
        return _empty("Dati di bilancio non disponibili", t)
    labels = m.year_labels()
    panels = [
        ("net_debt_ebitda", "Debito netto / EBITDA", "volte", False),
        ("interest_coverage", "Copertura interessi", "volte", False),
        ("debt_equity", "Debito / patrimonio", "volte", False),
        ("payout", "Utili distribuiti", "%", True),
    ]
    available = [p for p in panels if p[0] in years and years[p[0]].notna().any()]
    if not available:
        return _empty("Indicatori di solidita' non calcolabili", t)
    # Quattro grandezze, quattro riquadri: unita' e scale diverse non possono
    # convivere sullo stesso asse.
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
    fig = _layout(fig, t, title="Solidita' finanziaria nel tempo",
                  subtitle="Quattro misure con unita' diverse, quindi quattro riquadri separati",
                  height=360)
    for annotation in fig.layout.annotations:
        annotation.font = dict(size=12, color=t["ink2"], family=FONT)
        # I titoli dei riquadri nascono attaccati a quello del grafico: li
        # spostiamo sotto e allarghiamo il margine per farceli stare.
        if annotation.yref == "paper" and annotation.y and annotation.y > 0.9:
            annotation.y = 0.93
    fig.update_layout(showlegend=False, margin=dict(l=56, r=24, t=120, b=48))
    return fig


# --------------------------------------------------------------------------
# 9. storia del multiplo
# --------------------------------------------------------------------------
def multiple_history_chart(m: Metrics, key: str = "pe", dark: bool = False) -> go.Figure:
    t = tokens(dark)
    names = {"pe": "P/E (prezzo / utili)", "pb": "P/B (prezzo / patrimonio)",
             "ps": "P/S (prezzo / ricavi)", "ev_ebitda": "EV/EBITDA"}
    hist = m.multiple_history.get(key)
    if not hist:
        return _empty(f"Storico del {names.get(key, key)} non disponibile", t)
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
                  annotation_text=f"mediana {fmt.mult(hist['median'])}", annotation_position="top right",
                  annotation_font=dict(size=11, color=t["ink2"]))
    current = m.valuation.get(key)
    if current:
        colour = t["good"] if current < hist["median"] else t["critical"]
        fig.add_hline(y=current, line=dict(color=colour, width=2),
                      annotation_text=f"oggi {fmt.mult(current)}", annotation_position="bottom right",
                      annotation_font=dict(size=11, color=colour))
    percentile = hist.get("percentile")
    # "nel 0% piu' basso" non si capisce: meglio dire quante osservazioni batte.
    where = ("" if percentile is None
             else f" Oggi e' piu' economico del {1 - percentile:.0%} delle osservazioni storiche.")
    return _layout(fig, t, title=f"{names.get(key, key)}: quanto costa rispetto al suo passato",
                   subtitle=f"Zona grigia: meta' centrale dei valori storici.{where}",
                   height=330, unit="volte")


# --------------------------------------------------------------------------
# 10. punteggio per area
# --------------------------------------------------------------------------
def pillars_chart(verdict: Verdict, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    pillars = [p for p in verdict.pillars if p.score is not None]
    if not pillars:
        return _empty("Punteggi non calcolabili", t)
    pillars = sorted(pillars, key=lambda p: p.score)
    labels = [p.label for p in pillars]
    scores = [p.score for p in pillars]
    # Colori di stato, non colori di serie: qui il colore significa
    # "promosso / da tenere d'occhio / bocciato". Il numero e' sempre scritto.
    colors = [t["good"] if s >= 65 else t["warning"] if s >= 45 else t["critical"] for s in scores]
    # Il colore da solo non basta a chi non lo distingue: accanto al numero
    # mettiamo sempre la parola.
    words = ["buono" if s >= 65 else "medio" if s >= 45 else "debole" for s in scores]
    fig = go.Figure(go.Bar(
        x=scores, y=labels, orientation="h", width=0.5,
        marker=dict(color=colors, cornerradius=4, line=dict(color=t["surface"], width=2)),
        text=[f"{s:.0f} - {w}" for s, w in zip(scores, words)], textposition="outside",
        textfont=dict(size=12, color=t["ink"]),
        hovertemplate="%{y}: %{x:.0f}/100<extra></extra>", showlegend=False,
    ))
    fig.add_vline(x=50, line=dict(color=t["axis"], width=1))
    fig = _layout(fig, t, title="Punteggio per area",
                  subtitle="0-100. Verde sopra 65, giallo fra 45 e 65, rosso sotto 45. La linea segna la meta'.",
                  height=300)
    # L'asse si ferma a 100, ma la scala lascia spazio all'etichetta di fianco
    # alla barra piu' lunga.
    fig.update_xaxes(range=[0, 132], showgrid=True, gridcolor=t["grid"], linewidth=0,
                     tickvals=[0, 20, 40, 60, 80, 100])
    fig.update_yaxes(showgrid=False, zeroline=False, tickfont=dict(size=12, color=t["ink2"]))
    fig.update_layout(showlegend=False, hovermode="closest",
                      margin=dict(l=220, r=32, t=84, b=40))
    return fig


# --------------------------------------------------------------------------
# 11. i metodi di valutazione a confronto
# --------------------------------------------------------------------------
def methods_chart(m: Metrics, v: Valuation, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    usable = [method for method in v.methods if method.usable]
    if not usable:
        return _empty("Nessun modello di valutazione applicabile", t)
    # Plotly disegna le barre orizzontali dal basso: invertiamo l'ordine per
    # leggerle dall'alto, come sono descritte nel testo.
    labels = [method.label for method in usable][::-1]
    values = [method.fair_value for method in usable][::-1]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=values, y=labels, orientation="h", width=0.55, name="Singoli modelli",
        marker=dict(color=t["s1"], cornerradius=4, line=dict(color=t["surface"], width=2)),
        text=[fmt.num(value) for value in values], textposition="outside",
        textfont=dict(size=12, color=t["ink"]),
        hovertemplate="%{y}: %{x:,.2f}<extra></extra>",
    ))
    if v.fair_base:
        # La media ponderata e' la conclusione, non un modello fra gli altri:
        # colore proprio, in cima.
        fig.add_trace(go.Bar(
            x=[v.fair_base], y=["Media ponderata (conclusione)"], orientation="h",
            width=0.55, name="Media ponderata",
            marker=dict(color=t["s3"], cornerradius=4, line=dict(color=t["surface"], width=2)),
            text=[fmt.num(v.fair_base)], textposition="outside",
            textfont=dict(size=12, color=t["ink"]),
            hovertemplate="%{y}: %{x:,.2f}<extra></extra>",
        ))
    if v.analyst_target:
        # Riferimento esterno, con un colore proprio: non e' un nostro calcolo.
        fig.add_trace(go.Bar(
            x=[v.analyst_target], y=["Obiettivo medio analisti"], orientation="h",
            width=0.55, name="Riferimento analisti",
            marker=dict(color=t["s2"], cornerradius=4, line=dict(color=t["surface"], width=2)),
            text=[fmt.num(v.analyst_target)], textposition="outside",
            textfont=dict(size=12, color=t["ink"]),
            hovertemplate="%{y}: %{x:,.2f}<extra></extra>",
        ))
    if m.price:
        # La linea del prezzo sta dietro le barre, altrimenti taglia le
        # etichette; il suo valore e' scritto nel sottotitolo, dove non si
        # sovrappone alla legenda.
        fig.add_shape(type="line", x0=m.price, x1=m.price, y0=0, y1=1, yref="paper",
                      line=dict(color=t["critical"], width=2), layer="below")
    rows = len(labels) + (1 if v.fair_base else 0) + (1 if v.analyst_target else 0)
    upper = max([value for value in values if value]
                + [m.price or 0, v.fair_base or 0, v.analyst_target or 0])
    fig = _layout(fig, t, title="Quanto vale, secondo ogni metodo",
                  subtitle=f"Valori per azione in {m.currency}. La linea rossa verticale e' il prezzo "
                           f"di mercato ({fmt.num(m.price)}): le barre alla sua destra indicano un "
                           "titolo a sconto.",
                  height=max(320, 76 * rows + 130))
    fig.update_xaxes(range=[0, upper * 1.32], showgrid=True, gridcolor=t["grid"], linewidth=0)
    fig.update_yaxes(showgrid=False, zeroline=False, tickfont=dict(size=12, color=t["ink2"]))
    fig.update_layout(hovermode="closest", showlegend=True, barmode="group",
                      margin=dict(l=280, r=52, t=104, b=52))
    return fig


# --------------------------------------------------------------------------
# 12. dividendo storico
# --------------------------------------------------------------------------
def dividend_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    by_year = m.dividend.get("by_year")
    if by_year is None or len(by_year) == 0:
        return _empty("Nessun dividendo registrato per questo titolo", t)
    series = pd.Series(by_year).sort_index()
    fig = go.Figure()
    fig.add_trace(_bar([str(int(y)) for y in series.index], series.values,
                       "Dividendo per azione", t["s1"], t, unit=f" {m.currency}"))
    return _layout(fig, t, title="Dividendo per azione, anno per anno",
                   subtitle="Somma degli stacchi di ogni anno solare. L'ultimo anno puo' essere incompleto.",
                   height=300, unit=m.currency)


def all_charts(analysis, dark: bool = False) -> dict[str, go.Figure]:
    """Tutti i grafici in un colpo: usato dalla CLI per l'esportazione."""
    m, v, d = analysis.metrics, analysis.valuation, analysis.verdict
    prices, benchmark = analysis.data.prices, analysis.data.benchmark
    return {
        "prezzo": price_chart(m, v, prices, dark),
        "relativo": relative_chart(m, prices, benchmark, dark),
        "punteggi": pillars_chart(d, dark),
        "metodi": methods_chart(m, v, dark),
        "ricavi": revenue_chart(m, dark),
        "margini": margins_chart(m, dark),
        "redditivita": returns_chart(m, dark),
        "cassa": cashflow_chart(m, dark),
        "utile_dividendo": eps_dividend_chart(m, dark),
        "solidita": health_chart(m, dark),
        "multiplo_pe": multiple_history_chart(m, "pe", dark),
        "dividendo": dividend_chart(m, dark),
    }


# ==========================================================================
# GRAFICI SUI DIVIDENDI
# ==========================================================================
# I colori delle due serie divergenti (punti a favore / contro) sono la coppia
# blu-rosso documentata per le scale con un segno, con lo zero in grigio: non
# sono colori di stato, e non vanno confusi con verde/giallo/rosso dei
# punteggi.
DIVERGENTE_POSITIVO = {"light": "#2a78d6", "dark": "#3987e5"}
DIVERGENTE_NEGATIVO = {"light": "#e34948", "dark": "#e66767"}


def dividend_history_chart(analisi, dark: bool = False) -> go.Figure:
    """Dividendo per azione per anno, con i tagli segnati e la previsione."""
    t = tokens(dark)
    if analisi is None or not analisi.pays_dividends or analisi.years.empty:
        return _empty("Nessun dividendo registrato per questo titolo", t, height=300)
    tabella = analisi.years
    cur = analisi.currency

    anni = [str(int(a)) for a in tabella.index]
    valori = tabella["dps"].tolist()
    completo = tabella["completo"].tolist()
    variazioni = tabella["variazione"].tolist()

    # Un anno tagliato o saltato si vede subito solo se ha un colore suo: il
    # taglio del dividendo e' l'evento che conta piu' di tutti in questa serie.
    colori, etichette = [], []
    for valore, chiuso, variazione in zip(valori, completo, variazioni):
        # L'anno in corso va valutato prima di tutto: e' incompleto per
        # definizione, quindi piu' basso del precedente. Segnalarlo come taglio
        # sarebbe un falso allarme su ogni titolo, ogni anno.
        if not chiuso:
            colori.append(t["muted"]); etichette.append("anno in corso, incompleto")
        elif valore <= 0:
            colori.append(t["critical"]); etichette.append("nessun dividendo")
        elif variazione is not None and variazione == variazione and variazione < -0.02:
            colori.append(t["critical"]); etichette.append("taglio")
        else:
            colori.append(t["s1"]); etichette.append("pagato")

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=anni, y=valori, name="Dividendo pagato",
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
            x=anni_futuri, y=base, name="Previsione",
            marker=dict(color=t["s3"], cornerradius=4, line=dict(color=t["surface"], width=2)),
            error_y=dict(type="data", symmetric=False,
                         array=[a - b for a, b in zip(alto, base)],
                         arrayminus=[b - l for b, l in zip(base, basso)],
                         color=t["ink2"], thickness=1.5, width=6),
            hovertemplate="%{x}: %{y:,.2f} " + cur + " previsto<extra></extra>",
        ))

    tagli = analisi.streaks.get("tagli") or 0
    sottotitolo = (f"Barre rosse: anni di taglio o senza dividendo. "
                   f"{'Nessun taglio' if not tagli else str(tagli) + ' taglio/i'} nel periodo. "
                   "La barra verde e' la stima dei prossimi due anni, con la sua forchetta.")
    return _layout(fig, t, title="Dividendo per azione, anno per anno",
                   subtitle=sottotitolo, height=380, unit=cur)


def yield_history_chart(analisi, dark: bool = False) -> go.Figure:
    """Rendimento nel tempo: il prezzo di oggi e' generoso o caro?"""
    t = tokens(dark)
    if analisi is None or analisi.daily_yield is None or analisi.daily_yield.empty:
        # Riserva: le medie annuali, piu' grossolane ma meglio di niente.
        if analisi is not None and not analisi.years.empty and analisi.years["rendimento"].notna().any():
            serie = analisi.years[analisi.years["completo"]]["rendimento"].dropna()
            if len(serie) >= 3:
                fig = go.Figure()
                fig.add_trace(_bar([str(int(a)) for a in serie.index], serie.values,
                                   "Rendimento medio dell'anno", t["s1"], t, hover_pct=True))
                return _layout(fig, t, title="Rendimento da dividendo, anno per anno",
                               subtitle="Dividendo dell'anno sul prezzo medio dello stesso anno "
                                        "(manca lo storico giornaliero per una serie piu' fine)",
                               height=320, percent_axis=True)
        return _empty("Storico del rendimento non disponibile", t, height=300)

    serie = analisi.daily_yield
    stat = analisi.yield_stats
    fig = go.Figure()
    if stat.get("p25") and stat.get("p75"):
        fig.add_hrect(y0=stat["p25"], y1=stat["p75"], fillcolor=t["band"], line_width=0,
                      layer="below")
    fig.add_trace(go.Scatter(
        x=serie.index, y=serie.values, name="Rendimento", mode="lines",
        line=dict(color=t["s1"], width=2),
        hovertemplate="%{x|%m/%Y}: %{y:.2%}<extra></extra>",
    ))
    if stat.get("mediana"):
        fig.add_hline(y=stat["mediana"], line=dict(color=t["ink2"], width=1.5),
                      annotation_text=f"mediana {fmt.pct(stat['mediana'])}",
                      annotation_position="top right",
                      annotation_font=dict(size=11, color=t["ink2"]))
    attuale = stat.get("attuale")
    if attuale:
        colore = t["good"] if attuale > (stat.get("mediana") or 0) else t["critical"]
        fig.add_hline(y=attuale, line=dict(color=colore, width=2),
                      annotation_text=f"oggi {fmt.pct(attuale)}",
                      annotation_position="bottom right",
                      annotation_font=dict(size=11, color=colore))
    percentile = stat.get("percentile")
    coda = ("" if percentile is None else
            f" Oggi e' piu' generoso del {fmt.pct(percentile)} delle osservazioni.")
    cadenza = analisi.cadence or 1
    return _layout(fig, t, title="Rendimento da dividendo nel tempo",
                   subtitle=f"Dividendo su base annua (gli ultimi {cadenza} stacchi a ogni data) "
                            "diviso il prezzo di quel giorno. Zona grigia: meta' centrale dei "
                            f"valori storici.{coda}",
                   height=340, percent_axis=True)


def payout_coverage_chart(analisi, dark: bool = False) -> go.Figure:
    """Il dividendo e' coperto dagli utili e dalla cassa?"""
    t = tokens(dark)
    if analisi is None or analisi.years.empty:
        return _empty("Dati di copertura non disponibili", t, height=300)
    completi = analisi.complete_years()
    if completi.empty:
        return _empty("Nessun anno completo disponibile", t, height=300)
    anni = [str(int(a)) for a in completi.index]

    pannelli = []
    if completi["payout"].notna().any():
        pannelli.append(("payout", "Quota di utili distribuita", True, 1.0))
    if completi["copertura_cassa"].notna().any():
        pannelli.append(("copertura_cassa", "Copertura con la cassa libera", False, 1.0))
    if not pannelli:
        return _empty("Copertura non calcolabile: mancano utili o flussi di cassa", t, height=300)

    # Due grandezze, due unita' (percentuale e volte): due riquadri.
    fig = make_subplots(rows=1, cols=len(pannelli),
                        subplot_titles=[p[1] for p in pannelli], horizontal_spacing=0.10)
    for i, (colonna, nome, percentuale, soglia) in enumerate(pannelli, start=1):
        serie = completi[colonna]
        # Sopra la soglia il dividendo non e' coperto: il colore lo dice, e la
        # linea tratteggiata no perche' le linee tratteggiate sono riservate.
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

    fig = _layout(fig, t, title="Il dividendo e' coperto?",
                  subtitle="La linea segna il punto di rottura: sopra il 100% degli utili, o sotto "
                           "1 volta la cassa libera, il dividendo non e' finanziato dall'attivita'. "
                           "Le barre rosse sono gli anni in cui e' accaduto.",
                  height=350)
    for annotazione in fig.layout.annotations:
        annotazione.font = dict(size=12, color=t["ink2"], family=FONT)
        if annotazione.yref == "paper" and annotazione.y and annotazione.y > 0.9:
            annotazione.y = 0.93
    fig.update_layout(showlegend=False, margin=dict(l=56, r=24, t=124, b=48))
    return fig


def total_return_chart(analisi, prices, dark: bool = False) -> go.Figure:
    """Quanto del rendimento e' venuto dalle cedole e quanto dal prezzo."""
    t = tokens(dark)
    if analisi is None or prices is None or prices.empty or not analisi.pays_dividends:
        return _empty("Storico prezzi insufficiente per la scomposizione", t, height=300)
    chiusure = prices["Close"].dropna()
    tr = analisi.total_return
    anni = tr.get("anni") or 10
    inizio = chiusure.index[-1] - pd.Timedelta(days=int(365.25 * anni))
    finestra = chiusure[chiusure.index >= inizio]
    if len(finestra) < 100:
        return _empty("Storico prezzi insufficiente per la scomposizione", t, height=300)

    solo_prezzo = finestra / finestra.iloc[0] * 100
    # Ricostruiamo giorno per giorno il valore con le cedole reinvestite.
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
    fig.add_trace(_line(finestra.index, solo_prezzo.values, "Solo prezzo", t["s2"], t, width=1.5))
    fig.add_trace(_line(finestra.index, totale.values, "Con dividendi reinvestiti", t["s1"], t))
    for valori, colore, etichetta in ((totale, t["s1"], "con dividendi"),
                                      (solo_prezzo, t["s2"], "solo prezzo")):
        fig.add_annotation(x=finestra.index[-1], y=float(valori.iloc[-1]), text=f" {etichetta}",
                           showarrow=False, xanchor="left", font=dict(size=11, color=colore))

    quota = tr.get("quota_dividendi")
    coda = ""
    if quota is not None and 0 < quota <= 1:
        coda = f" I dividendi sono il {fmt.pct(quota)} del rendimento totale del periodo."
    elif tr.get("contributo_dividendi") is not None:
        coda = (f" I dividendi hanno aggiunto "
                f"{fmt.num(tr['contributo_dividendi'] * 100, 1)} punti percentuali.")
    return _layout(fig, t, title="Da dove e' venuto il rendimento",
                   subtitle=f"Entrambe le linee partono da 100 a {anni:.0f} anni fa. La distanza "
                            f"fra le due e' l'effetto delle cedole reinvestite.{coda}",
                   height=360, unit="indice = 100")


def safety_factors_chart(analisi, dark: bool = False) -> go.Figure:
    """I punti che compongono il punteggio di solidita', uno per uno."""
    t = tokens(dark)
    modo = "dark" if dark else "light"
    if analisi is None or analisi.safety is None or not analisi.safety.factors:
        return _empty("Punteggio di solidita' non calcolabile", t, height=300)
    fattori = [f for f in analisi.safety.factors if f.points != 0]
    if not fattori:
        return _empty("Nessun fattore ha inciso sul punteggio", t, height=260)
    fattori = sorted(fattori, key=lambda f: f.points)

    etichette = [f.label for f in fattori]
    punti = [f.points for f in fattori]
    colori = [DIVERGENTE_POSITIVO[modo] if p > 0 else DIVERGENTE_NEGATIVO[modo] for p in punti]
    testi = [f"{p:+.0f}" for p in punti]
    spiegazioni = [f.explanation for f in fattori]

    fig = go.Figure(go.Bar(
        x=punti, y=etichette, orientation="h", width=0.6,
        marker=dict(color=colori, cornerradius=4, line=dict(color=t["surface"], width=2)),
        text=testi, textposition="outside", textfont=dict(size=12, color=t["ink"]),
        customdata=spiegazioni,
        hovertemplate="%{y}: %{x:+.0f} punti<br>%{customdata}<extra></extra>",
        showlegend=False,
    ))
    fig.add_vline(x=0, line=dict(color=t["axis"], width=1.5))
    limite = max(abs(min(punti)), abs(max(punti))) * 1.45
    fig = _layout(fig, t, title="Da dove viene il punteggio di solidita'",
                  subtitle=f"Si parte da 50 e si arriva a {fmt.num(analisi.safety.score, 0)}. "
                           "Blu a destra: punti a favore. Rosso a sinistra: punti contro. "
                           "Passa sopra una barra per la spiegazione.",
                  height=max(300, 56 * len(fattori) + 130))
    fig.update_xaxes(range=[-limite, limite], showgrid=True, gridcolor=t["grid"], linewidth=0,
                     title=dict(text="punti", font=dict(size=11, color=t["muted"])))
    fig.update_yaxes(showgrid=False, zeroline=False, tickfont=dict(size=12, color=t["ink2"]))
    fig.update_layout(showlegend=False, hovermode="closest",
                      margin=dict(l=300, r=60, t=104, b=52))
    return fig


def backtest_chart(analisi, dark: bool = False) -> go.Figure:
    """Il segnale sul rendimento ha funzionato su questo titolo?"""
    t = tokens(dark)
    verifica = analisi.backtest if analisi else None
    if verifica is None or not verifica.buckets:
        messaggio = (verifica.note if verifica and verifica.note
                     else "Verifica retrospettiva non disponibile")
        return _empty(messaggio, t, height=280)
    gruppi = [b for b in verifica.buckets if b.observations]
    if not gruppi:
        return _empty(verifica.note or "Nessuna osservazione utilizzabile", t, height=280)

    etichette = [b.label.replace(" (segnale di ", "<br>(").replace(")", ")") for b in gruppi]
    valori = [b.avg_return_2y for b in gruppi]
    conteggi = [b.observations for b in gruppi]
    modo = "dark" if dark else "light"
    colori = [DIVERGENTE_POSITIVO[modo] if (v or 0) >= 0 else DIVERGENTE_NEGATIVO[modo]
              for v in valori]
    fig = go.Figure(go.Bar(
        x=etichette, y=valori, width=0.5,
        marker=dict(color=colori, cornerradius=4, line=dict(color=t["surface"], width=2)),
        text=[f"{v:+.0%}" if v is not None else "n/d" for v in valori],
        textposition="outside", textfont=dict(size=13, color=t["ink"]),
        customdata=conteggi,
        hovertemplate="%{x}<br>media 2 anni: %{y:+.1%}<br>%{customdata} osservazioni<extra></extra>",
        showlegend=False,
    ))
    fig.add_hline(y=0, line=dict(color=t["axis"], width=1.5))
    fig = _layout(fig, t, title="Il segnale ha funzionato su questo titolo?",
                  subtitle="Rendimento totale medio dei due anni successivi, a seconda di dove "
                           "stava il rendimento da dividendo rispetto alla propria storia. "
                           f"{verifica.observations} osservazioni mensili con finestre sovrapposte: "
                           "un indizio, non una dimostrazione.",
                  height=360, percent_axis=True)
    fig.update_layout(showlegend=False, hovermode="closest")
    return fig


def dividend_charts(analysis, dark: bool = False) -> dict[str, go.Figure]:
    """I sei grafici della scheda dividendi."""
    d = analysis.dividends
    return {
        "dividendi_storia": dividend_history_chart(d, dark),
        "dividendi_rendimento": yield_history_chart(d, dark),
        "dividendi_copertura": payout_coverage_chart(d, dark),
        "dividendi_rendimento_totale": total_return_chart(d, analysis.data.prices, dark),
        "dividendi_solidita": safety_factors_chart(d, dark),
        "dividendi_verifica": backtest_chart(d, dark),
    }
