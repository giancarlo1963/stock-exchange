"""The write-up: past, present, future and dividends, in English, from the numbers.

No hand-written copy and no language model: every sentence comes from a
threshold on a computed figure. The benefit is that the write-up cannot
contradict the charts, and the same company always produces the same text.
"""

from __future__ import annotations

from typing import Optional

from setxray import fmt
from setxray.metrics import Metrics
from setxray.scoring import Verdict
from setxray.valuation import Valuation


def _grade(value: Optional[float], thresholds: tuple[float, ...], words: tuple[str, ...]) -> str:
    """Turns a number into an adjective, by rising thresholds."""
    if value is None:
        return words[0]
    for threshold, word in zip(thresholds, words[1:]):
        if value < threshold:
            return word
    return words[-1]


# --------------------------------------------------------------------------
# PAST
# --------------------------------------------------------------------------
def past(m: Metrics) -> list[str]:
    """What kind of company it has been: growth, returns, shareholder payout."""
    out: list[str] = []
    years = m.year_labels()
    if not years:
        return ["Yahoo Finance has no historical financial statements for this stock, so the "
                "company's past cannot be reconstructed. The analysis below rests on the price "
                "history alone."]

    span = m.growth.get("revenue_span") or 0
    rev_cagr = m.growth.get("revenue_cagr")
    eps_cagr = m.growth.get("eps_cagr")
    opening = f"Across the {len(years)} financial years available ({years[0]}-{years[-1]})"
    if rev_cagr is None:
        out.append(f"{opening} revenue shows no measurable trend.")
    else:
        word = _grade(rev_cagr, (-0.02, 0.02, 0.06, 0.12),
                      ("", "falling sharply", "essentially flat", "growing modestly",
                       "growing well", "growing strongly"))
        out.append(f"{opening} revenue has been {word}: {fmt.pct(rev_cagr, sign=True)} a year "
                   "on average" + (f" over {span:.0f} years." if span else "."))

    if eps_cagr is not None and rev_cagr is not None:
        if eps_cagr > rev_cagr + 0.02:
            out.append(f"Earnings per share grew faster than revenue ({fmt.pct(eps_cagr, sign=True)} "
                       "a year): the company became more efficient, or reduced its share count.")
        elif eps_cagr < rev_cagr - 0.02:
            out.append(f"Earnings per share grew slower than revenue ({fmt.pct(eps_cagr, sign=True)} "
                       "a year): margins compressed, or new shares were issued.")
        else:
            out.append(f"Earnings per share tracked revenue ({fmt.pct(eps_cagr, sign=True)} a year).")

    up, total = m.growth.get("revenue_up_years"), m.growth.get("revenue_total_years")
    if up is not None and total:
        if up == total:
            out.append("Revenue grew in every year of the period: a steady path.")
        elif up == 0:
            out.append("Revenue did not grow in any of the years observed.")
        else:
            out.append(f"Growth was uneven: {up} years up out of {total}.")

    roe = m.quality.get("roe_avg3")
    roic = m.quality.get("roic_avg3")
    if roe is not None:
        word = _grade(roe, (0.0, 0.08, 0.13, 0.20),
                      ("", "negative", "low", "fair", "good", "very good"))
        sentence = (f"Return on shareholders' equity has been {word}: average ROE of "
                    f"{fmt.pct(roe)} over the recent years")
        if roic is not None:
            sentence += f", with ROIC of {fmt.pct(roic)} on invested capital"
        out.append(sentence + ".")
        if roic is not None and roic > 0.10:
            out.append("ROIC above 10% means the company creates value when it reinvests its "
                       "profits: the single most important trait for someone holding for years.")
        elif roic is not None and 0 < roic < 0.06:
            out.append("ROIC below 6% means reinvesting earns little: growth, if it comes, "
                       "creates little value for the shareholder.")

    margin_trend = m.quality.get("operating_margin_trend")
    om = m.quality.get("operating_margin_avg3")
    if om is not None:
        sentence = f"The average operating margin has been {fmt.pct(om)}"
        if margin_trend is not None:
            if margin_trend > 0.02:
                sentence += (f", improving by {fmt.num(margin_trend * 100, 1)} percentage points "
                             "over the period")
            elif margin_trend < -0.02:
                sentence += (f", deteriorating by {fmt.num(abs(margin_trend) * 100, 1)} percentage "
                             "points over the period")
            else:
                sentence += ", stable over the period"
        out.append(sentence + ".")

    positive, tot = m.growth.get("fcf_positive_years"), m.growth.get("fcf_total_years")
    if positive is not None and tot:
        if positive == tot:
            out.append("The company generated free cash flow in every year observed.")
        elif positive == 0:
            out.append("The company generated free cash flow in none of the years observed: "
                       "growth was funded with debt or fresh capital.")
        else:
            out.append(f"Free cash flow was positive in {positive} of {tot} years.")

    div = m.dividend
    if div.get("paying_years"):
        sentence = f"It paid a dividend in {div['paying_years']} of the years on record"
        growth = m.growth.get("dps_cagr") or div.get("dps_cagr")
        if growth is not None:
            sentence += f", with average dividend growth of {fmt.pct(growth, sign=True)} a year"
        if div.get("cuts"):
            sentence += f", and {div['cuts']} reductions along the way"
        out.append(sentence + ".")
    else:
        out.append("No dividend was paid over the period on record.")

    ret5, bench5 = m.trend.get("return_5y"), m.trend.get("benchmark_return_5y")
    if ret5 is not None:
        sentence = (f"Anyone who bought five years ago has earned {fmt.pct(ret5, sign=True)} "
                    "in total")
        if bench5 is not None:
            delta = ret5 - bench5
            sentence += (f", {'better' if delta > 0 else 'worse'} than the SET index "
                         f"({fmt.pct(bench5, sign=True)}), a gap of "
                         f"{fmt.num(abs(delta) * 100, 1)} percentage points")
        out.append(sentence + ".")

    drawdown = m.trend.get("max_drawdown_5y")
    if drawdown is not None:
        out.append(f"Along the way it fell as much as {fmt.pct(abs(drawdown))} from its previous "
                   "peak: that is the swing you have to be willing to sit through to stay invested.")
    return out


