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
from setxray.lang import L, plural


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
        return [L("Yahoo Finance has no historical financial statements for this stock, so the "
                  "company's past cannot be reconstructed. The analysis below rests on the price "
                  "history alone.",
                  "Non sono disponibili bilanci storici per questo titolo su Yahoo Finance, quindi "
                  "non e' possibile ricostruire il passato dell'azienda. L'analisi che segue si "
                  "basa "
                  "solo sull'andamento del prezzo.")]

    span = m.growth.get("revenue_span") or 0
    rev_cagr = m.growth.get("revenue_cagr")
    eps_cagr = m.growth.get("eps_cagr")
    opening = L(f"Across the {len(years)} financial years available ({years[0]}-{years[-1]})",
                f"Nei {len(years)} esercizi disponibili ({years[0]}-{years[-1]})")
    if rev_cagr is None:
        out.append(L(f"{opening} revenue shows no measurable trend.",
                     f"{opening} i ricavi non mostrano una tendenza calcolabile."))
    else:
        word = _grade(rev_cagr, (-0.02, 0.02, 0.06, 0.12),
                      ("", L("falling sharply",
                             "in netto calo"), L("essentially flat",
                                                                    "sostanzialmente fermi"), L("growing modestly",
                                                                    "in crescita moderata"),
                       L("growing well",
                         "in buona crescita"), L("growing strongly",
                                                                 "in forte crescita")))
        out.append(L(f"{opening} revenue has been {word}: {fmt.pct(rev_cagr, sign=True)} a year "
                     "on average",
                     f"{opening} i ricavi sono stati {word}: {fmt.pct(rev_cagr, sign=True)} "
                     f"all'anno in media") + (L(f" over {span:.0f} years.",
                                                f" su {span:.0f} anni.") if span else "."))

    if eps_cagr is not None and rev_cagr is not None:
        if eps_cagr > rev_cagr + 0.02:
            out.append(L(f"Earnings per share grew faster than revenue "
                         f"({fmt.pct(eps_cagr, sign=True)} "
                         "a year): the company became more efficient, or reduced its share count.",
                         f"L'utile per azione e' cresciuto piu' dei ricavi "
                         f"({fmt.pct(eps_cagr, sign=True)} "
                         "all'anno): l'azienda e' diventata piu' efficiente, oppure ha ridotto il "
                         "numero "
                         "di azioni in circolazione."))
        elif eps_cagr < rev_cagr - 0.02:
            out.append(L(f"Earnings per share grew slower than revenue "
                         f"({fmt.pct(eps_cagr, sign=True)} "
                         "a year): margins compressed, or new shares were issued.",
                         f"L'utile per azione e' cresciuto meno dei ricavi "
                         f"({fmt.pct(eps_cagr, sign=True)} "
                         "all'anno): i margini si sono compressi, oppure sono state emesse nuove "
                         "azioni."))
        else:
            out.append(L(f"Earnings per share tracked revenue ({fmt.pct(eps_cagr, sign=True)} a "
                         f"year).",
                         f"L'utile per azione ha seguito i ricavi ({fmt.pct(eps_cagr, sign=True)} "
                         f"all'anno)."))

    up, total = m.growth.get("revenue_up_years"), m.growth.get("revenue_total_years")
    if up is not None and total:
        if up == total:
            out.append(L("Revenue grew in every year of the period: a steady path.",
                         "I ricavi sono cresciuti in ogni esercizio del periodo: un percorso "
                         "regolare."))
        elif up == 0:
            out.append(L("Revenue did not grow in any of the years observed.",
                         "I ricavi non sono cresciuti in nessuno degli esercizi osservati."))
        else:
            out.append(L(f"Growth was uneven: {up} years up out of {total}.",
                         f"La crescita e' stata discontinua: {up} esercizi in aumento su {total}."))

    roe = m.quality.get("roe_avg3")
    roic = m.quality.get("roic_avg3")
    if roe is not None:
        word = _grade(roe, (0.0, 0.08, 0.13, 0.20),
                      ("", L("negative",
                             "negativa"), L("low",
                                                        "bassa"), L("fair",
                                                                           "discreta"), L("good",
                                                                                                  "buona"), L("very good",
                                                                                                                      "molto buona")))
        sentence = (L(f"Return on shareholders' equity has been {word}: average ROE of "
                      f"{fmt.pct(roe)} over the recent years",
                      f"La redditivita' del capitale proprio e' stata {word}: ROE medio "
                      f"{fmt.pct(roe)} "
                      "negli ultimi esercizi"))
        if roic is not None:
            sentence += L(f", with ROIC of {fmt.pct(roic)} on invested capital",
                          f", ROIC {fmt.pct(roic)} sul capitale investito")
        out.append(sentence + ".")
        if roic is not None and roic > 0.10:
            out.append(L("ROIC above 10% means the company creates value when it reinvests its "
                         "profits: the single most important trait for someone holding for years.",
                         "Un ROIC sopra il 10% indica che l'azienda crea valore quando reinveste "
                         "gli "
                         "utili: e' la caratteristica che conta di piu' per chi resta investito "
                         "anni."))
        elif roic is not None and 0 < roic < 0.06:
            out.append(L("ROIC below 6% means reinvesting earns little: growth, if it comes, "
                         "creates little value for the shareholder.",
                         "Un ROIC sotto il 6% significa che reinvestire rende poco: la crescita, "
                         "se "
                         "arriva, non crea molto valore per l'azionista."))

    margin_trend = m.quality.get("operating_margin_trend")
    om = m.quality.get("operating_margin_avg3")
    if om is not None:
        sentence = L(f"The average operating margin has been {fmt.pct(om)}",
                     f"Il margine operativo medio e' stato {fmt.pct(om)}")
        if margin_trend is not None:
            if margin_trend > 0.02:
                sentence += (L(f", improving by {fmt.num(margin_trend * 100, 1)} percentage points "
                               "over the period",
                               f", in miglioramento di {fmt.num(margin_trend * 100, 1)} punti "
                               "percentuali nel periodo"))
            elif margin_trend < -0.02:
                sentence += (L(f", deteriorating by {fmt.num(abs(margin_trend) * 100, 1)} "
                               f"percentage "
                               "points over the period",
                               f", in peggioramento di {fmt.num(abs(margin_trend) * 100, 1)} punti "
                               "percentuali nel periodo"))
            else:
                sentence += L(", stable over the period", ", stabile nel periodo")
        out.append(sentence + ".")

    positive, tot = m.growth.get("fcf_positive_years"), m.growth.get("fcf_total_years")
    if positive is not None and tot:
        if positive == tot:
            out.append(L("The company generated free cash flow in every year observed.",
                         "L'azienda ha generato cassa libera in tutti gli esercizi osservati."))
        elif positive == 0:
            out.append(L("The company generated free cash flow in none of the years observed: "
                         "growth was funded with debt or fresh capital.",
                         "L'azienda non ha generato cassa libera in nessuno degli esercizi "
                         "osservati: "
                         "la crescita e' stata finanziata con debito o capitale nuovo."))
        else:
            out.append(L(f"Free cash flow was positive in {positive} of {tot} years.",
                         f"La cassa libera e' stata positiva in {positive} esercizi su {tot}."))

    div = m.dividend
    if div.get("paying_years"):
        sentence = L(f"It paid a dividend in {div['paying_years']} of the years on record",
                     f"Ha distribuito dividendi in {div['paying_years']} degli anni rilevati")
        growth = m.growth.get("dps_cagr") or div.get("dps_cagr")
        if growth is not None:
            sentence += L(f", with average dividend growth of {fmt.pct(growth, sign=True)} a year",
                          f", con una crescita media del dividendo di {fmt.pct(growth, sign=True)} "
                          f"all'anno")
        if div.get("cuts"):
            sentence += L(f", and {div['cuts']} reductions along the way",
                          f", e {div['cuts']} riduzioni lungo il percorso")
        out.append(sentence + ".")
    else:
        out.append(L("No dividend was paid over the period on record.",
                     "Non risultano dividendi distribuiti nel periodo rilevato."))

    ret5, bench5 = m.trend.get("return_5y"), m.trend.get("benchmark_return_5y")
    if ret5 is not None:
        sentence = (L(f"Anyone who bought five years ago has earned {fmt.pct(ret5, sign=True)} "
                      "in total",
                      f"Per chi lo ha comprato cinque anni fa il titolo ha reso "
                      f"{fmt.pct(ret5, sign=True)} complessivi"))
        if bench5 is not None:
            delta = ret5 - bench5
            sentence += (L(f", {'better' if delta > 0 else 'worse'} than the SET index "
                           f"({fmt.pct(bench5, sign=True)}), a gap of "
                           f"{fmt.num(abs(delta) * 100, 1)} percentage points",
                           f", {'meglio' if delta > 0 else 'peggio'} dell'indice SET "
                           f"({fmt.pct(bench5, sign=True)}), con uno scarto di "
                           f"{fmt.num(abs(delta) * 100, 1)} punti percentuali"))
        out.append(sentence + ".")

    drawdown = m.trend.get("max_drawdown_5y")
    if drawdown is not None:
        out.append(L(f"Along the way it fell as much as {fmt.pct(abs(drawdown))} from its previous "
                     "peak: that is the swing you have to be willing to sit through to stay "
                     "invested.",
                     f"Lungo il percorso ha perso fino al {fmt.pct(abs(drawdown))} dal massimo "
                     f"precedente: "
                     "e' l'oscillazione che bisogna essere disposti a sopportare per restare "
                     "investiti."))
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
        return [L("No market price available: the current situation cannot be described.",
                  "Prezzo di mercato non disponibile: impossibile descrivere la situazione attuale.")]

    sentence = L(f"The stock trades at {fmt.money(price, cur)}",
                 f"Il titolo tratta a {fmt.money(price, cur)}")
    if m.market_cap:
        sentence += L(f", a market capitalisation of {fmt.big(m.market_cap, cur)}",
                      f", per una capitalizzazione di {fmt.big(m.market_cap, cur)}")
    if m.trend.get("high_52w") and m.trend.get("low_52w"):
        sentence += (L(f". Over the past 52 weeks it has moved between "
                       f"{fmt.num(m.trend['low_52w'])} "
                       f"and {fmt.num(m.trend['high_52w'])} {cur}",
                       f". Nelle ultime 52 settimane si e' mosso fra {fmt.num(m.trend['low_52w'])} "
                       f"e "
                       f"{fmt.num(m.trend['high_52w'])} {cur}"))
        if m.trend.get("from_high_52w") is not None:
            sentence += L(f", and today sits {fmt.pct(abs(m.trend['from_high_52w']))} below the "
                          f"high",
                          f", oggi e' {fmt.pct(abs(m.trend['from_high_52w']))} sotto il massimo")
    out.append(sentence + ".")

    revenue, net = m.ttm.get("revenue"), m.ttm.get("net_income")
    if revenue:
        sentence = L(f"Over the last twelve months it turned over {fmt.big(revenue, cur)}",
                     f"Negli ultimi dodici mesi ha fatturato {fmt.big(revenue, cur)}")
        if net is not None:
            if net >= 0:
                sentence += (L(f" with net profit of {fmt.big(net, cur)} "
                               f"(a {fmt.pct(m.ttm.get('net_margin'))} margin)",
                               f" con un utile netto di {fmt.big(net, cur)} "
                               f"(margine {fmt.pct(m.ttm.get('net_margin'))})"))
            else:
                sentence += L(f" and posted a loss of {fmt.big(abs(net), cur)}",
                              f" chiudendo in perdita di {fmt.big(abs(net), cur)}")
        growth = m.growth.get("revenue_ttm_vs_last_year")
        if growth is not None:
            direction = (L("accelerating", "in accelerazione") if growth > 0.03
                         else L("slowing",
                                "in rallentamento") if growth < -0.03 else L("in line",
                                                                                        "in linea"))
            sentence += (L(f", {direction} against the last full financial year "
                           f"({fmt.pct(growth, sign=True)})",
                           f", {direction} rispetto all'ultimo bilancio annuale "
                           f"({fmt.pct(growth, sign=True)})"))
        out.append(sentence + ".")

    pe = m.valuation.get("pe")
    pe_hist = m.multiple_history.get("pe") or {}
    if pe:
        sentence = L(f"The price is {fmt.mult(pe)} the last twelve months' earnings",
                     f"Il prezzo vale {fmt.mult(pe)} gli utili degli ultimi dodici mesi")
        median = pe_hist.get("median")
        percentile = pe_hist.get("percentile")
        if median:
            relation = L("below", "sotto") if pe < median else L("above", "sopra")
            sentence += (L(f", against a historical median of {fmt.mult(median)}: "
                           f"{fmt.pct(abs(pe / median - 1))} {relation} its own average",
                           f", contro una mediana storica di {fmt.mult(median)}: quindi "
                           f"{fmt.pct(abs(pe / median - 1))} {relation} la propria media"))
            if percentile is not None:
                if percentile <= 0.25:
                    sentence += L(". It has rarely been this cheap",
                                  ". Raramente e' stato cosi' economico")
                elif percentile >= 0.75:
                    sentence += L(". It has rarely been this expensive",
                                  ". Raramente e' stato cosi' caro")
        out.append(sentence + ".")
    else:
        out.append(L("The P/E cannot be computed because the last twelve months' earnings are not "
                     "positive: the valuation has to be read on book value and cash flow instead.",
                     "Il P/E non e' calcolabile perche' gli utili degli ultimi dodici mesi non "
                     "sono "
                     "positivi: la valutazione va letta sul patrimonio e sui flussi di cassa."))

    extra: list[str] = []
    if m.valuation.get("pb"):
        extra.append(f"P/B {fmt.mult(m.valuation['pb'])}")
    if m.valuation.get("ev_ebitda") and not m.is_financial:
        extra.append(f"EV/EBITDA {fmt.mult(m.valuation['ev_ebitda'])}")
    if m.valuation.get("fcf_yield") is not None:
        extra.append(L(f"free cash flow yield {fmt.pct(m.valuation['fcf_yield'])}",
                       f"rendimento della cassa libera {fmt.pct(m.valuation['fcf_yield'])}"))
    if m.dividend.get("yield_current"):
        extra.append(L(f"dividend yield {fmt.pct(m.dividend['yield_current'])}",
                       f"dividendo {fmt.pct(m.dividend['yield_current'])}"))
    if extra:
        out.append(L("The other multiples: ", "Gli altri multipli: ") + ", ".join(extra) + ".")

    nd = m.health.get("net_debt_ebitda")
    if nd is not None and not m.is_financial:
        word = _grade(nd, (0.0, 1.5, 3.0, 4.5),
                      ("", L("absent, there is more cash than debt",
                             "assente, c'e' piu' cassa che debito"), L("low",
                                                                       "basso"), L("manageable",
                                                                            "gestibile"),
                       L("high", "elevato"), L("very high", "molto elevato")))
        sentence = L(f"Debt is {word}: {fmt.mult(nd)} EBITDA",
                     f"Il debito e' {word}: {fmt.mult(nd)} l'EBITDA")
        cov = m.health.get("interest_coverage")
        if cov is not None:
            sentence += L(f", with interest covered {fmt.mult(cov)} by operating profit",
                          f", con gli interessi coperti {fmt.mult(cov)} dall'utile operativo")
        out.append(sentence + ".")
    elif m.is_financial and m.health.get("equity_ratio"):
        out.append(L("As a financial intermediary, the relevant strength measure is equity over "
                     f"total assets: {fmt.pct(m.health['equity_ratio'])}.",
                     "Come intermediario finanziario, il dato di solidita' rilevante e' il "
                     "patrimonio "
                     f"sull'attivo totale: {fmt.pct(m.health['equity_ratio'])}."))

    fcf = m.ttm.get("fcf")
    if fcf is not None:
        if fcf > 0:
            out.append(L(f"Over the last twelve months it generated {fmt.big(fcf, cur)} of free "
                         "cash flow after investment.",
                         f"Negli ultimi dodici mesi ha generato {fmt.big(fcf, cur)} di cassa "
                         f"libera "
                         "dopo gli investimenti."))
        else:
            out.append(L(f"Over the last twelve months it burned {fmt.big(abs(fcf), cur)} of cash "
                         "after investment: a situation that has to be funded with debt or new "
                         "capital.",
                         f"Negli ultimi dodici mesi ha bruciato {fmt.big(abs(fcf), cur)} di cassa "
                         f"dopo "
                         "gli investimenti: una situazione che va finanziata con debito o capitale "
                         "nuovo."))

    vs200 = m.trend.get("vs_sma200")
    excess = m.trend.get("excess_1y")
    if vs200 is not None:
        sentence = (L(f"On the price side, it sits {fmt.pct(abs(vs200))} "
                      f"{'above' if vs200 > 0 else 'below'} its 200-day average",
                      f"Sul fronte del prezzo, oggi e' {fmt.pct(abs(vs200))} "
                      f"{'sopra' if vs200 > 0 else 'sotto'} la media degli ultimi 200 giorni"))
        if excess is not None:
            sentence += (L(f" and over the past 12 months has done "
                           f"{'better' if excess > 0 else 'worse'} than the SET index by "
                           f"{fmt.pct(abs(excess))}",
                           f" e negli ultimi 12 mesi ha fatto "
                           f"{'meglio' if excess > 0 else 'peggio'} "
                           f"dell'indice SET di {fmt.pct(abs(excess))}"))
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
        sentence = L(f"Next year's earnings are expected to change by "
                     f"{fmt.pct(growth_next, sign=True)}",
                     f"Le attese sull'utile del prossimo esercizio sono di "
                     f"{fmt.pct(growth_next, sign=True)}")
        if analysts:
            sentence += L(f" (average of {int(analysts)} analysts)",
                          f" (media di {int(analysts)} analisti)")
        out.append(sentence + ".")
    else:
        out.append(L("No analyst estimates are available for this stock, so the projections below "
                     "start from the company's own historical figures alone.",
                     "Nessuna stima di analisti disponibile per questo titolo: le proiezioni che "
                     "seguono "
                     "partono dai soli dati storici dell'azienda."))

    if v.has_fair_value and m.price:
        out.append(
            L(f"Crossing {len(v.usable_methods())} independent valuation methods, the estimated "
              f"value lands between {fmt.money(v.fair_bear, cur)} in the pessimistic case and "
              f"{fmt.money(v.fair_bull, cur)} in the optimistic one, with a central figure of "
              f"{fmt.money(v.fair_base, cur)}. Against today's price that is "
              f"{fmt.pct(v.upside_base, sign=True)}.",
              f"Incrociando {len(v.usable_methods())} metodi di valutazione indipendenti, il "
              f"valore "
              f"stimato si colloca fra {fmt.money(v.fair_bear, cur)} nello scenario pessimistico e "
              f"{fmt.money(v.fair_bull, cur)} in quello ottimistico, con un valore centrale di "
              f"{fmt.money(v.fair_base, cur)}. Rispetto al prezzo di oggi significa "
              f"{fmt.pct(v.upside_base, sign=True)}.")
        )
        if v.expected_return_2y is not None:
            out.append(
                L(f"Over two years, adding the expected dividends "
                  f"({fmt.pct((v.dividend_yield or 0) * 2)} cumulative), the total expected return "
                  f"is {fmt.pct(v.expected_return_2y, sign=True)}, or "
                  f"{fmt.pct(v.expected_annualized, sign=True)} a year.",
                  f"Su due anni, aggiungendo i dividendi attesi "
                  f"({fmt.pct((v.dividend_yield or 0) * 2)} "
                  f"cumulati), il rendimento complessivo atteso e' "
                  f"{fmt.pct(v.expected_return_2y, sign=True)}, "
                  f"cioe' {fmt.pct(v.expected_annualized, sign=True)} all'anno.")
            )
        out.append(
            L(f"The assumptions behind those numbers, in the open: required return "
              f"{fmt.pct(v.cost_of_equity)} (risk-free rate {fmt.pct(v.risk_free)} plus a beta of "
              f"{fmt.ratio(v.beta)} times an equity risk premium of "
              f"{fmt.pct(v.equity_risk_premium)}), perpetual growth capped at 4%, and the price "
              f"converging to the estimated value within two years. Overall reliability of the "
              f"estimate: {v.reliability}.",
              f"Le ipotesi dietro questi numeri, in chiaro: rendimento richiesto "
              f"{fmt.pct(v.cost_of_equity)} "
              f"(tasso privo di rischio {fmt.pct(v.risk_free)} piu' beta {fmt.ratio(v.beta)} per "
              f"il premio "
              f"al rischio {fmt.pct(v.equity_risk_premium)}), crescita perpetua non oltre il 4%, "
              f"convergenza del prezzo al valore stimato entro due anni. Affidabilita' complessiva "
              f"della stima: {v.reliability}.")
        )
    else:
        out.append(L("No valuation model applies with the data available: there is no reference "
                     "value to quote, and that alone is a reason for caution.",
                     "Nessun modello di valutazione e' applicabile con i dati disponibili: non e' "
                     "possibile indicare un valore di riferimento, e questo da solo e' un motivo "
                     "di prudenza."))

    if v.analyst_target and m.price:
        out.append(L(f"The analysts covering the stock point to an average target of "
                     f"{fmt.money(v.analyst_target, cur)}, {fmt.pct(abs(v.analyst_upside or 0))} "
                     f"{'above' if v.analyst_target > m.price else 'below'} the current price. "
                     "That is a market reference, not an independent check.",
                     f"Gli analisti che coprono il titolo indicano un obiettivo medio di "
                     f"{fmt.money(v.analyst_target, cur)}, {fmt.pct(abs(v.analyst_upside or 0))} "
                     f"{'sopra' if v.analyst_target > m.price else 'sotto'} il prezzo attuale. "
                     "E' un riferimento di mercato, non una verifica indipendente."))

    drivers: list[str] = []
    if (m.growth.get("revenue_cagr") or 0) > 0.08:
        drivers.append(L("the revenue growth already under way",
                         "la crescita dei ricavi gia' in atto"))
    if (m.quality.get("roic_avg3") or 0) > 0.10:
        drivers.append(L("the ability to reinvest at high returns",
                         "la capacita' di reinvestire con rendimenti alti"))
    if (m.dividend.get("yield_current") or 0) >= 0.04:
        drivers.append(L(f"the dividend ({fmt.pct(m.dividend['yield_current'])}), which pays you "
                         f"to wait",
                         f"il dividendo ({fmt.pct(m.dividend['yield_current'])}), che paga l'attesa"))
    pe_percentile = (m.multiple_history.get("pe") or {}).get("percentile")
    if pe_percentile is not None and pe_percentile <= 0.30:
        drivers.append(L("the multiple returning towards its own historical average",
                         "il ritorno del multiplo verso la propria media storica"))
    if (m.quality.get("operating_margin_trend") or 0) > 0.02:
        drivers.append(L("the margin improvement in progress",
                         "il miglioramento dei margini in corso"))
    if drivers:
        out.append(L("What could lift the stock over the next 1-2 years: ",
                     "Cosa puo' far salire il titolo nei prossimi 1-2 anni: ") + "; ".join(drivers) + ".")

    risks = [flag.text.rstrip(".") for flag in verdict.grave_flags[:3]]
    risks += [flag.text.rstrip(".") for flag in verdict.warning_flags[:3]]
    if (m.trend.get("volatility") or 0) > 0.35:
        risks.append(L(f"annual volatility of {fmt.pct(m.trend['volatility'])}, which makes wide "
                       "swings likely even without bad news",
                       f"volatilita' annua del {fmt.pct(m.trend['volatility'])}, che rende "
                       f"probabili "
                       "oscillazioni ampie anche senza cattive notizie"))
    if m.is_financial:
        risks.append(L("as a financial intermediary it is exposed to the credit cycle and to rates",
                       "come intermediario finanziario e' esposto al ciclo del credito e ai tassi"))
    if not risks:
        risks.append(L("no specific risk emerges from the data, but market risk remains, along "
                       "with "
                       "currency risk for anyone investing from outside Thailand",
                       "dai dati non emerge un rischio specifico, ma restano il rischio di mercato "
                       "e "
                       "quello di cambio per chi investe dall'Europa"))
    out.append(L("What could go wrong: ", "Cosa puo' andare storto: ") + "; ".join(risks) + ".")

    out.append(L("A note on currency: the stock is quoted in baht. For an investor in euros or "
                 "dollars the final return also depends on the exchange rate, which this analysis "
                 "does not forecast.",
                 "Nota sul cambio: il titolo e' quotato in baht. Per un investitore in euro il "
                 "rendimento finale dipende anche dal cambio EUR/THB, che questa analisi non "
                 "prevede."))
    return out


