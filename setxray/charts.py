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
from setxray.metrics import Metrics
from setxray.scoring import Verdict
from setxray.valuation import Valuation

# --- colour tokens (palette validated for colour blindness, light and dark) -
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
    """Shared frame: title, subtitle, light grid, legend on top."""
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
        return _empty("Price history not available", t)
    close = prices["Close"].dropna()
    fig = go.Figure()

    # The value range as a horizontal band: you see at once whether the price
    # sits inside it, below it or above it.
    if v.fair_bear and v.fair_bull:
        fig.add_hrect(y0=v.fair_bear, y1=v.fair_bull, fillcolor=t["band"], line_width=0, layer="below")
    fig.add_trace(_line(close.index, close.values, "Price", t["s1"], t, width=2))
    if len(close) >= 200:
        fig.add_trace(_line(close.index, close.rolling(200).mean(), "200-day average", t["s3"], t, width=1.5))
    if len(close) >= 50:
        fig.add_trace(_line(close.index, close.rolling(50).mean(), "50-day average", t["s2"], t, width=1.5))
    if v.fair_base:
        fig.add_hline(y=v.fair_base, line=dict(color=t["ink2"], width=1.5),
                      annotation_text=f"estimated value {fmt.num(v.fair_base)}",
                      annotation_position="top right",
                      annotation_font=dict(size=11, color=t["ink2"]))
    if m.price:
        fig.add_trace(go.Scatter(
            x=[close.index[-1]], y=[m.price], mode="markers+text", name="today",
            marker=dict(color=t["s1"], size=9, line=dict(color=t["surface"], width=2)),
            text=[f" {fmt.num(m.price)}"], textposition="middle right",
            textfont=dict(size=12, color=t["ink"]), showlegend=False,
            hovertemplate="today: %{y:,.2f}<extra></extra>",
        ))
    return _layout(fig, t, title="Price and estimated value",
                   subtitle=f"Closing prices in {m.currency}. The grey band is the value range "
                            "estimated by the models, from the pessimistic to the optimistic scenario.",
                   height=420, unit=m.currency)


# --------------------------------------------------------------------------
# 2. comparison against the SET index
# --------------------------------------------------------------------------
def relative_chart(m: Metrics, prices: Optional[pd.DataFrame],
                   benchmark: Optional[pd.DataFrame], dark: bool = False) -> go.Figure:
    t = tokens(dark)
    if prices is None or prices.empty:
        return _empty("Price history not available", t)
    if benchmark is None or benchmark.empty:
        return _empty("SET index not available for the comparison", t)
    stock = prices["AdjClose"].dropna()
    index = benchmark["AdjClose"].dropna()
    joined = pd.concat([stock.rename("t"), index.rename("i")], axis=1).dropna()
    if joined.empty:
        return _empty("No period in common between the stock and the index", t)
    # Both series rebased to 100: the only correct way to compare two
    # quantities of different scale without a second axis.
    joined = joined / joined.iloc[0] * 100
    fig = go.Figure()
    fig.add_trace(_line(joined.index, joined["t"], m.symbol, t["s1"], t))
    fig.add_trace(_line(joined.index, joined["i"], "SET index", t["s2"], t, width=1.5))
    for column, color, label in (("t", t["s1"], m.symbol), ("i", t["s2"], "SET")):
        fig.add_annotation(x=joined.index[-1], y=joined[column].iloc[-1], text=f" {label}",
                           showarrow=False, xanchor="left", font=dict(size=11, color=color))
    return _layout(fig, t, title="Stock against the SET index",
                   subtitle="Total return, both rebased to 100 at the start date",
                   height=340, unit="index = 100")


# --------------------------------------------------------------------------
# 3. revenue and net income
# --------------------------------------------------------------------------
def revenue_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty or "revenue" not in years:
        return _empty("Income statement not available", t)
    labels = m.year_labels()
    scale, unit = (1e9, f"bn {m.currency}") if years["revenue"].max() >= 1e9 else (1e6, f"m {m.currency}")
    fig = go.Figure()
    fig.add_trace(_bar(labels, years["revenue"] / scale, "Revenue", t["s1"], t, unit=f" {unit}"))
    if "net_income" in years:
        fig.add_trace(_bar(labels, years["net_income"] / scale, "Net income", t["s2"], t, unit=f" {unit}"))
    return _layout(fig, t, title="Revenue and net income by financial year",
                   subtitle="What it bills and what is left of it, year by year", height=340, unit=unit)