# --------------------------------------------------------------------------
# PRESENT
# --------------------------------------------------------------------------
def present(m: Metrics, v: Valuation) -> list[str]:
    """Where it stands now: the last twelve months, the price, the balance sheet."""
    out: list[str] = []
    cur = m.currency
    price = m.price
    if price is None:
        return ["No market price available: the current situation cannot be described."]

    sentence = f"The stock trades at {fmt.money(price, cur)}"
    if m.market_cap:
        sentence += f", a market capitalisation of {fmt.big(m.market_cap, cur)}"
    if m.trend.get("high_52w") and m.trend.get("low_52w"):
        sentence += (f". Over the past 52 weeks it has moved between {fmt.num(m.trend['low_52w'])} "
                     f"and {fmt.num(m.trend['high_52w'])} {cur}")
        if m.trend.get("from_high_52w") is not None:
            sentence += f", and today sits {fmt.pct(abs(m.trend['from_high_52w']))} below the high"
    out.append(sentence + ".")

    revenue, net = m.ttm.get("revenue"), m.ttm.get("net_income")
    if revenue:
        sentence = f"Over the last twelve months it turned over {fmt.big(revenue, cur)}"
        if net is not None:
            if net >= 0:
                sentence += (f" with net profit of {fmt.big(net, cur)} "
                             f"(a {fmt.pct(m.ttm.get('net_margin'))} margin)")
            else:
                sentence += f" and posted a loss of {fmt.big(abs(net), cur)}"
        growth = m.growth.get("revenue_ttm_vs_last_year")
        if growth is not None:
            direction = ("accelerating" if growth > 0.03
                         else "slowing" if growth < -0.03 else "in line")
            sentence += (f", {direction} against the last full financial year "
                         f"({fmt.pct(growth, sign=True)})")
        out.append(sentence + ".")

    pe = m.valuation.get("pe")
    pe_hist = m.multiple_history.get("pe") or {}
    if pe:
        sentence = f"The price is {fmt.mult(pe)} the last twelve months' earnings"
        median = pe_hist.get("median")
        percentile = pe_hist.get("percentile")
        if median:
            relation = "below" if pe < median else "above"
            sentence += (f", against a historical median of {fmt.mult(median)}: "
                         f"{fmt.pct(abs(pe / median - 1))} {relation} its own average")
            if percentile is not None:
                if percentile <= 0.25:
                    sentence += ". It has rarely been this cheap"
                elif percentile >= 0.75:
                    sentence += ". It has rarely been this expensive"
        out.append(sentence + ".")
    else:
        out.append("The P/E cannot be computed because the last twelve months' earnings are not "
                   "positive: the valuation has to be read on book value and cash flow instead.")

    extra: list[str] = []
    if m.valuation.get("pb"):
        extra.append(f"P/B {fmt.mult(m.valuation['pb'])}")
    if m.valuation.get("ev_ebitda") and not m.is_financial:
        extra.append(f"EV/EBITDA {fmt.mult(m.valuation['ev_ebitda'])}")
    if m.valuation.get("fcf_yield") is not None:
        extra.append(f"free cash flow yield {fmt.pct(m.valuation['fcf_yield'])}")
    if m.dividend.get("yield_current"):
        extra.append(f"dividend yield {fmt.pct(m.dividend['yield_current'])}")
    if extra:
        out.append("The other multiples: " + ", ".join(extra) + ".")

    nd = m.health.get("net_debt_ebitda")
    if nd is not None and not m.is_financial:
        word = _grade(nd, (0.0, 1.5, 3.0, 4.5),
                      ("", "absent, there is more cash than debt", "low", "manageable",
                       "high", "very high"))
        sentence = f"Debt is {word}: {fmt.mult(nd)} EBITDA"
        cov = m.health.get("interest_coverage")
        if cov is not None:
            sentence += f", with interest covered {fmt.mult(cov)} by operating profit"
        out.append(sentence + ".")
    elif m.is_financial and m.health.get("equity_ratio"):
        out.append("As a financial intermediary, the relevant strength measure is equity over "
                   f"total assets: {fmt.pct(m.health['equity_ratio'])}.")

    fcf = m.ttm.get("fcf")
    if fcf is not None:
        if fcf > 0:
            out.append(f"Over the last twelve months it generated {fmt.big(fcf, cur)} of free "
                       "cash flow after investment.")
        else:
            out.append(f"Over the last twelve months it burned {fmt.big(abs(fcf), cur)} of cash "
                       "after investment: a situation that has to be funded with debt or new capital.")

    vs200 = m.trend.get("vs_sma200")
    excess = m.trend.get("excess_1y")
    if vs200 is not None:
        sentence = (f"On the price side, it sits {fmt.pct(abs(vs200))} "
                    f"{'above' if vs200 > 0 else 'below'} its 200-day average")
        if excess is not None:
            sentence += (f" and over the past 12 months has done "
                         f"{'better' if excess > 0 else 'worse'} than the SET index by "
                         f"{fmt.pct(abs(excess))}")
        out.append(sentence + ".")
    return out


