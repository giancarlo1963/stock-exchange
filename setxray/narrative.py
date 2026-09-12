"""Il racconto: passato, presente, futuro — in italiano, generato dai numeri.

Niente testo scritto a mano e niente modello linguistico: ogni frase nasce da
una soglia su un dato calcolato. Il vantaggio e' che il racconto non puo'
contraddire i grafici, e che la stessa azienda produce sempre lo stesso testo.
"""

from __future__ import annotations

from typing import Optional

from setxray import fmt
from setxray.metrics import Metrics
from setxray.scoring import Verdict
from setxray.valuation import Valuation


def _grade(value: Optional[float], thresholds: tuple[float, ...], words: tuple[str, ...]) -> str:
    """Traduce un numero in un aggettivo, secondo soglie crescenti."""
    if value is None:
        return words[0]
    for threshold, word in zip(thresholds, words[1:]):
        if value < threshold:
            return word
    return words[-1]


# --------------------------------------------------------------------------
# PASSATO
# --------------------------------------------------------------------------
def past(m: Metrics) -> list[str]:
    """Che azienda e' stata: crescita, redditivita', ritorno per l'azionista."""
    out: list[str] = []
    years = m.year_labels()
    if not years:
        return ["Non sono disponibili bilanci storici per questo titolo su Yahoo Finance, quindi "
                "non e' possibile ricostruire il passato dell'azienda. L'analisi che segue si basa "
                "solo sull'andamento del prezzo."]

    span = m.growth.get("revenue_span") or 0
    rev_cagr = m.growth.get("revenue_cagr")
    eps_cagr = m.growth.get("eps_cagr")
    opening = f"Nei {len(years)} esercizi disponibili ({years[0]}-{years[-1]})"
    if rev_cagr is None:
        out.append(f"{opening} i ricavi non mostrano una tendenza calcolabile.")
    else:
        word = _grade(rev_cagr, (-0.02, 0.02, 0.06, 0.12),
                      ("", "in netto calo", "sostanzialmente fermi", "in crescita moderata",
                       "in buona crescita", "in forte crescita"))
        out.append(f"{opening} i ricavi sono stati {word}: {fmt.pct(rev_cagr, sign=True)} "
                   f"all'anno in media" + (f" su {span:.0f} anni." if span else "."))

    if eps_cagr is not None and rev_cagr is not None:
        if eps_cagr > rev_cagr + 0.02:
            out.append(f"L'utile per azione e' cresciuto piu' dei ricavi ({fmt.pct(eps_cagr, sign=True)} "
                       "all'anno): l'azienda e' diventata piu' efficiente, oppure ha ridotto il numero "
                       "di azioni in circolazione.")
        elif eps_cagr < rev_cagr - 0.02:
            out.append(f"L'utile per azione e' cresciuto meno dei ricavi ({fmt.pct(eps_cagr, sign=True)} "
                       "all'anno): i margini si sono compressi, oppure sono state emesse nuove azioni.")
        else:
            out.append(f"L'utile per azione ha seguito i ricavi ({fmt.pct(eps_cagr, sign=True)} all'anno).")

    up, total = m.growth.get("revenue_up_years"), m.growth.get("revenue_total_years")
    if up is not None and total:
        if up == total:
            out.append("I ricavi sono cresciuti in ogni esercizio del periodo: un percorso regolare.")
        elif up == 0:
            out.append("I ricavi non sono cresciuti in nessuno degli esercizi osservati.")
        else:
            out.append(f"La crescita e' stata discontinua: {up} esercizi in aumento su {total}.")

    roe = m.quality.get("roe_avg3")
    roic = m.quality.get("roic_avg3")
    if roe is not None:
        word = _grade(roe, (0.0, 0.08, 0.13, 0.20),
                      ("", "negativa", "bassa", "discreta", "buona", "molto buona"))
        sentence = (f"La redditivita' del capitale proprio e' stata {word}: ROE medio {fmt.pct(roe)} "
                    "negli ultimi esercizi")
        if roic is not None:
            sentence += f", ROIC {fmt.pct(roic)} sul capitale investito"
        out.append(sentence + ".")
        if roic is not None and roic > 0.10:
            out.append("Un ROIC sopra il 10% indica che l'azienda crea valore quando reinveste gli "
                       "utili: e' la caratteristica che conta di piu' per chi resta investito anni.")
        elif roic is not None and 0 < roic < 0.06:
            out.append("Un ROIC sotto il 6% significa che reinvestire rende poco: la crescita, se "
                       "arriva, non crea molto valore per l'azionista.")

    margin_trend = m.quality.get("operating_margin_trend")
    om = m.quality.get("operating_margin_avg3")
    if om is not None:
        sentence = f"Il margine operativo medio e' stato {fmt.pct(om)}"
        if margin_trend is not None:
            if margin_trend > 0.02:
                sentence += (f", in miglioramento di {fmt.num(margin_trend * 100, 1)} punti "
                             "percentuali nel periodo")
            elif margin_trend < -0.02:
                sentence += (f", in peggioramento di {fmt.num(abs(margin_trend) * 100, 1)} punti "
                             "percentuali nel periodo")
            else:
                sentence += ", stabile nel periodo"
        out.append(sentence + ".")

    positive, tot = m.growth.get("fcf_positive_years"), m.growth.get("fcf_total_years")
    if positive is not None and tot:
        if positive == tot:
            out.append("L'azienda ha generato cassa libera in tutti gli esercizi osservati.")
        elif positive == 0:
            out.append("L'azienda non ha generato cassa libera in nessuno degli esercizi osservati: "
                       "la crescita e' stata finanziata con debito o capitale nuovo.")
        else:
            out.append(f"La cassa libera e' stata positiva in {positive} esercizi su {tot}.")

    div = m.dividend
    if div.get("paying_years"):
        sentence = f"Ha distribuito dividendi in {div['paying_years']} degli anni rilevati"
        growth = m.growth.get("dps_cagr") or div.get("dps_cagr")
        if growth is not None:
            sentence += f", con una crescita media del dividendo di {fmt.pct(growth, sign=True)} all'anno"
        if div.get("cuts"):
            sentence += f", e {div['cuts']} riduzioni lungo il percorso"
        out.append(sentence + ".")
    else:
        out.append("Non risultano dividendi distribuiti nel periodo rilevato.")

    ret5, bench5 = m.trend.get("return_5y"), m.trend.get("benchmark_return_5y")
    if ret5 is not None:
        sentence = (f"Per chi lo ha comprato cinque anni fa il titolo ha reso "
                    f"{fmt.pct(ret5, sign=True)} complessivi")
        if bench5 is not None:
            delta = ret5 - bench5
            sentence += (f", {'meglio' if delta > 0 else 'peggio'} dell'indice SET "
                         f"({fmt.pct(bench5, sign=True)}), con uno scarto di "
                         f"{fmt.num(abs(delta) * 100, 1)} punti percentuali")
        out.append(sentence + ".")

    drawdown = m.trend.get("max_drawdown_5y")
    if drawdown is not None:
        out.append(f"Lungo il percorso ha perso fino al {fmt.pct(abs(drawdown))} dal massimo precedente: "
                   "e' l'oscillazione che bisogna essere disposti a sopportare per restare investiti.")
    return out


