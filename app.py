"""SET X-Ray - web interface.

Run with:
    streamlit run app.py

One screen: type the symbol, read the decision, then go down into the detail if
you want to see where it came from. The order of the sections is deliberate:
the answer first, the evidence after.
"""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from setxray import __version__, charts, fmt
from setxray.datasource import POPULAR_SET_SYMBOLS, clear_cache
from setxray.demo import PROFILE_NAMES, PROFILES
from setxray.engine import Analysis, NoDataError, analyze
from setxray.scoring import BUY, HOLD, SELL
from setxray.sources import describe_sources

st.set_page_config(page_title="SET X-Ray - Thai stock dividends and analysis",
                   page_icon="📊", layout="wide")

VERDICT_STYLE = {
    BUY: ("#0ca30c", "Buy or accumulate"),
    HOLD: ("#fab219", "Hold, without adding"),
    SELL: ("#d03b3b", "Sell or reduce"),
}

st.markdown("""
<style>
  .verdict { border-radius: 14px; padding: 22px 26px; color: #fff; margin-bottom: 4px; }
  .verdict h1 { font-size: 2.0rem; margin: 0 0 6px 0; font-weight: 700; letter-spacing: -0.02em; }
  .verdict p  { margin: 0; font-size: 1.02rem; opacity: 0.95; }
  .card { border: 1px solid rgba(11,11,11,0.12); border-radius: 12px;
          padding: 14px 16px; height: 100%; }
  .card .label { font-size: 0.78rem; text-transform: uppercase;
                 letter-spacing: 0.05em; opacity: 0.7; }
  .card .value { font-size: 1.5rem; font-weight: 650; line-height: 1.25; }
  .card .note { font-size: 0.82rem; opacity: 0.72; }
  .serious { border-left: 4px solid #d03b3b; padding: 8px 14px; margin-bottom: 8px;
             background: rgba(208,59,59,0.08); border-radius: 6px; }
  .warning { border-left: 4px solid #fab219; padding: 8px 14px; margin-bottom: 8px;
             background: rgba(250,178,25,0.10); border-radius: 6px; }
  .prose p { margin-bottom: 0.7rem; line-height: 1.55; }
  .secondary { border: 1px solid rgba(11,11,11,0.14); border-radius: 10px;
               padding: 12px 16px; margin: 10px 0 2px 0; }
  .secondary .heading { font-size: 0.8rem; text-transform: uppercase;
                        letter-spacing: 0.05em; opacity: 0.7; margin-bottom: 2px; }
  .disagreement { border-left: 4px solid #ec835a; background: rgba(236,131,90,0.10);
                  padding: 10px 14px; border-radius: 6px; margin-top: 8px; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False, ttl=1800)
def _analyze_cached(symbol: str, risk_free: float, erp: float) -> Analysis:
    """One request per symbol and per set of assumptions: Yahoo dislikes bursts."""
    return analyze(symbol, risk_free=risk_free, erp=erp)


def card(label: str, value: str, note: str = "", colour: str = "") -> str:
    style = f" style='color:{colour}'" if colour else ""
    return (f"<div class='card'><div class='label'>{label}</div>"
            f"<div class='value'{style}>{value}</div>"
            f"<div class='note'>{note}</div></div>")


# Direct link: ?symbol=PTT opens the app with the analysis already running, so
# the address of a stock can be bookmarked or shared. The old Italian parameter
# still works, for links saved before the interface was translated.
_from_url = st.query_params.get("symbol") or st.query_params.get("simbolo")
if _from_url and "simbolo" not in st.session_state:
    st.session_state["simbolo"] = _from_url
    st.session_state["esegui"] = True


# --------------------------------------------------------------------------
# sidebar
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### SET X-Ray")
    st.caption(f"Dividends and fundamental analysis - Stock Exchange of Thailand - version {__version__}")

    simbolo = st.text_input("SET symbol", value=st.session_state.get("simbolo", "PTT"),
                            help="For example PTT, AOT, CPALL, SCB. The .BK suffix is optional.")
    avvia = st.button("Analyse", type="primary", use_container_width=True)

    st.markdown("**Heavily traded stocks**")
    colonne = st.columns(2)
    for i, (codice, descrizione) in enumerate(POPULAR_SET_SYMBOLS):
        if colonne[i % 2].button(codice, key=f"quick-{codice}", help=descrizione,
                                 use_container_width=True):
            st.session_state["simbolo"] = codice
            st.session_state["esegui"] = True
            st.rerun()

    with st.expander("Try it without internet (made-up data)"):
        st.caption("Six invented companies, to see how the analysis behaves in the typical "
                   "cases. The numbers are not real.")
        for profilo, descrizione in PROFILES.items():
            nome = PROFILE_NAMES.get(profilo, profilo)
            if st.button(f"Demo: {nome}", key=f"demo-{profilo}", help=descrizione,
                         use_container_width=True):
                st.session_state["simbolo"] = f"demo:{profilo}"
                st.session_state["esegui"] = True
                st.rerun()

    with st.expander("Valuation assumptions"):
        st.caption("These change the return you demand from the investment, and therefore the "
                   "estimated value.")
        tasso = st.slider("Risk-free rate (Thailand, 10 years)", 0.5, 6.0, 2.8, 0.1,
                          format="%.1f%%") / 100
        premio = st.slider("Equity risk premium", 3.0, 12.0, 7.5, 0.5,
                           format="%.1f%%") / 100
        if st.button("Clear the data cache", use_container_width=True):
            rimossi = clear_cache()
            _analyze_cached.clear()
            st.success(f"Cache cleared ({rimossi} files).")

    st.divider()
    attive = [riga["source"] for riga in describe_sources() if riga["active"]]
    st.caption(f"Dividends from {len(attive)} active sources · prices and statements from Yahoo "
               "Finance. See the *Data sources* tab. This is not financial advice.")

if avvia:
    st.session_state["simbolo"] = simbolo
    st.session_state["esegui"] = True

if not st.session_state.get("esegui"):
    st.title("Dividends and analysis of a Stock Exchange of Thailand share")
    st.markdown("""
Type the symbol of a stock listed on the **SET** in Bangkok (for example `PTT`,
`AOT`, `CPALL`) and press **Analyse**.

The tool is built around one question: **how has this stock paid dividends over
the last ten years, and what does that history say about what to do today?** It
reconstructs every payment, measures growth, cuts and continuity, works out how
much of the total return came from the coupons, estimates what it will pay over
the next two years, and ends with **buy, hold or sell** and the reasons why.

The horizon is **one to two years at the very least**: this is not a tool for
short-term trading.
""")
    colonne = st.columns(3)
    with colonne[0]:
        st.markdown("#### Ten years of coupons")
        st.caption("Dividend per share year by year, average growth over 3, 5 and 10 years, "
                   "cuts and skipped years, and how much of the total return came from the "
                   "coupons rather than from the price.")
    with colonne[1]:
        st.markdown("#### Will the dividend hold?")
        st.caption("A safety score built from factors you can see one by one: cover from "
                   "earnings, cover from real cash, debt, the trend in earnings, the history "
                   "of cuts, continuity.")
    with colonne[2]:
        st.markdown("#### Buy or sell, and why")
        st.caption("Today's yield against the stock's own history, the two-year dividend "
                   "forecast, and a backtest of how this signal behaved on this very stock.")
    st.info("No internet, or you just want to see what it looks like? Open **Try it without "
            "internet** in the sidebar: six invented companies cover the typical cases, "
            "including a dividend that was cut and an irregular payer.", icon="💡")
    with st.expander("Where the dividend data comes from"):
        st.caption("The tool queries several archives and compares the results, because on SET "
                   "stocks the dividend is the figure that is easiest to get wrong.")
        st.dataframe(pd.DataFrame([{
            "Source": riga["source"],
            "Needs a key": riga["api_key"],
            "Active now": "yes" if riga["active"] else "no",
            "Notes": riga["note"],
        } for riga in describe_sources()]), use_container_width=True, hide_index=True)
    st.stop()

# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------
richiesto = st.session_state.get("simbolo", "PTT")
if st.query_params.get("symbol") != richiesto:
    st.query_params["symbol"] = richiesto
try:
    with st.spinner(f"Fetching and analysing {richiesto}..."):
        analisi = _analyze_cached(richiesto, tasso, premio)
except NoDataError as errore:
    st.error(str(errore), icon="⚠️")
    st.stop()
except ValueError as errore:
    st.error(f"Invalid symbol: {errore}", icon="⚠️")
    st.stop()
except Exception as errore:  # network, Yahoo rate limit, unexpected formats
    st.error(f"The analysis could not be completed: {type(errore).__name__} - {errore}",
             icon="⚠️")
    st.info("If it keeps happening, try clearing the data cache in the sidebar, or come back "
            "in a few minutes: Yahoo Finance limits how many requests it accepts.")
    st.stop()

m, v, d = analisi.metrics, analisi.valuation, analisi.verdict
scuro = st.get_option("theme.base") == "dark"
valuta = m.currency

if analisi.data.is_demo:
    st.warning("**Demo mode.** Invented company and synthetic numbers: they exist only to show "
               "how the app works. Do not use them to decide anything.", icon="🧪")

st.markdown(f"## {m.name}")
sottotitolo = [f"`{m.symbol}`"]
if m.sector:
    sottotitolo.append(m.sector)
if m.industry:
    sottotitolo.append(m.industry)
sottotitolo.append(f"data as of {fmt.date(m.trend.get('last_date'))}")
if analisi.data.from_cache:
    sottotitolo.append("from local cache")
st.caption(" · ".join(sottotitolo))

# --- the dividend answer, before everything else --------------------------
div = analisi.dividends
segnale = div.signal if (div and div.pays_dividends and div.signal) else None

if segnale is not None:
    colore, spiegazione = VERDICT_STYLE[segnale.action]
    sicurezza = div.safety
    st.markdown(
        f"<div class='verdict' style='background:{colore}'>"
        f"<h1>{segnale.headline}</h1><p>{spiegazione} · horizon 1-2 years · "
        f"dividend safety {fmt.num(sicurezza.score, 0)}/100 ({sicurezza.band}) · "
        f"cut risk {sicurezza.cut_risk_band}</p></div>",
        unsafe_allow_html=True,
    )

    rendimento = div.yield_stats
    colonne = st.columns(4)
    percentile = rendimento.get("percentile")
    nota_percentile = ("" if percentile is None
                       else f"more generous than {fmt.pct(percentile)} of its own history")
    colonne[0].markdown(card(
        "Yield today", fmt.pct(rendimento.get("attuale")),
        f"historical median {fmt.pct(rendimento.get('mediana'))} · {nota_percentile}",
    ), unsafe_allow_html=True)
    previsione = div.forecast
    colonne[1].markdown(card(
        "Dividend per share", fmt.money(rendimento.get("dps_indicato"), valuta),
        (f"next 12 months estimated at {fmt.money(previsione.year1_base, valuta)}"
         if previsione and previsione.ok else "annualised, most recent payments"),
    ), unsafe_allow_html=True)
    atteso = segnale.expected_return_2y
    colonne[2].markdown(card(
        "Expected return over 2 years", fmt.pct(atteso, sign=True),
        (f"{fmt.pct(segnale.income_component, sign=True)} from coupons and "
         f"{fmt.pct(segnale.price_component, sign=True)} from the price"),
        colour="#0ca30c" if (atteso or 0) > 0.08 else "#d03b3b" if (atteso or 0) < 0 else "",
    ), unsafe_allow_html=True)
    etichetta = ("Buy below" if segnale.action != SELL else "Would become interesting below")
    colonne[3].markdown(card(
        etichetta, fmt.money(segnale.entry_price, valuta),
        f"estimated value {fmt.money(segnale.fair_price, valuta)} · "
        f"trim above {fmt.money(segnale.exit_price, valuta)}",
    ), unsafe_allow_html=True)

    st.markdown("### Why")
    for motivo in segnale.reasons:
        st.markdown(f"- {motivo}")

    # The general verdict as a confirmation or as a contradiction: when the two
    # models diverge the user must be told, not handed an average.
    generale = d.expected_return_2y
    st.markdown(
        f"<div class='secondary'><div class='heading'>General fundamental analysis "
        f"(earnings, cash, equity, debt)</div>"
        f"<b>{d.headline}</b> · score {fmt.num(d.composite, 0)}/100 · "
        f"expected return {fmt.pct(generale, sign=True)}"
        + ("<br><span style='font-size:0.88rem;opacity:0.85'>The price looks low against "
           "earnings, but the red flags in the accounts win out: this is the classic profile "
           "of a value trap.</span>"
           if d.action == SELL and (generale or 0) > 0.10 else "")
        + "</div>",
        unsafe_allow_html=True,
    )
    if d.action != segnale.action:
        st.markdown(
            f"<div class='disagreement'><b>The two models disagree.</b> "
            f"On dividends the signal is <b>{segnale.action}</b>, on general fundamentals "
            f"<b>{d.action}</b>. This is not a bug: they look at different things. The dividend "
            "model weighs how sustainable the coupon is, the general one weighs earnings and "
            "equity. If you are after income, follow the first and read the second as a "
            "warning; if you are after capital growth, the other way round.</div>",
            unsafe_allow_html=True,
        )
else:
    colore, spiegazione = VERDICT_STYLE[d.action]
    st.markdown(
        f"<div class='verdict' style='background:{colore}'>"
        f"<h1>{d.headline}</h1><p>{spiegazione} · horizon 1-2 years · "
        f"score {fmt.num(d.composite, 0)}/100 · "
        f"data reliability: {d.data_quality}</p></div>",
        unsafe_allow_html=True,
    )
    st.warning("**This stock pays no dividend** according to the sources available, so the "
               "verdict above comes from the general fundamental analysis. The *Dividends* tab "
               "explains what to do if you know that it does pay one.",
               icon="ℹ️")
    colonne = st.columns(4)
    colonne[0].markdown(card("Price today", fmt.money(m.price, valuta),
                             f"52 weeks: {fmt.num(m.trend.get('low_52w'))} - "
                             f"{fmt.num(m.trend.get('high_52w'))}"), unsafe_allow_html=True)
    colonne[1].markdown(card("Estimated value", fmt.money(v.fair_base, valuta),
                             f"range {fmt.num(v.fair_bear)} - {fmt.num(v.fair_bull)}"),
                        unsafe_allow_html=True)
    colonne[2].markdown(card("Expected return over 2 years",
                             fmt.pct(d.expected_return_2y, sign=True),
                             f"{fmt.pct(d.expected_annualized, sign=True)} a year"),
                        unsafe_allow_html=True)
    colonne[3].markdown(card("Entry price",
                             fmt.money(d.entry_price, valuta) if d.entry_price else fmt.NA,
                             "below this price the +20% target stays within reach"),
                        unsafe_allow_html=True)
    st.markdown("### Why")
    for motivo in d.reasons:
        st.markdown(f"- {motivo}")

st.info(d.position_note, icon="💼")

if d.grave_flags or d.warning_flags:
    st.markdown("### Red flags in the accounts")
    for flag in d.grave_flags:
        st.markdown(f"<div class='serious'><b>Serious</b> - {flag.text}</div>",
                    unsafe_allow_html=True)
    for flag in d.warning_flags:
        st.markdown(f"<div class='warning'><b>Watch out</b> - {flag.text}</div>",
                    unsafe_allow_html=True)


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------
schede = st.tabs(["Dividends (10 years)", "Past", "Present", "Future",
                  "Score detail", "Tables", "Data sources"])

with schede[0]:
    if segnale is None:
        st.markdown("#### No dividend on record")
        for nota in (div.notes if div else []):
            st.markdown(f"- {nota}")
        st.markdown("""
If you know the stock pays and the data is missing, you can supply it yourself:
copy the table of payments from the SET website into a text file and save it as
`data/<SYMBOL>-dividends.csv`, with two columns:

```
date,dividend
2016-04-25,1.10
2016-09-05,1.10
```

The app reads it instead of the APIs and treats it as the most reliable source.
See the **Data sources** tab for the other archives available.
""")
    else:
        st.markdown("#### Ten years of distribution")
        st.markdown("<div class='prose'>"
                    + "".join(f"<p>{p}</p>" for p in analisi.narrative["dividends"])
                    + "</div>", unsafe_allow_html=True)

        st.plotly_chart(charts.dividend_history_chart(div, scuro), use_container_width=True)
        st.plotly_chart(charts.yield_history_chart(div, scuro), use_container_width=True)
        due = st.columns(2)
        due[0].plotly_chart(charts.payout_coverage_chart(div, scuro), use_container_width=True)
        due[1].plotly_chart(charts.total_return_chart(div, analisi.data.prices, scuro),
                            use_container_width=True)
        st.plotly_chart(charts.safety_factors_chart(div, scuro), use_container_width=True)

        st.markdown("##### Dividend safety, factor by factor")
        st.caption("It starts from 50 points. Each factor adds or removes points according to "
                   "the rule shown: this is a stated criterion, not a statistical model trained "
                   "on a historical database of cuts. You are free to disagree on a factor and "
                   "redo the sum.")
        st.dataframe(pd.DataFrame([{
            "Factor": fattore.label,
            "Value": (fmt.pct(fattore.value) if fattore.fmt == "pct"
                      else fmt.mult(fattore.value) if fattore.fmt == "x"
                      else fmt.num(fattore.value, 0)),
            "Points": f"{fattore.points:+.0f}",
            "Why": fattore.explanation,
        } for fattore in div.safety.factors]), use_container_width=True, hide_index=True)

        st.markdown("##### The dividend forecast, method by method")
        st.dataframe(pd.DataFrame([{
            "Method": metodo.label,
            "Estimated dividend": (fmt.money(metodo.value, valuta) if metodo.usable
                                   else "not applicable"),
            "Weight": f"{metodo.weight:.0%}" if metodo.weight else "-",
            "Assumptions": metodo.detail or metodo.skipped_reason or "",
        } for metodo in div.forecast.methods]), use_container_width=True, hide_index=True)

        st.plotly_chart(charts.backtest_chart(div, scuro), use_container_width=True)

        st.markdown("##### The numbers, year by year")
        etichette_div = {
            "dps": f"Dividend per share ({valuta})", "stacchi": "Number of payments",
            "prezzo_medio": f"Average price for the year ({valuta})",
            "rendimento": "Yield on the average price",
            "eps": f"Earnings per share ({valuta})", "payout": "Share of earnings paid out",
            "fcf_per_azione": f"Free cash flow per share ({valuta})",
            "copertura_cassa": "Cover from free cash flow (times)",
            "variazione": "Change on the previous year",
        }
        tabella_div = div.years[[c for c in etichette_div if c in div.years.columns]].copy()
        tabella_div.index = [str(int(a)) for a in tabella_div.index]
        tabella_div = tabella_div.rename(columns=etichette_div).T
        st.dataframe(tabella_div.style.format("{:,.4g}", na_rep=fmt.NA),
                     use_container_width=True)
        st.caption("The last column is the year in progress: it is incomplete by definition and "
                   "enters no average.")

        if div.notes:
            st.markdown("##### Limits of this analysis")
            for nota in div.notes:
                st.markdown(f"- {nota}")

with schede[1]:
    st.markdown("#### What kind of company it has been")
    st.markdown("<div class='prose'>" + "".join(f"<p>{p}</p>" for p in analisi.narrative["past"])
                + "</div>", unsafe_allow_html=True)
    st.plotly_chart(charts.revenue_chart(m, scuro), use_container_width=True)
    due = st.columns(2)
    due[0].plotly_chart(charts.margins_chart(m, scuro), use_container_width=True)
    due[1].plotly_chart(charts.returns_chart(m, scuro), use_container_width=True)
    due = st.columns(2)
    due[0].plotly_chart(charts.cashflow_chart(m, scuro), use_container_width=True)
    due[1].plotly_chart(charts.eps_dividend_chart(m, scuro), use_container_width=True)
    st.plotly_chart(charts.dividend_chart(m, scuro), use_container_width=True)
    st.plotly_chart(charts.relative_chart(m, analisi.data.prices, analisi.data.benchmark, scuro),
                    use_container_width=True)

with schede[2]:
    st.markdown("#### Where it stands now")
    st.markdown("<div class='prose'>" + "".join(f"<p>{p}</p>" for p in analisi.narrative["present"])
                + "</div>", unsafe_allow_html=True)
    st.plotly_chart(charts.price_chart(m, v, analisi.data.prices, scuro), use_container_width=True)
    due = st.columns(2)
    due[0].plotly_chart(charts.multiple_history_chart(m, "pe", scuro), use_container_width=True)
    due[1].plotly_chart(charts.multiple_history_chart(m, "pb", scuro), use_container_width=True)
    st.plotly_chart(charts.health_chart(m, scuro), use_container_width=True)

with schede[3]:
    st.markdown("#### What to expect over 1-2 years")
    st.markdown("<div class='prose'>" + "".join(f"<p>{p}</p>" for p in analisi.narrative["future"])
                + "</div>", unsafe_allow_html=True)
    st.plotly_chart(charts.methods_chart(m, v, scuro), use_container_width=True)
    st.markdown("##### The models, one by one")
    righe = []
    for metodo in v.methods:
        righe.append({
            "Method": metodo.label,
            "Value per share": (fmt.money(metodo.fair_value, valuta) if metodo.usable
                                else "not applicable"),
            "Weight": f"{metodo.weight:.0%}" if metodo.weight else "-",
            "Assumptions": metodo.detail or metodo.skipped_reason or "",
        })
    st.dataframe(pd.DataFrame(righe), use_container_width=True, hide_index=True)
    st.markdown("##### When to revisit the decision")
    for innesco in d.review_triggers:
        st.markdown(f"- {innesco}")

with schede[4]:
    st.plotly_chart(charts.pillars_chart(d, scuro), use_container_width=True)
    st.markdown("#### How the score is built")
    st.caption("Each area is the weighted average of a handful of indicators. Indicators with "
               "no data carry no weight, and their absence lowers the overall reliability.")
    for pilastro in d.pillars:
        titolo = (f"{pilastro.label} - "
                  f"{fmt.NA if pilastro.score is None else f'{pilastro.score:.0f}/100'} "
                  f"(weight {pilastro.weight:.0%})")
        with st.expander(titolo, expanded=pilastro.score is not None and pilastro.score < 45):
            st.caption(pilastro.question)
            st.dataframe(pd.DataFrame([{
                "Indicator": criterio.label,
                "Value": criterio.formatted(),
                "Score": fmt.NA if criterio.score is None else f"{criterio.score:.0f}",
                "Weight": f"{criterio.weight:.1f}",
                "Note": criterio.note,
            } for criterio in pilastro.criteria]), use_container_width=True, hide_index=True)

with schede[5]:
    st.markdown("#### The numbers, financial year by financial year")
    st.caption("The full table: every chart on this page is built from it.")
    if m.years is not None and not m.years.empty:
        etichette = {
            "revenue": "Revenue", "gross_profit": "Gross profit",
            "operating_income": "Operating income",
            "ebitda": "EBITDA", "net_income": "Net income", "eps": "Earnings per share",
            "dps": "Dividend per share", "equity": "Shareholders' equity",
            "total_assets": "Total assets",
            "total_debt": "Total debt", "net_debt": "Net debt", "cash": "Cash",
            "cfo": "Cash from operations", "capex": "Capital spending", "fcf": "Free cash flow",
            "gross_margin": "Gross margin", "operating_margin": "Operating margin",
            "net_margin": "Net margin", "roe": "ROE", "roic": "ROIC", "roa": "ROA",
            "net_debt_ebitda": "Net debt / EBITDA", "debt_equity": "Debt / equity",
            "interest_coverage": "Interest coverage", "current_ratio": "Current ratio",
            "equity_ratio": "Equity / assets", "payout": "Share of earnings paid out",
        }
        tabella = m.years[[c for c in etichette if c in m.years.columns]].copy()
        tabella.index = [data.strftime("%Y") for data in tabella.index]
        tabella = tabella.rename(columns=etichette).T
        st.dataframe(tabella.style.format("{:,.4g}", na_rep=fmt.NA), use_container_width=True)
    else:
        st.warning("No financial statements available on Yahoo Finance for this stock.")

    st.markdown("#### Trailing twelve months and multiples")
    sintesi = {
        "Revenue (12 months)": fmt.big(m.ttm.get("revenue"), valuta),
        "Net income (12 months)": fmt.big(m.ttm.get("net_income"), valuta),
        "Free cash flow (12 months)": fmt.big(m.ttm.get("fcf"), valuta),
        "Earnings per share (12 months)": fmt.money(m.ttm.get("eps"), valuta),
        "Market capitalisation": fmt.big(m.market_cap, valuta),
        "P/E": fmt.mult(m.valuation.get("pe")),
        "P/B": fmt.mult(m.valuation.get("pb")),
        "EV/EBITDA": fmt.mult(m.valuation.get("ev_ebitda")),
        "Free cash flow yield": fmt.pct(m.valuation.get("fcf_yield")),
        "Dividend yield": fmt.pct(m.dividend.get("yield_current")),
        "Beta against the SET index": fmt.ratio(m.trend.get("beta")),
        "Annual volatility": fmt.pct(m.trend.get("volatility")),
        "Required return (models)": fmt.pct(v.cost_of_equity),
    }
    st.dataframe(pd.DataFrame({"Item": list(sintesi), "Value": list(sintesi.values())}),
                 use_container_width=True, hide_index=True)

with schede[6]:
    st.markdown("#### Where the dividends come from")
    if div is not None and div.source is not None:
        st.markdown(f"**Series used:** {div.source.provenance()}")
        righe_fonti = []
        for risultato in div.source.results:
            righe_fonti.append({
                "Source": risultato.label,
                "Trust": "*" * risultato.trust,
                "Outcome": (f"{risultato.payments} payments over {risultato.span_years:.1f} years"
                            if risultato.ok else (risultato.error or "no data")),
                "Used": "yes" if risultato.key == div.source.chosen else "",
                "Notes": risultato.note,
            })
        if righe_fonti:
            st.dataframe(pd.DataFrame(righe_fonti), use_container_width=True, hide_index=True)
        if div.source.disagreements:
            st.markdown("**The sources do not agree on everything:**")
            for avviso in div.source.disagreements:
                st.markdown(f"<div class='warning'>{avviso}</div>", unsafe_allow_html=True)
            st.caption("We make no attempt to reconcile them: on a figure like the dividend, "
                       "knowing that two archives disagree is worth more than an average of the "
                       "two. The SET website is the referee.")
    else:
        st.caption("No information on where the dividend data came from.")

    st.markdown("#### Every source available")
    st.caption("The tool queries every active archive and compares the results. The sources that "
               "require a key are free: register on the service's website and put the key in the "
               "environment variable shown.")
    st.dataframe(pd.DataFrame([{
        "Source": riga["source"],
        "Trust": "*" * riga["trust"],
        "Environment variable": riga["api_key"],
        "Active now": "yes" if riga["active"] else "no",
        "Notes": riga["note"],
    } for riga in describe_sources()]), use_container_width=True, hide_index=True)
    with st.expander("How to supply the dividends by hand (always works)"):
        st.markdown("""
No API is guaranteed to last. This route is: copy the table of payments from the
SET website and save it as `data/<SYMBOL>-dividends.csv`.

```
date,dividend
2016-04-25,1.10
2016-09-05,1.10
2017-04-24,1.20
```

`data,importo` works too, as do the semicolon as a separator and the comma as a
decimal mark. Dates are read day before month, the way the SET writes them. The
file is treated as the most reliable source and used instead of the APIs.
""")

    st.markdown("#### What was found in the rest of the data")
    copertura = analisi.data.data_coverage()
    st.dataframe(pd.DataFrame({
        "Item": list(copertura),
        "Available": ["yes" if valore else "no" for valore in copertura.values()],
    }), use_container_width=True, hide_index=True)
    limiti = list(m.notes) + list(v.notes) + list(analisi.data.warnings)
    if limiti:
        st.markdown("#### Limits worth keeping in mind")
        for nota in limiti:
            st.markdown(f"- {nota}")
    st.markdown("#### Method")
    st.markdown("""
**The dividend signal.** Today's yield (the most recent payments annualised,
divided by the price) is compared with its own daily history over the last ten
years. The estimated value assumes the yield closes **half** the gap back to its
median within two years: a full return to the mean would be a bet on the company
and the market becoming what they used to be. When dividend safety falls below 60
points, the target yield is raised by up to 90%, because a fragile dividend
permanently deserves a higher yield. When cut risk is high, the valuation uses the
dividend from the **pessimistic scenario**, not the current one.