# --------------------------------------------------------------------------
# FUTURE
# --------------------------------------------------------------------------
def future(m: Metrics, v: Valuation, verdict: Verdict) -> list[str]:
    """What to expect over 1-2 years, with the assumptions in the open."""
    out: list[str] = []
    cur = m.currency

    growth_next = m.estimates.get("eps_growth_next_year") or m.estimates.get("growth_next_year")
    analysts = m.estimates.get("analysts")
    if growth_next is not None:
        sentence = f"Next year's earnings are expected to change by {fmt.pct(growth_next, sign=True)}"
        if analysts:
            sentence += f" (average of {int(analysts)} analysts)"
        out.append(sentence + ".")
    else:
        out.append("No analyst estimates are available for this stock, so the projections below "
                   "start from the company's own historical figures alone.")

    if v.has_fair_value and m.price:
        out.append(
            f"Crossing {len(v.usable_methods())} independent valuation methods, the estimated "
            f"value lands between {fmt.money(v.fair_bear, cur)} in the pessimistic case and "
            f"{fmt.money(v.fair_bull, cur)} in the optimistic one, with a central figure of "
            f"{fmt.money(v.fair_base, cur)}. Against today's price that is "
            f"{fmt.pct(v.upside_base, sign=True)}."
        )
        if v.expected_return_2y is not None:
            out.append(
                f"Over two years, adding the expected dividends "
                f"({fmt.pct((v.dividend_yield or 0) * 2)} cumulative), the total expected return "
                f"is {fmt.pct(v.expected_return_2y, sign=True)}, or "
                f"{fmt.pct(v.expected_annualized, sign=True)} a year."
            )
        out.append(
            f"The assumptions behind those numbers, in the open: required return "
            f"{fmt.pct(v.cost_of_equity)} (risk-free rate {fmt.pct(v.risk_free)} plus a beta of "
            f"{fmt.ratio(v.beta)} times an equity risk premium of "
            f"{fmt.pct(v.equity_risk_premium)}), perpetual growth capped at 4%, and the price "
            f"converging to the estimated value within two years. Overall reliability of the "
            f"estimate: {v.reliability}."
        )
    else:
        out.append("No valuation model applies with the data available: there is no reference "
                   "value to quote, and that alone is a reason for caution.")

    if v.analyst_target and m.price:
        out.append(f"The analysts covering the stock point to an average target of "
                   f"{fmt.money(v.analyst_target, cur)}, {fmt.pct(abs(v.analyst_upside or 0))} "
                   f"{'above' if v.analyst_target > m.price else 'below'} the current price. "
                   "That is a market reference, not an independent check.")

    drivers: list[str] = []
    if (m.growth.get("revenue_cagr") or 0) > 0.08:
        drivers.append("the revenue growth already under way")
    if (m.quality.get("roic_avg3") or 0) > 0.10:
        drivers.append("the ability to reinvest at high returns")
    if (m.dividend.get("yield_current") or 0) >= 0.04:
        drivers.append(f"the dividend ({fmt.pct(m.dividend['yield_current'])}), which pays you to wait")
    pe_percentile = (m.multiple_history.get("pe") or {}).get("percentile")
    if pe_percentile is not None and pe_percentile <= 0.30:
        drivers.append("the multiple returning towards its own historical average")
    if (m.quality.get("operating_margin_trend") or 0) > 0.02:
        drivers.append("the margin improvement in progress")
    if drivers:
        out.append("What could lift the stock over the next 1-2 years: " + "; ".join(drivers) + ".")

    risks = [flag.text.rstrip(".") for flag in verdict.grave_flags[:3]]
    risks += [flag.text.rstrip(".") for flag in verdict.warning_flags[:3]]
    if (m.trend.get("volatility") or 0) > 0.35:
        risks.append(f"annual volatility of {fmt.pct(m.trend['volatility'])}, which makes wide "
                     "swings likely even without bad news")
    if m.is_financial:
        risks.append("as a financial intermediary it is exposed to the credit cycle and to rates")
    if not risks:
        risks.append("no specific risk emerges from the data, but market risk remains, along with "
                     "currency risk for anyone investing from outside Thailand")
    out.append("What could go wrong: " + "; ".join(risks) + ".")

    out.append("A note on currency: the stock is quoted in baht. For an investor in euros or "
               "dollars the final return also depends on the exchange rate, which this analysis "
               "does not forecast.")
    return out