# --------------------------------------------------------------------------
# PRESENTE
# --------------------------------------------------------------------------
def present(m: Metrics, v: Valuation) -> list[str]:
    """Dove si trova adesso: conti degli ultimi dodici mesi, prezzo, solidita'."""
    out: list[str] = []
    cur = m.currency
    price = m.price
    if price is None:
        return ["Prezzo di mercato non disponibile: impossibile descrivere la situazione attuale."]

    sentence = f"Il titolo tratta a {fmt.money(price, cur)}"
    if m.market_cap:
        sentence += f", per una capitalizzazione di {fmt.big(m.market_cap, cur)}"
    if m.trend.get("high_52w") and m.trend.get("low_52w"):
        sentence += (f". Nelle ultime 52 settimane si e' mosso fra {fmt.num(m.trend['low_52w'])} e "
                     f"{fmt.num(m.trend['high_52w'])} {cur}")
        if m.trend.get("from_high_52w") is not None:
            sentence += f", oggi e' {fmt.pct(abs(m.trend['from_high_52w']))} sotto il massimo"
    out.append(sentence + ".")

    revenue, net = m.ttm.get("revenue"), m.ttm.get("net_income")
    if revenue:
        sentence = f"Negli ultimi dodici mesi ha fatturato {fmt.big(revenue, cur)}"
        if net is not None:
            if net >= 0:
                sentence += (f" con un utile netto di {fmt.big(net, cur)} "
                             f"(margine {fmt.pct(m.ttm.get('net_margin'))})")
            else:
                sentence += f" chiudendo in perdita di {fmt.big(abs(net), cur)}"
        growth = m.growth.get("revenue_ttm_vs_last_year")
        if growth is not None:
            direction = ("in accelerazione" if growth > 0.03
                         else "in rallentamento" if growth < -0.03 else "in linea")
            sentence += f", {direction} rispetto all'ultimo bilancio annuale ({fmt.pct(growth, sign=True)})"
        out.append(sentence + ".")

    pe = m.valuation.get("pe")
    pe_hist = m.multiple_history.get("pe") or {}
    if pe:
        sentence = f"Il prezzo vale {fmt.mult(pe)} gli utili degli ultimi dodici mesi"
        median = pe_hist.get("median")
        percentile = pe_hist.get("percentile")
        if median:
            relation = "sotto" if pe < median else "sopra"
            sentence += (f", contro una mediana storica di {fmt.mult(median)}: quindi "
                         f"{fmt.pct(abs(pe / median - 1))} {relation} la propria media")
            if percentile is not None:
                if percentile <= 0.25:
                    sentence += ". Raramente e' stato cosi' economico"
                elif percentile >= 0.75:
                    sentence += ". Raramente e' stato cosi' caro"
        out.append(sentence + ".")
    else:
        out.append("Il P/E non e' calcolabile perche' gli utili degli ultimi dodici mesi non sono "
                   "positivi: la valutazione va letta sul patrimonio e sui flussi di cassa.")

    extra: list[str] = []
    if m.valuation.get("pb"):
        extra.append(f"P/B {fmt.mult(m.valuation['pb'])}")
    if m.valuation.get("ev_ebitda") and not m.is_financial:
        extra.append(f"EV/EBITDA {fmt.mult(m.valuation['ev_ebitda'])}")
    if m.valuation.get("fcf_yield") is not None:
        extra.append(f"rendimento della cassa libera {fmt.pct(m.valuation['fcf_yield'])}")
    if m.dividend.get("yield_current"):
        extra.append(f"dividendo {fmt.pct(m.dividend['yield_current'])}")
    if extra:
        out.append("Gli altri multipli: " + ", ".join(extra) + ".")

    nd = m.health.get("net_debt_ebitda")
    if nd is not None and not m.is_financial:
        word = _grade(nd, (0.0, 1.5, 3.0, 4.5),
                      ("", "assente, c'e' piu' cassa che debito", "basso", "gestibile",
                       "elevato", "molto elevato"))
        sentence = f"Il debito e' {word}: {fmt.mult(nd)} l'EBITDA"
        cov = m.health.get("interest_coverage")
        if cov is not None:
            sentence += f", con gli interessi coperti {fmt.mult(cov)} dall'utile operativo"
        out.append(sentence + ".")
    elif m.is_financial and m.health.get("equity_ratio"):
        out.append("Come intermediario finanziario, il dato di solidita' rilevante e' il patrimonio "
                   f"sull'attivo totale: {fmt.pct(m.health['equity_ratio'])}.")

    fcf = m.ttm.get("fcf")
    if fcf is not None:
        if fcf > 0:
            out.append(f"Negli ultimi dodici mesi ha generato {fmt.big(fcf, cur)} di cassa libera "
                       "dopo gli investimenti.")
        else:
            out.append(f"Negli ultimi dodici mesi ha bruciato {fmt.big(abs(fcf), cur)} di cassa dopo "
                       "gli investimenti: una situazione che va finanziata con debito o capitale nuovo.")

    vs200 = m.trend.get("vs_sma200")
    excess = m.trend.get("excess_1y")
    if vs200 is not None:
        sentence = (f"Sul fronte del prezzo, oggi e' {fmt.pct(abs(vs200))} "
                    f"{'sopra' if vs200 > 0 else 'sotto'} la media degli ultimi 200 giorni")
        if excess is not None:
            sentence += (f" e negli ultimi 12 mesi ha fatto {'meglio' if excess > 0 else 'peggio'} "
                         f"dell'indice SET di {fmt.pct(abs(excess))}")
        out.append(sentence + ".")
    return out