# --------------------------------------------------------------------------
# 4. margins
# --------------------------------------------------------------------------
def margins_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty:
        return _empty("Margins cannot be computed without an income statement", t)
    labels = m.year_labels()
    fig = go.Figure()
    for column, name, color in (("gross_margin", "Gross margin", t["s1"]),
                                ("operating_margin", "Operating margin", t["s2"]),
                                ("net_margin", "Net margin", t["s3"])):
        if column in years and years[column].notna().any():
            series = years[column]
            last = series.dropna()
            # The value written beside the last point: it identifies the series
            # even for those who cannot tell the colours apart.
            label = fmt.pct(last.iloc[-1]) if not last.empty else None
            fig.add_trace(_line(labels, series.values, name, color, t, pct=True, end_label=label))
    if not fig.data:
        return _empty("Margins not available", t)
    fig = _layout(fig, t, title="Margins",
                  subtitle="How much of the revenue survives at each level of the income statement",
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
        return _empty("Returns cannot be computed without financial statements", t)
    labels = m.year_labels()
    fig = go.Figure()
    for column, name, color in (("roe", "ROE (on equity)", t["s1"]),
                                ("roic", "ROIC (on invested capital)", t["s2"]),
                                ("roa", "ROA (on assets)", t["s3"])):
        if column in years and years[column].notna().any():
            fig.add_trace(_bar(labels, years[column], name, color, t, hover_pct=True))
    if not fig.data:
        return _empty("Return ratios not available", t)
    return _layout(fig, t, title="Returns on capital",
                   subtitle="What the capital employed earns: above 10-12% the company creates value by reinvesting",
                   height=320, percent_axis=True)


# --------------------------------------------------------------------------
# 6. cash flows
# --------------------------------------------------------------------------
def cashflow_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty or "cfo" not in years:
        return _empty("Cash flow statement not available", t)
    labels = m.year_labels()
    scale, unit = (1e9, f"bn {m.currency}") if years["cfo"].abs().max() >= 1e9 else (1e6, f"m {m.currency}")
    fig = go.Figure()
    fig.add_trace(_bar(labels, years["cfo"] / scale, "Cash from operations", t["s1"], t, unit=f" {unit}"))
    if "capex" in years:
        fig.add_trace(_bar(labels, years["capex"] / scale, "Capital spending", t["s2"], t, unit=f" {unit}"))
    if "fcf" in years:
        # A third bar, not a line: it is the same unit as the other two, and a
        # line laid over bars reads badly.
        fig.add_trace(_bar(labels, years["fcf"] / scale, "Free cash flow", t["s3"], t, unit=f" {unit}"))
    return _layout(fig, t, title="Where the cash comes from and where it goes",
                   subtitle="Cash generated by operations, capital spending (negative) and the free cash left over",
                   height=340, unit=unit)


# --------------------------------------------------------------------------
# 7. earnings and dividend per share
# --------------------------------------------------------------------------
def eps_dividend_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty or "eps" not in years:
        return _empty("Earnings per share not available", t)
    labels = m.year_labels()
    fig = go.Figure()
    fig.add_trace(_bar(labels, years["eps"], "Earnings per share", t["s1"], t, unit=f" {m.currency}"))
    if "dps" in years and years["dps"].notna().any():
        fig.add_trace(_bar(labels, years["dps"], "Dividend per share", t["s2"], t, unit=f" {m.currency}"))
    return _layout(fig, t, title="Earnings and dividend per share",
                   subtitle="The gap between the two bars is the profit reinvested in the business",
                   height=320, unit=m.currency)


# --------------------------------------------------------------------------
# 8. financial strength (panels side by side, different scales)
# --------------------------------------------------------------------------
def health_chart(m: Metrics, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    years = m.years
    if years is None or years.empty:
        return _empty("Balance sheet data not available", t)
    labels = m.year_labels()
    panels = [
        ("net_debt_ebitda", "Net debt / EBITDA", "times", False),
        ("interest_coverage", "Interest coverage", "times", False),
        ("debt_equity", "Debt / equity", "times", False),
        ("payout", "Share of earnings paid out", "%", True),
    ]
    available = [p for p in panels if p[0] in years and years[p[0]].notna().any()]
    if not available:
        return _empty("Financial strength indicators cannot be computed", t)
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
    fig = _layout(fig, t, title="Financial strength over time",
                  subtitle="Four measures with different units, hence four separate panels",
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
# 9. history of the multiple
# --------------------------------------------------------------------------
def multiple_history_chart(m: Metrics, key: str = "pe", dark: bool = False) -> go.Figure:
    t = tokens(dark)
    names = {"pe": "P/E (price / earnings)", "pb": "P/B (price / book value)",
             "ps": "P/S (price / revenue)", "ev_ebitda": "EV/EBITDA"}
    hist = m.multiple_history.get(key)
    if not hist:
        return _empty(f"History of the {names.get(key, key)} not available", t)
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
                  annotation_text=f"median {fmt.mult(hist['median'])}", annotation_position="top right",
                  annotation_font=dict(size=11, color=t["ink2"]))
    current = m.valuation.get(key)
    if current:
        colour = t["good"] if current < hist["median"] else t["critical"]
        fig.add_hline(y=current, line=dict(color=colour, width=2),
                      annotation_text=f"today {fmt.mult(current)}", annotation_position="bottom right",
                      annotation_font=dict(size=11, color=colour))
    percentile = hist.get("percentile")
    # "in the bottom 0%" means nothing: better to say how many observations it beats.
    where = ("" if percentile is None
             else f" Today it is cheaper than {1 - percentile:.0%} of its historical observations.")
    return _layout(fig, t, title=f"{names.get(key, key)}: what it costs against its own past",
                   subtitle=f"Grey zone: the central half of the historical values.{where}",
                   height=330, unit="times")


# --------------------------------------------------------------------------
# 10. score by area
# --------------------------------------------------------------------------
def pillars_chart(verdict: Verdict, dark: bool = False) -> go.Figure:
    t = tokens(dark)
    pillars = [p for p in verdict.pillars if p.score is not None]
    if not pillars:
        return _empty("Scores cannot be computed", t)
    pillars = sorted(pillars, key=lambda p: p.score)
    labels = [p.label for p in pillars]
    scores = [p.score for p in pillars]
    # Status colours, not series colours: here the colour means
    # "pass / watch closely / fail". The number is always written out.
    colors = [t["good"] if s >= 65 else t["warning"] if s >= 45 else t["critical"] for s in scores]
    # Colour alone is not enough for those who cannot tell it apart: beside the
    # number we always put the word.
    words = ["good" if s >= 65 else "middling" if s >= 45 else "weak" for s in scores]
    fig = go.Figure(go.Bar(
        x=scores, y=labels, orientation="h", width=0.5,
        marker=dict(color=colors, cornerradius=4, line=dict(color=t["surface"], width=2)),
        text=[f"{s:.0f} - {w}" for s, w in zip(scores, words)], textposition="outside",
        textfont=dict(size=12, color=t["ink"]),
        hovertemplate="%{y}: %{x:.0f}/100<extra></extra>", showlegend=False,
    ))
    fig.add_vline(x=50, line=dict(color=t["axis"], width=1))
    fig = _layout(fig, t, title="Score by area",
                  subtitle="0-100. Green above 65, amber between 45 and 65, red below 45. The line marks the halfway point.",
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
        return _empty("No valuation model applicable", t)
    # Plotly draws horizontal bars from the bottom up: we reverse the order so
    # they read from the top, as the text describes them.
    labels = [method.label for method in usable][::-1]
    values = [method.fair_value for method in usable][::-1]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=values, y=labels, orientation="h", width=0.55, name="Individual models",
        marker=dict(color=t["s1"], cornerradius=4, line=dict(color=t["surface"], width=2)),
        text=[fmt.num(value) for value in values], textposition="outside",
        textfont=dict(size=12, color=t["ink"]),
        hovertemplate="%{y}: %{x:,.2f}<extra></extra>",
    ))
    if v.fair_base:
        # The weighted average is the conclusion, not one model among the
        # others: its own colour, on top.
        fig.add_trace(go.Bar(
            x=[v.fair_base], y=["Weighted average (conclusion)"], orientation="h",
            width=0.55, name="Weighted average",
            marker=dict(color=t["s3"], cornerradius=4, line=dict(color=t["surface"], width=2)),
            text=[fmt.num(v.fair_base)], textposition="outside",
            textfont=dict(size=12, color=t["ink"]),
            hovertemplate="%{y}: %{x:,.2f}<extra></extra>",
        ))
    if v.analyst_target:
        # An outside reference, with its own colour: this one is not our sum.
        fig.add_trace(go.Bar(
            x=[v.analyst_target], y=["Average analyst target"], orientation="h",
            width=0.55, name="Analyst reference",
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
    fig = _layout(fig, t, title="What it is worth, according to each method",
                  subtitle=f"Per-share values in {m.currency}. The vertical red line is the market "
                           f"price ({fmt.num(m.price)}): bars to the right of it mean the stock "
                           "trades at a discount.",
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
        return _empty("No dividend recorded for this stock", t)
    series = pd.Series(by_year).sort_index()
    fig = go.Figure()
    fig.add_trace(_bar([str(int(y)) for y in series.index], series.values,
                       "Dividend per share", t["s1"], t, unit=f" {m.currency}"))
    return _layout(fig, t, title="Dividend per share, year by year",
                   subtitle="Sum of every payment in each calendar year. The last year may be incomplete.",
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
        return _empty("No dividend recorded for this stock", t, height=300)
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
            colori.append(t["muted"]); etichette.append("year in progress, incomplete")
        elif valore <= 0:
            colori.append(t["critical"]); etichette.append("no dividend")
        elif variazione is not None and variazione == variazione and variazione < -0.02:
            colori.append(t["critical"]); etichette.append("cut")
        else:
            colori.append(t["s1"]); etichette.append("paid")

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=anni, y=valori, name="Dividend paid",
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
            x=anni_futuri, y=base, name="Forecast",
            marker=dict(color=t["s3"], cornerradius=4, line=dict(color=t["surface"], width=2)),
            error_y=dict(type="data", symmetric=False,
                         array=[a - b for a, b in zip(alto, base)],
                         arrayminus=[b - l for b, l in zip(base, basso)],
                         color=t["ink2"], thickness=1.5, width=6),
            hovertemplate="%{x}: %{y:,.2f} " + cur + " forecast<extra></extra>",
        ))

    tagli = analisi.streaks.get("tagli") or 0
    sottotitolo = ("Red bars: years with a cut or with no dividend at all. "
                   f"{'No cuts' if not tagli else str(tagli) + (' cut' if tagli == 1 else ' cuts')} "
                   "over the period. The green bars are the estimate for the next two years, "
                   "with their range.")
    return _layout(fig, t, title="Dividend per share, year by year",
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
                                   "Average yield for the year", t["s1"], t, hover_pct=True))
                return _layout(fig, t, title="Dividend yield, year by year",
                               subtitle="The year's dividend over the average price of that same "
                                        "year (no daily history available for a finer series)",
                               height=320, percent_axis=True)
        return _empty("Yield history not available", t, height=300)

    serie = analisi.daily_yield
    stat = analisi.yield_stats
    fig = go.Figure()
    if stat.get("p25") and stat.get("p75"):
        fig.add_hrect(y0=stat["p25"], y1=stat["p75"], fillcolor=t["band"], line_width=0,
                      layer="below")
    fig.add_trace(go.Scatter(
        x=serie.index, y=serie.values, name="Yield", mode="lines",
        line=dict(color=t["s1"], width=2),
        hovertemplate="%{x|%m/%Y}: %{y:.2%}<extra></extra>",
    ))
    if stat.get("mediana"):
        fig.add_hline(y=stat["mediana"], line=dict(color=t["ink2"], width=1.5),
                      annotation_text=f"median {fmt.pct(stat['mediana'])}",
                      annotation_position="top right",
                      annotation_font=dict(size=11, color=t["ink2"]))
    attuale = stat.get("attuale")
    if attuale:
        colore = t["good"] if attuale > (stat.get("mediana") or 0) else t["critical"]
        fig.add_hline(y=attuale, line=dict(color=colore, width=2),
                      annotation_text=f"today {fmt.pct(attuale)}",
                      annotation_position="bottom right",
                      annotation_font=dict(size=11, color=colore))
    percentile = stat.get("percentile")
    coda = ("" if percentile is None else
            f" Today it is more generous than {fmt.pct(percentile)} of the observations.")
    cadenza = analisi.cadence or 1
    return _layout(fig, t, title="Dividend yield over time",
                   subtitle=f"Annualised dividend (the last {cadenza} payments as of each date) "
                            "divided by the price on that day. Grey zone: the central half of "
                            f"the historical values.{coda}",
                   height=340, percent_axis=True)


def payout_coverage_chart(analisi, dark: bool = False) -> go.Figure:
    """Is the dividend covered by earnings and by cash?"""
    t = tokens(dark)
    if analisi is None or analisi.years.empty:
        return _empty("Coverage data not available", t, height=300)
    completi = analisi.complete_years()
    if completi.empty:
        return _empty("No complete year available", t, height=300)
    anni = [str(int(a)) for a in completi.index]

    pannelli = []
    if completi["payout"].notna().any():
        pannelli.append(("payout", "Share of earnings paid out", True, 1.0))
    if completi["copertura_cassa"].notna().any():
        pannelli.append(("copertura_cassa", "Cover from free cash flow", False, 1.0))
    if not pannelli:
        return _empty("Coverage cannot be computed: earnings or cash flows are missing", t, height=300)

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

    fig = _layout(fig, t, title="Is the dividend covered?",
                  subtitle="The line marks the breaking point: above 100% of earnings, or below "
                           "1 times free cash flow, the dividend is not funded by the business. "
                           "The red bars are the years when that happened.",
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
        return _empty("Price history too short for the breakdown", t, height=300)
    chiusure = prices["Close"].dropna()
    tr = analisi.total_return
    anni = tr.get("anni") or 10
    inizio = chiusure.index[-1] - pd.Timedelta(days=int(365.25 * anni))
    finestra = chiusure[chiusure.index >= inizio]
    if len(finestra) < 100:
        return _empty("Price history too short for the breakdown", t, height=300)

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
    fig.add_trace(_line(finestra.index, solo_prezzo.values, "Price only", t["s2"], t, width=1.5))
    fig.add_trace(_line(finestra.index, totale.values, "With dividends reinvested", t["s1"], t))
    for valori, colore, etichetta in ((totale, t["s1"], "with dividends"),
                                      (solo_prezzo, t["s2"], "price only")):
        fig.add_annotation(x=finestra.index[-1], y=float(valori.iloc[-1]), text=f" {etichetta}",
                           showarrow=False, xanchor="left", font=dict(size=11, color=colore))

    quota = tr.get("quota_dividendi")
    coda = ""
    if quota is not None and 0 < quota <= 1:
        coda = f" Dividends are {fmt.pct(quota)} of the total return over the period."
    elif tr.get("contributo_dividendi") is not None:
        coda = (f" Dividends added "
                f"{fmt.num(tr['contributo_dividendi'] * 100, 1)} percentage points.")
    return _layout(fig, t, title="Where the return came from",
                   subtitle=f"Both lines start at 100 {anni:.0f} years ago. The gap between them "
                            f"is the effect of the coupons reinvested.{coda}",
                   height=360, unit="index = 100")


def safety_factors_chart(analisi, dark: bool = False) -> go.Figure:
    """The points that make up the safety score, one by one."""
    t = tokens(dark)
    modo = "dark" if dark else "light"
    if analisi is None or analisi.safety is None or not analisi.safety.factors:
        return _empty("Safety score cannot be computed", t, height=300)
    fattori = [f for f in analisi.safety.factors if f.points != 0]
    if not fattori:
        return _empty("No factor moved the score", t, height=260)
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
        hovertemplate="%{y}: %{x:+.0f} points<br>%{customdata}<extra></extra>",
        showlegend=False,
    ))
    fig.add_vline(x=0, line=dict(color=t["axis"], width=1.5))
    limite = max(abs(min(punti)), abs(max(punti))) * 1.45
    fig = _layout(fig, t, title="Where the safety score comes from",
                  subtitle=f"It starts at 50 and ends at {fmt.num(analisi.safety.score, 0)}. "
                           "Blue to the right: points in favour. Red to the left: points against. "
                           "Hover over a bar for the explanation.",
                  height=max(300, 56 * len(fattori) + 130))
    fig.update_xaxes(range=[-limite, limite], showgrid=True, gridcolor=t["grid"], linewidth=0,
                     title=dict(text="points", font=dict(size=11, color=t["muted"])))
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
                     else "Backtest not available")
        return _empty(messaggio, t, height=280)
    gruppi = [b for b in verifica.buckets if b.observations]
    if not gruppi:
        return _empty(verifica.note or "No usable observation", t, height=280)

    # The bucket labels carry their signal in brackets ("High yield (buy
    # signal)"): we break the line there so the tick does not run wide.
    etichette = [b.label.replace(" (", "<br>(") for b in gruppi]
    valori = [b.avg_return_2y for b in gruppi]
    conteggi = [b.observations for b in gruppi]
    modo = "dark" if dark else "light"
    colori = [DIVERGING_POSITIVE[modo] if (v or 0) >= 0 else DIVERGING_NEGATIVE[modo]
              for v in valori]
    fig = go.Figure(go.Bar(
        x=etichette, y=valori, width=0.5,
        marker=dict(color=colori, cornerradius=4, line=dict(color=t["surface"], width=2)),
        text=[f"{v:+.0%}" if v is not None else fmt.NA for v in valori],
        textposition="outside", textfont=dict(size=13, color=t["ink"]),
        customdata=conteggi,
        hovertemplate="%{x}<br>2-year average: %{y:+.1%}<br>%{customdata} observations<extra></extra>",
        showlegend=False,
    ))
    fig.add_hline(y=0, line=dict(color=t["axis"], width=1.5))
    fig = _layout(fig, t, title="Has the signal worked on this stock?",
                  subtitle="Average total return over the following two years, depending on where "
                           "the dividend yield stood against its own history. "
                           f"{verifica.observations} monthly observations with overlapping "
                           "windows: a hint, not a proof.",
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