The overall score (0-100) is the weighted average of five areas: valuation 25%,
business quality 20%, growth 20%, financial strength 20%, price trend 15%. The
trend carries little weight because the horizon is one to two years.

The estimated value comes from four independent models - historical multiple,
discounted dividends, discounted cash flow, justified book value - weighted
according to the kind of company. The final decision crosses the score with the
expected return, but serious problems in the accounts take precedence: two
serious problems mean **sell** even on a high score.

The data comes from Yahoo Finance, which for Thai stocks normally exposes the
last four financial years of statements and more than ten years of prices. Where
a figure is missing it is declared as missing, not estimated.
""")

st.divider()
report = analisi.report()
colonne = st.columns([1, 1, 3])
colonne[0].download_button("Download the report (markdown)", data=report.encode("utf-8"),
                           file_name=f"setxray-{m.symbol}.md", mime="text/markdown",
                           use_container_width=True)
if m.years is not None and not m.years.empty:
    csv = io.StringIO()
    m.years.to_csv(csv)
    colonne[1].download_button("Download the data (CSV)", data=csv.getvalue().encode("utf-8"),
                               file_name=f"setxray-{m.symbol}.csv", mime="text/csv",
                               use_container_width=True)
colonne[2].caption("Automated processing of public data. This is not financial advice, nor a "
                   "personalised recommendation: always check the figures against the company's "
                   "official statements and the Stock Exchange of Thailand website.")