# --------------------------------------------------------------------------
# DIVIDENDS (ten years)
# --------------------------------------------------------------------------
def dividends(analisi) -> list[str]:
    """The dividend write-up: what it paid, whether it holds, what to expect."""
    if analisi is None or not analisi.pays_dividends:
        return [L("No dividend is recorded for this stock in the sources available. If you know it "
                  "does pay, you can supply the payment history in a CSV file: the app will use it "
                  "instead of the APIs.",
                  "Nessun dividendo risulta distribuito da questo titolo nelle fonti "
                  "disponibili. Se sai che distribuisce, puoi fornire la storia degli "
                  "stacchi in un file CSV: l'app la usa al posto delle API.")]

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
        sentence = (L(f"Across the complete years from {first} to {last} it distributed "
                      f"{fmt.money(total, cur)} per share in total",
                      f"Negli anni completi dal {first} al {last} ha distribuito "
                      f"{fmt.money(total, cur)} per azione in totale"))
        if analisi.price:
            sentence += (L(f", which is {fmt.pct(total / analisi.price)} of today's price "
                           "collected in dividends",
                           f", cioe' il {fmt.pct(total / analisi.price)} del prezzo di oggi "
                           "incassato in cedole"))
        out.append(sentence + ".")

    cadence = {1: L("once a year",
                    "una volta l'anno"), 2: L("twice a year",
                                                             "due volte l'anno"), 4: L("every quarter",
                                                                                                       "ogni trimestre")}.get(
        analisi.cadence or 0, L("on an irregular schedule", "con cadenza variabile"))
    paid = streaks.get("anni_pagati")
    skipped = streaks.get("anni_saltati") or 0
    sentence = L(f"It pays {cadence}", f"Paga {cadence}")
    if paid is not None and observed:
        if skipped == 0:
            sentence += L(f" and has paid in all {observed} complete years observed",
                          f" e ha pagato in tutti i {observed} anni completi osservati")
        else:
            sentence += (L(f" and has paid in {paid} of the {observed} years observed, "
                           f"skipping {skipped}",
                           f" e ha pagato in {paid} dei {observed} anni osservati, "
                           f"saltandone {skipped}"))
    out.append(sentence + ".")

    cagr10 = growth.get("cagr_10y")
    cagr5 = growth.get("cagr_5y")
    cagr3 = growth.get("cagr_3y")
    parts = [L(f"{label} {fmt.pct(value, sign=True)}",
               f"{label} {fmt.pct(value, sign=True)}")
             for label, value in ((L("over 10 years",
                                     "su 10 anni"), cagr10), (L("over 5",
                                                                                 "su 5"), cagr5), (L("over 3",
                                                                                   "su 3"), cagr3))
             if value is not None]
    if parts:
        reference = cagr10 if cagr10 is not None else (cagr5 if cagr5 is not None else cagr3)
        word = _grade(reference, (-0.02, 0.005, 0.04, 0.09),
                      ("", L("shrinking",
                             "in riduzione"), L("flat",
                                                             "fermo"), L("growing slowly",
                                                                                 "in crescita lenta"), L("growing solidly",
                                                                    "in crescita solida"),
                       L("growing strongly", "in forte crescita")))
        out.append(L(f"The dividend per share is {word}: average annual growth ",
                     f"Il dividendo per azione e' {word}: crescita media annua ")
                   + ", ".join(parts) + ".")
    elif growth.get("irregolare"):
        out.append(L("Average dividend growth is not quoted: with years at zero inside the window "
                      "a compound growth rate has no meaning, and stating one would be misleading.",
                      "La crescita media del dividendo non viene indicata: con anni a zero dentro "
                      "la "
                      "finestra un tasso composto non significa niente, e dichiararlo sarebbe "
                      "fuorviante."))

    cuts = streaks.get("tagli")
    if cuts:
        worst = streaks.get("taglio_massimo")
        cut_year = streaks.get("anno_ultimo_taglio")
        sentence = L(f"It has reduced the dividend {cuts} {plural(cuts, 'time', 'times')}",
                     f"Ha ridotto il dividendo {cuts} {plural(cuts, 'volta', 'volte')}")
        if worst is not None:
            sentence += L(f", the deepest by {fmt.pct(abs(worst))}",
                          f", con un taglio massimo del {fmt.pct(abs(worst))}")
        if cut_year:
            sentence += L(f"; the most recent in {cut_year}", f"; l'ultimo nel {cut_year}")
            since = streaks.get("anni_dall_ultimo_taglio")
            if since:
                sentence += L(f", {since} years ago", f", {since} anni fa")
        out.append(sentence + ".")
    elif observed:
        out.append(L(f"It has never reduced the dividend in the {observed} years observed.",
                     f"Non ha mai ridotto il dividendo nei {observed} anni osservati."))

    increases = streaks.get("aumenti_consecutivi")
    since_cut = streaks.get("anni_dall_ultimo_taglio")
    if increases and increases >= 3:
        if cuts and since_cut is not None and increases >= since_cut:
            # The streak starts from the post-cut low: calling it a growth
            # record would give a hurried reader the wrong impression.
            out.append(L(f"The last {increases} years are increases, but they start from the low "
                         "that followed the cut: this is a recovery, not yet a return to the "
                         "previous level.",
                         f"Gli ultimi {increases} anni sono di aumento, ma partono dal minimo "
                         "successivo al taglio: e' una risalita, non ancora un ritorno ai "
                         "livelli precedenti."))
        else:
            out.append(L(f"That is {increases} consecutive years of increases: the kind of record "
                         "that lifts the yield on the price you paid.",
                         f"Sono {increases} anni consecutivi di aumento: e' il tipo di percorso "
                         "che fa crescere il rendimento sul prezzo pagato."))

    # --- how much of the return came from dividends ------------------------
    tr = analisi.total_return
    if tr.get("totale_reinvestito") is not None and tr.get("solo_prezzo") is not None:
        years = tr.get("anni") or 10
        sentence = (L(f"Over {years:.0f} years the price returned "
                      f"{fmt.pct(tr['solo_prezzo'], sign=True)}, while with dividends reinvested "
                      f"the total return was {fmt.pct(tr['totale_reinvestito'], sign=True)}",
                      f"In {years:.0f} anni il prezzo ha fatto "
                      f"{fmt.pct(tr['solo_prezzo'], sign=True)}, "
                      f"mentre con i dividendi reinvestiti il rendimento totale e' stato "
                      f"{fmt.pct(tr['totale_reinvestito'], sign=True)}"))
        if tr.get("annualizzato") is not None:
            sentence += L(f" ({fmt.pct(tr['annualizzato'], sign=True)} a year)",
                          f" ({fmt.pct(tr['annualizzato'], sign=True)} all'anno)")
        out.append(sentence + ".")
        share = tr.get("quota_dividendi")
        contribution = tr.get("contributo_dividendi")
        if contribution is not None:
            if share is not None and 0 < share <= 1:
                if share >= 0.5:
                    out.append(L(f"Dividends added {fmt.num(contribution * 100, 1)} percentage "
                                 f"points, which is {fmt.pct(share)} of the entire return: on this "
                                 "stock the payout is the main part of what you earn.",
                                 f"I dividendi hanno aggiunto {fmt.num(contribution * 100, 1)} "
                                 f"punti "
                                 f"percentuali, cioe' il {fmt.pct(share)} di tutto il rendimento: "
                                 "su questo titolo la cedola e' la parte principale del ritorno."))
                else:
                    out.append(L(f"Dividends added {fmt.num(contribution * 100, 1)} percentage "
                                 f"points, {fmt.pct(share)} of the total return.",
                                 f"I dividendi hanno aggiunto {fmt.num(contribution * 100, 1)} "
                                 f"punti "
                                 f"percentuali, il {fmt.pct(share)} del rendimento totale."))
            elif tr["solo_prezzo"] < 0:
                total = tr.get("totale_reinvestito")
                if total is not None and total < 0:
                    out.append(L(f"Dividends added {fmt.num(contribution * 100, 1)} percentage "
                                 "points, but it was not enough: the period is still a loss even "
                                 "after collecting every payment. They softened the damage rather "
                                 "than avoiding it.",
                                 f"I dividendi hanno aggiunto {fmt.num(contribution * 100, 1)} "
                                 f"punti "
                                 "percentuali, ma non sono bastati: il periodo resta in perdita "
                                 "anche incassando tutte le cedole. Hanno attenuato il danno, "
                                 "non evitato."))
                else:
                    out.append(L(f"Dividends added {fmt.num(contribution * 100, 1)} percentage "
                                 "points and turned a period of falling prices into a positive one.",
                                 f"I dividendi hanno aggiunto {fmt.num(contribution * 100, 1)} "
                                 f"punti "
                                 "percentuali e hanno ribaltato in positivo un periodo in cui il "
                                 "prezzo e' sceso."))

    yoc = analisi.yield_on_cost
    if yoc.get("10y"):
        out.append(L(f"Anyone who bought ten years ago at {fmt.money(yoc.get('prezzo_10y'), cur)} "
                     f"now collects {fmt.pct(yoc['10y'])} on the price they paid.",
                     f"Chi lo ha comprato dieci anni fa a {fmt.money(yoc.get('prezzo_10y'), cur)} "
                     f"oggi incassa un {fmt.pct(yoc['10y'])} sul prezzo pagato."))
    elif yoc.get("5y"):
        out.append(L(f"Anyone who bought five years ago at {fmt.money(yoc.get('prezzo_5y'), cur)} "
                     f"now collects {fmt.pct(yoc['5y'])} on the price they paid.",
                     f"Chi lo ha comprato cinque anni fa a {fmt.money(yoc.get('prezzo_5y'), cur)} "
                     f"oggi incassa un {fmt.pct(yoc['5y'])} sul prezzo pagato."))

    # --- is today's price generous? ----------------------------------------
    current, median = yields.get("attuale"), yields.get("mediana")
    if current and median:
        percentile = yields.get("percentile")
        sentence = (L(f"Today the stock yields {fmt.pct(current)} (indicated dividend "
                      f"{fmt.money(yields.get('dps_indicato'), cur)}), against a historical median "
                      f"of {fmt.pct(median)}",
                      f"Oggi il titolo rende {fmt.pct(current)} (dividendo indicato "
                      f"{fmt.money(yields.get('dps_indicato'), cur)}), contro una mediana storica "
                      f"di {fmt.pct(median)}"))
        if percentile is not None:
            if percentile >= 0.75:
                sentence += (L(f": more generous than {fmt.pct(percentile)} of the observations of "
                               "recent years, so the price is low against its own history",
                               f": e' piu' generoso del {fmt.pct(percentile)} delle osservazioni "
                               f"degli "
                               "ultimi anni, quindi il prezzo e' basso rispetto alla sua storia"))
            elif percentile <= 0.25:
                sentence += (L(f": only {fmt.pct(percentile)} of observations were lower, so the "
                               "stock is expensive against its own history",
                               f": solo il {fmt.pct(percentile)} delle osservazioni e' stato piu' "
                               f"basso, "
                               "quindi il titolo e' caro rispetto alla sua storia"))
            else:
                sentence += L(f", in line with the past (percentile {fmt.pct(percentile)})",
                              f", in linea con il passato (percentile {fmt.pct(percentile)})")
        out.append(sentence + ".")
        if yields.get("p25") and yields.get("p75"):
            out.append(L(f"Over the period observed the yield moved between "
                         f"{fmt.pct(yields['p25'])} and {fmt.pct(yields['p75'])} in the middle "
                         f"half "
                         f"of cases, with a low of {fmt.pct(yields.get('minimo'))} and a high of "
                         f"{fmt.pct(yields.get('massimo'))}.",
                         f"Nel periodo osservato il rendimento si e' mosso fra "
                         f"{fmt.pct(yields['p25'])} e {fmt.pct(yields['p75'])} nella meta' "
                         f"centrale dei casi, con un minimo di {fmt.pct(yields.get('minimo'))} "
                         f"e un massimo di {fmt.pct(yields.get('massimo'))}."))

    # --- does the dividend hold? -------------------------------------------
    safety = analisi.safety
    if safety:
        out.append(L(f"Dividend safety: {fmt.num(safety.score, 0)} out of 100, verdict "
                     f"\"{safety.band}\", cut risk {safety.cut_risk_band}. The score is built from "
                     "the factors listed in the table: you can see how many points each one "
                     "contributes, and disagree with any of them.",
                     f"Solidita' del dividendo: {fmt.num(safety.score, 0)} su 100, "
                     f"giudizio \"{safety.band}\", rischio di taglio {safety.cut_risk_band}. "
                     "Il punteggio nasce dai fattori elencati nella tabella: puoi vedere quanti "
                     "punti porta ognuno e non essere d'accordo su uno di essi."))
        heaviest = sorted(safety.factors, key=lambda f: f.points)[:2]
        negatives = [f for f in heaviest if f.points < 0]
        if negatives:
            out.append(L("The factors weighing most against it: ",
                         "I fattori che pesano di piu' in negativo: ")
                       + "; ".join(f"{f.label.lower()} ({f.explanation})" for f in negatives) + ".")
        positives = sorted(safety.factors, key=lambda f: -f.points)[:2]
        positives = [f for f in positives if f.points > 0]
        if positives:
            out.append(L("In its favour: ", "A favore: ")
                       + "; ".join(f"{f.label.lower()} ({f.explanation})" for f in positives) + ".")
        for trigger in safety.hard_triggers:
            out.append(trigger)

    # --- what will it pay? -------------------------------------------------
    forecast = analisi.forecast
    if forecast and forecast.ok:
        sentence = (L(f"For the next twelve months the estimate is "
                      f"{fmt.money(forecast.year1_base, cur)} per share (between "
                      f"{fmt.num(forecast.year1_low)} and {fmt.num(forecast.year1_high)}), and "
                      f"{fmt.money(forecast.year2_base, cur)} the year after",
                      f"Per i prossimi dodici mesi la stima e' "
                      f"{fmt.money(forecast.year1_base, cur)} "
                      f"per azione (fra {fmt.num(forecast.year1_low)} e "
                      f"{fmt.num(forecast.year1_high)}), e {fmt.money(forecast.year2_base, cur)} "
                      "l'anno successivo"))
        if analisi.price:
            sentence += (L(f": on today's price that is "
                           f"{fmt.pct(forecast.year1_base / analisi.price)} in the first year",
                           f": sul prezzo di oggi sono "
                           f"{fmt.pct(forecast.year1_base / analisi.price)} "
                           "il primo anno"))
        out.append(sentence + ".")
        used = [m for m in forecast.methods if m.usable]
        if used:
            quanti = len(used)
            out.append(L(f"The estimate crosses {quanti} {plural(quanti, 'method', 'methods')}",
                         f"La stima incrocia {quanti} {plural(quanti, 'metodo', 'metodi')}")
                       + ": " + "; ".join(f"{m.label.lower()} ({m.detail})" for m in used) + ".")
        if forecast.note:
            out.append(forecast.note)

    # --- did the signal work here? -----------------------------------------
    test = analisi.backtest
    if test and test.observations >= 24:
        high = next((b for b in test.buckets if b.label.startswith(L("High yield",
                                                                     "Rendimento alto"))), None)
        low = next((b for b in test.buckets if b.label.startswith(L("Low yield",
                                                                    "Rendimento basso"))), None)
        thin = [b for b in (high, low) if b is not None and b.observations < 6]
        if thin:
            # Comparing an average over one or two observations with one over
            # fifty is worse than not comparing at all.
            names = L(" and ", " e ").join(b.label.split(" (")[0].lower() for b in thin)
            out.append(L(f"The backtest is not conclusive: the \"{names}\" group has too few "
                         f"observations ({', '.join(str(b.observations) for b in thin)}) to be "
                         "compared. Over these ten years the stock's yield sat almost always in "
                         "the same band.",
                         f"La verifica retrospettiva non e' conclusiva: il gruppo "
                         f"\"{names}\" ha troppo poche osservazioni "
                         f"({', '.join(str(b.observations) for b in thin)}) per essere "
                         "confrontato. In questi dieci anni il rendimento del titolo e' stato "
                         "quasi sempre nella stessa fascia."))
        elif high and low and high.avg_return_2y is not None and low.avg_return_2y is not None:
            out.append(
                L(f"Tested on this stock's own data: on the {high.observations} occasions when the "
                  f"yield was among the highest in its history, the following two years returned "
                  f"{fmt.pct(high.avg_return_2y, sign=True)} on average; on the {low.observations} "
                  f"occasions when it was among the lowest, "
                  f"{fmt.pct(low.avg_return_2y, sign=True)}.",
                  f"Verifica sui dati di questo titolo: nelle {high.observations} occasioni in cui "
                  f"il "
                  f"rendimento era fra i piu' alti della sua storia, i due anni successivi hanno "
                  f"reso "
                  f"in media {fmt.pct(high.avg_return_2y, sign=True)}; nelle {low.observations} "
                  f"occasioni in cui era fra i piu' bassi, {fmt.pct(low.avg_return_2y, sign=True)}.")
            )
            gap = test.separation
            if gap is not None and not thin:
                if gap > 0.10:
                    out.append(L(f"The gap between the two cases is {fmt.num(gap * 100, 0)} "
                                 "percentage points in favour of the high yield: on this stock the "
                                 "rule worked.",
                                 f"La differenza fra i due casi e' di {fmt.num(gap * 100, 0)} "
                                 "punti percentuali a favore del rendimento alto: su questo titolo "
                                 "la "
                                 "regola ha funzionato."))
                elif gap < -0.10:
                    out.append(L(f"The gap is {fmt.num(abs(gap) * 100, 0)} percentage points "
                                 "*against* the high yield: on this stock, buying when the payout "
                                 "was generous did not pay.",
                                 f"La differenza e' di {fmt.num(abs(gap) * 100, 0)} punti "
                                 "percentuali *contro* il rendimento alto: su questo titolo "
                                 "comprare "
                                 "quando la cedola era generosa non ha pagato."))
                else:
                    out.append(L("The gap between the two cases is small: on this stock the level "
                                 "of the yield did not separate the good moments from the bad ones.",
                                 "La differenza fra i due casi e' piccola: su questo titolo il "
                                 "livello "
                                 "del rendimento non ha distinto bene i momenti buoni da quelli "
                                 "cattivi."))
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
        add(L("> **SYNTHETIC DEMONSTRATION DATA** - invented company, figures are not real.",
              "> **DATI DIMOSTRATIVI SINTETICI** - societa' inventata, numeri non reali."))
        add("")
    add(L(f"**Decision: {d.headline}**", f"**Decisione: {d.headline}**"))
    add("")
    add(L(f"- Price: {fmt.money(m.price, cur)} (latest data {fmt.date(m.trend.get('last_date'))})",
          f"- Prezzo: {fmt.money(m.price, cur)} (ultimo dato al "
          f"{fmt.date(m.trend.get('last_date'))})"))
    add(L(f"- Overall score: {fmt.num(d.composite, 0)}/100",
          f"- Punteggio complessivo: {fmt.num(d.composite, 0)}/100"))
    add(L(f"- Estimated value: {fmt.money(v.fair_bear, cur)} / **{fmt.money(v.fair_base, cur)}** / "
          f"{fmt.money(v.fair_bull, cur)} (pessimistic / base / optimistic)",
          f"- Valore stimato: {fmt.money(v.fair_bear, cur)} / **{fmt.money(v.fair_base, cur)}** / "
          f"{fmt.money(v.fair_bull, cur)} (pessimistico / centrale / ottimistico)"))
    add(L(f"- Expected 2-year return: {fmt.pct(d.expected_return_2y, sign=True)} "
          f"({fmt.pct(d.expected_annualized, sign=True)} a year)",
          f"- Rendimento atteso a 2 anni: {fmt.pct(d.expected_return_2y, sign=True)} "
          f"({fmt.pct(d.expected_annualized, sign=True)} annuo)"))
    if d.entry_price:
        add(L(f"- Entry price for a +20% target over 2 years: below {fmt.money(d.entry_price, cur)}",
              f"- Prezzo d'ingresso per puntare al +20% a 2 anni: sotto "
              f"{fmt.money(d.entry_price, cur)}"))
    add(L(f"- Quality of the data available: {d.data_quality}",
          f"- Qualita' dei dati disponibili: {d.data_quality}"))
    add("")

    div = getattr(analysis, "dividends", None)
    if div is not None and div.pays_dividends and div.signal:
        add(L("## Dividends: the signal", "## Dividendi: il segnale"))
        add("")
        add(f"**{div.signal.headline}**")
        add("")
        add(L(f"- Yield today: {fmt.pct(div.yield_stats.get('attuale'))} "
              f"(historical median {fmt.pct(div.yield_stats.get('mediana'))}, "
              f"percentile {fmt.pct(div.yield_stats.get('percentile'))})",
              f"- Rendimento oggi: {fmt.pct(div.yield_stats.get('attuale'))} "
              f"(mediana storica {fmt.pct(div.yield_stats.get('mediana'))}, "
              f"percentile {fmt.pct(div.yield_stats.get('percentile'))})"))
        add(L(f"- Dividend per share on an annual basis: "
              f"{fmt.money(div.yield_stats.get('dps_indicato'), cur)}",
              f"- Dividendo per azione su base annua: "
              f"{fmt.money(div.yield_stats.get('dps_indicato'), cur)}"))
        if div.forecast and div.forecast.ok:
            add(L(f"- Next 12 months estimate: {fmt.money(div.forecast.year1_base, cur)} "
                  f"(between {fmt.num(div.forecast.year1_low)} and "
                  f"{fmt.num(div.forecast.year1_high)})",
                  f"- Stima prossimi 12 mesi: {fmt.money(div.forecast.year1_base, cur)} "
                  f"(fra {fmt.num(div.forecast.year1_low)} e {fmt.num(div.forecast.year1_high)})"))
        add(L(f"- Dividend safety: {fmt.num(div.safety.score, 0)}/100 "
              f"({div.safety.band}), cut risk {div.safety.cut_risk_band}",
              f"- Solidita' del dividendo: {fmt.num(div.safety.score, 0)}/100 "
              f"({div.safety.band}), rischio di taglio {div.safety.cut_risk_band}"))
        add(L(f"- Expected 2-year return: {fmt.pct(div.signal.expected_return_2y, sign=True)} "
              f"({fmt.pct(div.signal.income_component, sign=True)} from dividends, "
              f"{fmt.pct(div.signal.price_component, sign=True)} from the price)",
              f"- Rendimento atteso a 2 anni: "
              f"{fmt.pct(div.signal.expected_return_2y, sign=True)} "
              f"({fmt.pct(div.signal.income_component, sign=True)} di cedole, "
              f"{fmt.pct(div.signal.price_component, sign=True)} di prezzo)"))
        add(L(f"- Buy below {fmt.money(div.signal.entry_price, cur)}, "
              f"estimated value {fmt.money(div.signal.fair_price, cur)}, "
              f"trim above {fmt.money(div.signal.exit_price, cur)}",
              f"- Compra sotto {fmt.money(div.signal.entry_price, cur)}, "
              f"valore stimato {fmt.money(div.signal.fair_price, cur)}, "
              f"alleggerisci sopra {fmt.money(div.signal.exit_price, cur)}"))
        add("")
        for reason in div.signal.reasons:
            add(L(f"- {reason}", f"- {reason}"))
        add("")
        add(L("### Dividend safety, factor by factor",
              "### Solidita' del dividendo, fattore per fattore"))
        add("")
        add(L("| Factor | Value | Points | Why |", "| Fattore | Valore | Punti | Perche' |"))
        add("|---|---|---|---|")
        for factor in div.safety.factors:
            value = (fmt.pct(factor.value) if factor.fmt == "pct"
                     else fmt.mult(factor.value) if factor.fmt == "x"
                     else fmt.num(factor.value, 0))
            add(L(f"| {factor.label} | {value} | {factor.points:+.0f} | {factor.explanation} |",
                  f"| {factor.label} | {value} | {factor.points:+.0f} | {factor.explanation} |"))
        add("")
        if div.source is not None:
            add(L(f"*Dividend provenance: {div.source.provenance()}*",
                  f"*Provenienza dei dividendi: {div.source.provenance()}*"))
            add("")
            for warning in div.source.disagreements:
                add(L(f"> {warning}", f"> {warning}"))
            if div.source.disagreements:
                add("")

    add(L("## Why", "## Perche'"))
    add("")
    for reason in d.reasons:
        add(f"- {reason}")
    add("")
    add(L("## Putting it into practice", "## Come tradurlo in pratica"))
    add("")
    add(d.position_note)
    add("")
    add(L("## Score by area", "## Punteggio per area"))
    add("")
    add(L("| Area | Score | Question it answers |",
          "| Area | Punteggio | Domanda a cui risponde |"))
    add("|---|---|---|")
    for pillar in d.pillars:
        score = fmt.na() if pillar.score is None else f"{pillar.score:.0f}/100"
        add(f"| {pillar.label} | {score} | {pillar.question} |")
    add("")
    # La chiave e' un identificatore, il titolo e' testo: due cose diverse, e
    # tradurre la chiave faceva sparire in silenzio quattro sezioni del report.
    for title, key in ((L("Ten years of dividends", "Dieci anni di dividendi"), "dividends"),
                       (L("Past", "Passato"), "past"),
                       (L("Present", "Presente"), "present"),
                       (L("Future", "Futuro"), "future")):
        if key not in analysis.narrative:
            continue
        add(f"## {title}")
        add("")
        for paragraph in analysis.narrative[key]:
            add(paragraph)
            add("")
    if d.flags:
        add(L("## Red flags", "## Campanelli d'allarme"))
        add("")
        for flag in d.flags:
            marker = L("SERIOUS", "GRAVE") if flag.severity == "grave" else L("watch", "attenzione")
            add(f"- **[{marker}]** {flag.text}")
        add("")
    add(L("## When to revisit the decision", "## Quando rimettere in discussione la decisione"))
    add("")
    for trigger in d.review_triggers:
        add(f"- {trigger}")
    add("")
    add(L("## Valuation methods used", "## Metodi di valutazione usati"))
    add("")
    add(L("| Method | Value | Weight | Assumptions |", "| Metodo | Valore | Peso | Ipotesi |"))
    add("|---|---|---|---|")
    for method in v.methods:
        if method.usable:
            add(f"| {method.label} | {fmt.money(method.fair_value, cur)} | "
                f"{method.weight:.0%} | {method.detail} |")
        else:
            add(L(f"| {method.label} | not applicable | - | {method.skipped_reason} |",
                  f"| {method.label} | non applicabile | - | {method.skipped_reason} |"))
    add("")
    limits = list(m.notes) + list(v.notes) + list(analysis.data.warnings)
    if div is not None:
        limits += list(div.notes)
    if limits:
        add(L("## Limits of the data", "## Limiti dei dati"))
        add("")
        for note in limits:
            add(f"- {note}")
        add("")
    add("---")
    add("")
    add(L("This document is an automated elaboration of public data: it is neither financial "
          "advice nor a personalised recommendation. Always check the figures against the "
          "company's official statements and the Stock Exchange of Thailand website before "
          "investing.",
          "Questo documento e' un'elaborazione automatica di dati pubblici: non e' una consulenza "
          "finanziaria ne' una raccomandazione personalizzata. Verifica sempre i numeri sui "
          "bilanci "
          "ufficiali della societa' e sul sito della Stock Exchange of Thailand prima di investire."))
    return "\n".join(lines)