# --------------------------------------------------------------------------
# FUTURO
# --------------------------------------------------------------------------
def future(m: Metrics, v: Valuation, verdict: Verdict) -> list[str]:
    """Cosa ci si puo' aspettare a 1-2 anni, con le ipotesi in chiaro."""
    out: list[str] = []
    cur = m.currency

    growth_next = m.estimates.get("eps_growth_next_year") or m.estimates.get("growth_next_year")
    analysts = m.estimates.get("analysts")
    if growth_next is not None:
        sentence = f"Le attese sull'utile del prossimo esercizio sono di {fmt.pct(growth_next, sign=True)}"
        if analysts:
            sentence += f" (media di {int(analysts)} analisti)"
        out.append(sentence + ".")
    else:
        out.append("Nessuna stima di analisti disponibile per questo titolo: le proiezioni che seguono "
                   "partono dai soli dati storici dell'azienda.")

    if v.has_fair_value and m.price:
        out.append(
            f"Incrociando {len(v.usable_methods())} metodi di valutazione indipendenti, il valore "
            f"stimato si colloca fra {fmt.money(v.fair_bear, cur)} nello scenario pessimistico e "
            f"{fmt.money(v.fair_bull, cur)} in quello ottimistico, con un valore centrale di "
            f"{fmt.money(v.fair_base, cur)}. Rispetto al prezzo di oggi significa "
            f"{fmt.pct(v.upside_base, sign=True)}."
        )
        if v.expected_return_2y is not None:
            out.append(
                f"Su due anni, aggiungendo i dividendi attesi ({fmt.pct((v.dividend_yield or 0) * 2)} "
                f"cumulati), il rendimento complessivo atteso e' {fmt.pct(v.expected_return_2y, sign=True)}, "
                f"cioe' {fmt.pct(v.expected_annualized, sign=True)} all'anno."
            )
        out.append(
            f"Le ipotesi dietro questi numeri, in chiaro: rendimento richiesto {fmt.pct(v.cost_of_equity)} "
            f"(tasso privo di rischio {fmt.pct(v.risk_free)} piu' beta {fmt.ratio(v.beta)} per il premio "
            f"al rischio {fmt.pct(v.equity_risk_premium)}), crescita perpetua non oltre il 4%, "
            f"convergenza del prezzo al valore stimato entro due anni. Affidabilita' complessiva "
            f"della stima: {v.reliability}."
        )
    else:
        out.append("Nessun modello di valutazione e' applicabile con i dati disponibili: non e' "
                   "possibile indicare un valore di riferimento, e questo da solo e' un motivo di prudenza.")

    if v.analyst_target and m.price:
        out.append(f"Gli analisti che coprono il titolo indicano un obiettivo medio di "
                   f"{fmt.money(v.analyst_target, cur)}, {fmt.pct(abs(v.analyst_upside or 0))} "
                   f"{'sopra' if v.analyst_target > m.price else 'sotto'} il prezzo attuale. "
                   "E' un riferimento di mercato, non una verifica indipendente.")

    drivers: list[str] = []
    if (m.growth.get("revenue_cagr") or 0) > 0.08:
        drivers.append("la crescita dei ricavi gia' in atto")
    if (m.quality.get("roic_avg3") or 0) > 0.10:
        drivers.append("la capacita' di reinvestire con rendimenti alti")
    if (m.dividend.get("yield_current") or 0) >= 0.04:
        drivers.append(f"il dividendo ({fmt.pct(m.dividend['yield_current'])}), che paga l'attesa")
    pe_percentile = (m.multiple_history.get("pe") or {}).get("percentile")
    if pe_percentile is not None and pe_percentile <= 0.30:
        drivers.append("il ritorno del multiplo verso la propria media storica")
    if (m.quality.get("operating_margin_trend") or 0) > 0.02:
        drivers.append("il miglioramento dei margini in corso")
    if drivers:
        out.append("Cosa puo' far salire il titolo nei prossimi 1-2 anni: " + "; ".join(drivers) + ".")

    risks = [flag.text.rstrip(".") for flag in verdict.grave_flags[:3]]
    risks += [flag.text.rstrip(".") for flag in verdict.warning_flags[:3]]
    if (m.trend.get("volatility") or 0) > 0.35:
        risks.append(f"volatilita' annua del {fmt.pct(m.trend['volatility'])}, che rende probabili "
                     "oscillazioni ampie anche senza cattive notizie")
    if m.is_financial:
        risks.append("come intermediario finanziario e' esposto al ciclo del credito e ai tassi")
    if not risks:
        risks.append("dai dati non emerge un rischio specifico, ma restano il rischio di mercato e "
                     "quello di cambio per chi investe dall'Europa")
    out.append("Cosa puo' andare storto: " + "; ".join(risks) + ".")

    out.append("Nota sul cambio: il titolo e' quotato in baht. Per un investitore in euro il "
               "rendimento finale dipende anche dal cambio EUR/THB, che questa analisi non prevede.")
    return out