# --------------------------------------------------------------------------
# DIVIDENDS (ten years)
# --------------------------------------------------------------------------
def dividends(analisi) -> list[str]:
    """The dividend write-up: what it paid, whether it holds, what to expect."""
    if analisi is None or not analisi.pays_dividends:
        return ["No dividend is recorded for this stock in the sources available. If you know it "
                "does pay, you can supply the payment history in a CSV file: the app will use it "
                "instead of the APIs."]

    out: list[str] = []
    cur = analisi.currency
    complete = analisi.complete_years()
    growth, streaks = analisi.growth, analisi.streaks
    yields = analisi.yield_stats

    # --- how much it paid -------------------------------------------------
    observed = streaks.get("anni_osservati") or len(complete)
    if not complete.empty:
        total = float(complete["dps"].sum())
        first, last = int(complete.index[0]), int(complete.index[-1])
        sentence = (f"Across the complete years from {first} to {last} it distributed "
                    f"{fmt.money(total, cur)} per share in total")
        if analisi.price:
            sentence += (f", which is {fmt.pct(total / analisi.price)} of today's price "
                         "collected in dividends")
        out.append(sentence + ".")

    cadence = {1: "once a year", 2: "twice a year", 4: "every quarter"}.get(
        analisi.cadence or 0, "on an irregular schedule")
    paid = streaks.get("anni_pagati")
    skipped = streaks.get("anni_saltati") or 0
    sentence = f"It pays {cadence}"
    if paid is not None and observed:
        if skipped == 0:
            sentence += f" and has paid in all {observed} complete years observed"
        else:
            sentence += (f" and has paid in {paid} of the {observed} years observed, "
                         f"skipping {skipped}")
    out.append(sentence + ".")

    cagr10 = growth.get("cagr_10y")
    cagr5 = growth.get("cagr_5y")
    cagr3 = growth.get("cagr_3y")
    parts = [f"{label} {fmt.pct(value, sign=True)}"
             for label, value in (("over 10 years", cagr10), ("over 5", cagr5), ("over 3", cagr3))
             if value is not None]
    if parts:
        reference = cagr10 if cagr10 is not None else (cagr5 if cagr5 is not None else cagr3)
        word = _grade(reference, (-0.02, 0.005, 0.04, 0.09),
                      ("", "shrinking", "flat", "growing slowly", "growing solidly",
                       "growing strongly"))
        out.append(f"The dividend per share is {word}: average annual growth "
                   + ", ".join(parts) + ".")
    elif growth.get("irregolare"):
        out.append("Average dividend growth is not quoted: with years at zero inside the window a "
                   "compound growth rate has no meaning, and stating one would be misleading.")

    cuts = streaks.get("tagli")
    if cuts:
        worst = streaks.get("taglio_massimo")
        cut_year = streaks.get("anno_ultimo_taglio")
        sentence = f"It has reduced the dividend {cuts} time" + ("" if cuts == 1 else "s")
        if worst is not None:
            sentence += f", the deepest by {fmt.pct(abs(worst))}"
        if cut_year:
            sentence += f"; the most recent in {cut_year}"
            since = streaks.get("anni_dall_ultimo_taglio")
            if since:
                sentence += f", {since} years ago"
        out.append(sentence + ".")
    elif observed:
        out.append(f"It has never reduced the dividend in the {observed} years observed.")

    increases = streaks.get("aumenti_consecutivi")
    since_cut = streaks.get("anni_dall_ultimo_taglio")
    if increases and increases >= 3:
        if cuts and since_cut is not None and increases >= since_cut:
            # The streak starts from the post-cut low: calling it a growth
            # record would give a hurried reader the wrong impression.
            out.append(f"The last {increases} years are increases, but they start from the low "
                       "that followed the cut: this is a recovery, not yet a return to the "
                       "previous level.")
        else:
            out.append(f"That is {increases} consecutive years of increases: the kind of record "
                       "that lifts the yield on the price you paid.")

    # --- how much of the return came from dividends ------------------------
    tr = analisi.total_return
    if tr.get("totale_reinvestito") is not None and tr.get("solo_prezzo") is not None:
        years = tr.get("anni") or 10
        sentence = (f"Over {years:.0f} years the price returned "
                    f"{fmt.pct(tr['solo_prezzo'], sign=True)}, while with dividends reinvested "
                    f"the total return was {fmt.pct(tr['totale_reinvestito'], sign=True)}")
        if tr.get("annualizzato") is not None:
            sentence += f" ({fmt.pct(tr['annualizzato'], sign=True)} a year)"
        out.append(sentence + ".")
        share = tr.get("quota_dividendi")
        contribution = tr.get("contributo_dividendi")
        if contribution is not None:
            if share is not None and 0 < share <= 1:
                if share >= 0.5:
                    out.append(f"Dividends added {fmt.num(contribution * 100, 1)} percentage "
                               f"points, which is {fmt.pct(share)} of the entire return: on this "
                               "stock the payout is the main part of what you earn.")
                else:
                    out.append(f"Dividends added {fmt.num(contribution * 100, 1)} percentage "
                               f"points, {fmt.pct(share)} of the total return.")
            elif tr["solo_prezzo"] < 0:
                total = tr.get("totale_reinvestito")
                if total is not None and total < 0:
                    out.append(f"Dividends added {fmt.num(contribution * 100, 1)} percentage "
                               "points, but it was not enough: the period is still a loss even "
                               "after collecting every payment. They softened the damage rather "
                               "than avoiding it.")
                else:
                    out.append(f"Dividends added {fmt.num(contribution * 100, 1)} percentage "
                               "points and turned a period of falling prices into a positive one.")

    yoc = analisi.yield_on_cost
    if yoc.get("10y"):
        out.append(f"Anyone who bought ten years ago at {fmt.money(yoc.get('prezzo_10y'), cur)} "
                   f"now collects {fmt.pct(yoc['10y'])} on the price they paid.")
    elif yoc.get("5y"):
        out.append(f"Anyone who bought five years ago at {fmt.money(yoc.get('prezzo_5y'), cur)} "
                   f"now collects {fmt.pct(yoc['5y'])} on the price they paid.")

    # --- is today's price generous? ----------------------------------------
    current, median = yields.get("attuale"), yields.get("mediana")
    if current and median:
        percentile = yields.get("percentile")
        sentence = (f"Today the stock yields {fmt.pct(current)} (indicated dividend "
                    f"{fmt.money(yields.get('dps_indicato'), cur)}), against a historical median "
                    f"of {fmt.pct(median)}")
        if percentile is not None:
            if percentile >= 0.75:
                sentence += (f": more generous than {fmt.pct(percentile)} of the observations of "
                             "recent years, so the price is low against its own history")
            elif percentile <= 0.25:
                sentence += (f": only {fmt.pct(percentile)} of observations were lower, so the "
                             "stock is expensive against its own history")
            else:
                sentence += f", in line with the past (percentile {fmt.pct(percentile)})"
        out.append(sentence + ".")
        if yields.get("p25") and yields.get("p75"):
            out.append(f"Over the period observed the yield moved between "
                       f"{fmt.pct(yields['p25'])} and {fmt.pct(yields['p75'])} in the middle half "
                       f"of cases, with a low of {fmt.pct(yields.get('minimo'))} and a high of "
                       f"{fmt.pct(yields.get('massimo'))}.")

    # --- does the dividend hold? -------------------------------------------
    safety = analisi.safety
    if safety:
        out.append(f"Dividend safety: {fmt.num(safety.score, 0)} out of 100, verdict "
                   f"\"{safety.band}\", cut risk {safety.cut_risk_band}. The score is built from "
                   "the factors listed in the table: you can see how many points each one "
                   "contributes, and disagree with any of them.")
        heaviest = sorted(safety.factors, key=lambda f: f.points)[:2]
        negatives = [f for f in heaviest if f.points < 0]
        if negatives:
            out.append("The factors weighing most against it: "
                       + "; ".join(f"{f.label.lower()} ({f.explanation})" for f in negatives) + ".")
        positives = sorted(safety.factors, key=lambda f: -f.points)[:2]
        positives = [f for f in positives if f.points > 0]
        if positives:
            out.append("In its favour: "
                       + "; ".join(f"{f.label.lower()} ({f.explanation})" for f in positives) + ".")
        for trigger in safety.hard_triggers:
            out.append(trigger)

    # --- what will it pay? -------------------------------------------------
    forecast = analisi.forecast
    if forecast and forecast.ok:
        sentence = (f"For the next twelve months the estimate is "
                    f"{fmt.money(forecast.year1_base, cur)} per share (between "
                    f"{fmt.num(forecast.year1_low)} and {fmt.num(forecast.year1_high)}), and "
                    f"{fmt.money(forecast.year2_base, cur)} the year after")
        if analisi.price:
            sentence += (f": on today's price that is "
                         f"{fmt.pct(forecast.year1_base / analisi.price)} in the first year")
        out.append(sentence + ".")
        used = [m for m in forecast.methods if m.usable]
        if used:
            out.append(f"The estimate crosses {len(used)} method"
                       + ("" if len(used) == 1 else "s") + ": "
                       + "; ".join(f"{m.label.lower()} ({m.detail})" for m in used) + ".")
        if forecast.note:
            out.append(forecast.note)

    # --- did the signal work here? -----------------------------------------
    test = analisi.backtest
    if test and test.observations >= 24:
        high = next((b for b in test.buckets if b.label.startswith("High yield")), None)
        low = next((b for b in test.buckets if b.label.startswith("Low yield")), None)
        thin = [b for b in (high, low) if b is not None and b.observations < 6]
        if thin:
            # Comparing an average over one or two observations with one over
            # fifty is worse than not comparing at all.
            names = " and ".join(b.label.split(" (")[0].lower() for b in thin)
            out.append(f"The backtest is not conclusive: the \"{names}\" group has too few "
                       f"observations ({', '.join(str(b.observations) for b in thin)}) to be "
                       "compared. Over these ten years the stock's yield sat almost always in "
                       "the same band.")
        elif high and low and high.avg_return_2y is not None and low.avg_return_2y is not None:
            out.append(
                f"Tested on this stock's own data: on the {high.observations} occasions when the "
                f"yield was among the highest in its history, the following two years returned "
                f"{fmt.pct(high.avg_return_2y, sign=True)} on average; on the {low.observations} "
                f"occasions when it was among the lowest, "
                f"{fmt.pct(low.avg_return_2y, sign=True)}."
            )
            gap = test.separation
            if gap is not None and not thin:
                if gap > 0.10:
                    out.append(f"The gap between the two cases is {fmt.num(gap * 100, 0)} "
                               "percentage points in favour of the high yield: on this stock the "
                               "rule worked.")
                elif gap < -0.10:
                    out.append(f"The gap is {fmt.num(abs(gap) * 100, 0)} percentage points "
                               "*against* the high yield: on this stock, buying when the payout "
                               "was generous did not pay.")
                else:
                    out.append("The gap between the two cases is small: on this stock the level "
                               "of the yield did not separate the good moments from the bad ones.")
        out.append(test.note)
    elif test and test.note:
        out.append(test.note)
    return out