# --------------------------------------------------------------------------
# report scaricabile
# --------------------------------------------------------------------------
def build_report(analysis) -> str:
    """Il report completo in markdown, da salvare, stampare o inviare."""
    m: Metrics = analysis.metrics
    v: Valuation = analysis.valuation
    d: Verdict = analysis.verdict
    cur = m.currency
    lines: list[str] = []
    add = lines.append

    add(f"# {m.name} ({m.symbol})")
    add("")
    if analysis.data.is_demo:
        add("> **DATI DIMOSTRATIVI SINTETICI** - societa' inventata, numeri non reali.")
        add("")
    add(f"**Decisione: {d.headline}**")
    add("")
    add(f"- Prezzo: {fmt.money(m.price, cur)} (ultimo dato al {fmt.date(m.trend.get('last_date'))})")
    add(f"- Punteggio complessivo: {fmt.num(d.composite, 0)}/100")
    add(f"- Valore stimato: {fmt.money(v.fair_bear, cur)} / **{fmt.money(v.fair_base, cur)}** / "
        f"{fmt.money(v.fair_bull, cur)} (pessimistico / centrale / ottimistico)")
    add(f"- Rendimento atteso a 2 anni: {fmt.pct(d.expected_return_2y, sign=True)} "
        f"({fmt.pct(d.expected_annualized, sign=True)} annuo)")
    if d.entry_price:
        add(f"- Prezzo d'ingresso per puntare al +20% a 2 anni: sotto {fmt.money(d.entry_price, cur)}")
    add(f"- Qualita' dei dati disponibili: {d.data_quality}")
    add("")
    add("## Perche'")
    add("")
    for reason in d.reasons:
        add(f"- {reason}")
    add("")
    add("## Come tradurlo in pratica")
    add("")
    add(d.position_note)
    add("")
    add("## Punteggio per area")
    add("")
    add("| Area | Punteggio | Domanda a cui risponde |")
    add("|---|---|---|")
    for pillar in d.pillars:
        score = "n/d" if pillar.score is None else f"{pillar.score:.0f}/100"
        add(f"| {pillar.label} | {score} | {pillar.question} |")
    add("")
    for title, key in (("Passato", "passato"), ("Presente", "presente"), ("Futuro", "futuro")):
        add(f"## {title}")
        add("")
        for paragraph in analysis.narrative[key]:
            add(paragraph)
            add("")
    if d.flags:
        add("## Campanelli d'allarme")
        add("")
        for flag in d.flags:
            marker = "GRAVE" if flag.severity == "grave" else "attenzione"
            add(f"- **[{marker}]** {flag.text}")
        add("")
    add("## Quando rimettere in discussione la decisione")
    add("")
    for trigger in d.review_triggers:
        add(f"- {trigger}")
    add("")
    add("## Metodi di valutazione usati")
    add("")
    add("| Metodo | Valore | Peso | Ipotesi |")
    add("|---|---|---|---|")
    for method in v.methods:
        if method.usable:
            add(f"| {method.label} | {fmt.money(method.fair_value, cur)} | "
                f"{method.weight:.0%} | {method.detail} |")
        else:
            add(f"| {method.label} | non applicabile | - | {method.skipped_reason} |")
    add("")
    limits = list(m.notes) + list(v.notes) + list(analysis.data.warnings)
    if limits:
        add("## Limiti dei dati")
        add("")
        for note in limits:
            add(f"- {note}")
        add("")
    add("---")
    add("")
    add("Questo documento e' un'elaborazione automatica di dati pubblici: non e' una consulenza "
        "finanziaria ne' una raccomandazione personalizzata. Verifica sempre i numeri sui bilanci "
        "ufficiali della societa' e sul sito della Stock Exchange of Thailand prima di investire.")
    return "\n".join(lines)