# --------------------------------------------------------------------------
# downloadable report
# --------------------------------------------------------------------------
def build_report(analysis) -> str:
    """The full report in markdown, ready to save, print or send."""
    m: Metrics = analysis.metrics
    v: Valuation = analysis.valuation
    d: Verdict = analysis.verdict
    cur = m.currency
    lines: list[str] = []
    add = lines.append

    add(f"# {m.name} ({m.symbol})")
    add("")
    if analysis.data.is_demo:
        add("> **SYNTHETIC DEMONSTRATION DATA** - invented company, figures are not real.")
        add("")
    add(f"**Decision: {d.headline}**")
    add("")
    add(f"- Price: {fmt.money(m.price, cur)} (latest data {fmt.date(m.trend.get('last_date'))})")
    add(f"- Overall score: {fmt.num(d.composite, 0)}/100")
    add(f"- Estimated value: {fmt.money(v.fair_bear, cur)} / **{fmt.money(v.fair_base, cur)}** / "
        f"{fmt.money(v.fair_bull, cur)} (pessimistic / base / optimistic)")
    add(f"- Expected 2-year return: {fmt.pct(d.expected_return_2y, sign=True)} "
        f"({fmt.pct(d.expected_annualized, sign=True)} a year)")
    if d.entry_price:
        add(f"- Entry price for a +20% target over 2 years: below {fmt.money(d.entry_price, cur)}")
    add(f"- Quality of the data available: {d.data_quality}")
    add("")

    div = getattr(analysis, "dividends", None)
    if div is not None and div.pays_dividends and div.signal:
        add("## Dividends: the signal")
        add("")
        add(f"**{div.signal.headline}**")
        add("")
        add(f"- Yield today: {fmt.pct(div.yield_stats.get('attuale'))} "
            f"(historical median {fmt.pct(div.yield_stats.get('mediana'))}, "
            f"percentile {fmt.pct(div.yield_stats.get('percentile'))})")
        add(f"- Dividend per share on an annual basis: "
            f"{fmt.money(div.yield_stats.get('dps_indicato'), cur)}")
        if div.forecast and div.forecast.ok:
            add(f"- Next 12 months estimate: {fmt.money(div.forecast.year1_base, cur)} "
                f"(between {fmt.num(div.forecast.year1_low)} and {fmt.num(div.forecast.year1_high)})")
        add(f"- Dividend safety: {fmt.num(div.safety.score, 0)}/100 "
            f"({div.safety.band}), cut risk {div.safety.cut_risk_band}")
        add(f"- Expected 2-year return: {fmt.pct(div.signal.expected_return_2y, sign=True)} "
            f"({fmt.pct(div.signal.income_component, sign=True)} from dividends, "
            f"{fmt.pct(div.signal.price_component, sign=True)} from the price)")
        add(f"- Buy below {fmt.money(div.signal.entry_price, cur)}, "
            f"estimated value {fmt.money(div.signal.fair_price, cur)}, "
            f"trim above {fmt.money(div.signal.exit_price, cur)}")
        add("")
        for reason in div.signal.reasons:
            add(f"- {reason}")
        add("")
        add("### Dividend safety, factor by factor")
        add("")
        add("| Factor | Value | Points | Why |")
        add("|---|---|---|---|")
        for factor in div.safety.factors:
            value = (fmt.pct(factor.value) if factor.fmt == "pct"
                     else fmt.mult(factor.value) if factor.fmt == "x"
                     else fmt.num(factor.value, 0))
            add(f"| {factor.label} | {value} | {factor.points:+.0f} | {factor.explanation} |")
        add("")
        if div.source is not None:
            add(f"*Dividend provenance: {div.source.provenance()}*")
            add("")
            for warning in div.source.disagreements:
                add(f"> {warning}")
            if div.source.disagreements:
                add("")

    add("## Why")
    add("")
    for reason in d.reasons:
        add(f"- {reason}")
    add("")
    add("## Putting it into practice")
    add("")
    add(d.position_note)
    add("")
    add("## Score by area")
    add("")
    add("| Area | Score | Question it answers |")
    add("|---|---|---|")
    for pillar in d.pillars:
        score = "n/a" if pillar.score is None else f"{pillar.score:.0f}/100"
        add(f"| {pillar.label} | {score} | {pillar.question} |")
    add("")
    for title, key in (("Ten years of dividends", "dividends"), ("Past", "past"),
                       ("Present", "present"), ("Future", "future")):
        if key not in analysis.narrative:
            continue
        add(f"## {title}")
        add("")
        for paragraph in analysis.narrative[key]:
            add(paragraph)
            add("")
    if d.flags:
        add("## Red flags")
        add("")
        for flag in d.flags:
            marker = "SERIOUS" if flag.severity == "grave" else "watch"
            add(f"- **[{marker}]** {flag.text}")
        add("")
    add("## When to revisit the decision")
    add("")
    for trigger in d.review_triggers:
        add(f"- {trigger}")
    add("")
    add("## Valuation methods used")
    add("")
    add("| Method | Value | Weight | Assumptions |")
    add("|---|---|---|---|")
    for method in v.methods:
        if method.usable:
            add(f"| {method.label} | {fmt.money(method.fair_value, cur)} | "
                f"{method.weight:.0%} | {method.detail} |")
        else:
            add(f"| {method.label} | not applicable | - | {method.skipped_reason} |")
    add("")
    limits = list(m.notes) + list(v.notes) + list(analysis.data.warnings)
    if div is not None:
        limits += list(div.notes)
    if limits:
        add("## Limits of the data")
        add("")
        for note in limits:
            add(f"- {note}")
        add("")
    add("---")
    add("")
    add("This document is an automated elaboration of public data: it is neither financial "
        "advice nor a personalised recommendation. Always check the figures against the "
        "company's official statements and the Stock Exchange of Thailand website before "
        "investing.")
    return "\n".join(lines)
