"""SET X-Ray - interfaccia web.

Avvio:
    streamlit run app.py

Una sola schermata: scrivi il simbolo, leggi la decisione, poi scendi nei
dettagli se vuoi capire da dove viene. L'ordine delle sezioni e' voluto: prima
la risposta, poi le prove.
"""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from setxray import __version__, charts, fmt
from setxray.datasource import POPULAR_SET_SYMBOLS, clear_cache
from setxray.demo import PROFILES
from setxray.engine import Analysis, NoDataError, analyze
from setxray.scoring import BUY, HOLD, SELL
from setxray.sources import describe_sources

st.set_page_config(page_title="SET X-Ray - dividendi e analisi azioni Thailandia",
                   page_icon="📊", layout="wide")

VERDICT_STYLE = {
    BUY: ("#0ca30c", "Comprare o accumulare"),
    HOLD: ("#fab219", "Tenere, senza aumentare"),
    SELL: ("#d03b3b", "Vendere o ridurre"),
}

st.markdown("""
<style>
  .verdetto { border-radius: 14px; padding: 22px 26px; color: #fff; margin-bottom: 4px; }
  .verdetto h1 { font-size: 2.0rem; margin: 0 0 6px 0; font-weight: 700; letter-spacing: -0.02em; }
  .verdetto p  { margin: 0; font-size: 1.02rem; opacity: 0.95; }
  .riquadro { border: 1px solid rgba(11,11,11,0.12); border-radius: 12px;
              padding: 14px 16px; height: 100%; }
  .riquadro .etichetta { font-size: 0.78rem; text-transform: uppercase;
                         letter-spacing: 0.05em; opacity: 0.7; }
  .riquadro .valore { font-size: 1.5rem; font-weight: 650; line-height: 1.25; }
  .riquadro .nota { font-size: 0.82rem; opacity: 0.72; }
  .grave { border-left: 4px solid #d03b3b; padding: 8px 14px; margin-bottom: 8px;
           background: rgba(208,59,59,0.08); border-radius: 6px; }
  .avviso { border-left: 4px solid #fab219; padding: 8px 14px; margin-bottom: 8px;
            background: rgba(250,178,25,0.10); border-radius: 6px; }
  .blocco p { margin-bottom: 0.7rem; line-height: 1.55; }
  .secondario { border: 1px solid rgba(11,11,11,0.14); border-radius: 10px;
                padding: 12px 16px; margin: 10px 0 2px 0; }
  .secondario .titolo { font-size: 0.8rem; text-transform: uppercase;
                        letter-spacing: 0.05em; opacity: 0.7; margin-bottom: 2px; }
  .divergenza { border-left: 4px solid #ec835a; background: rgba(236,131,90,0.10);
                padding: 10px 14px; border-radius: 6px; margin-top: 8px; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False, ttl=1800)
def _analyze_cached(symbol: str, risk_free: float, erp: float) -> Analysis:
    """Una richiesta per simbolo e per set di ipotesi: Yahoo non ama le raffiche."""
    return analyze(symbol, risk_free=risk_free, erp=erp)


def riquadro(etichetta: str, valore: str, nota: str = "", colore: str = "") -> str:
    stile = f" style='color:{colore}'" if colore else ""
    return (f"<div class='riquadro'><div class='etichetta'>{etichetta}</div>"
            f"<div class='valore'{stile}>{valore}</div>"
            f"<div class='nota'>{nota}</div></div>")


# Link diretto: ?simbolo=PTT apre l'app con l'analisi gia' avviata, cosi' si
# puo' salvare o condividere l'indirizzo di un titolo.
_da_url = st.query_params.get("simbolo")
if _da_url and "simbolo" not in st.session_state:
    st.session_state["simbolo"] = _da_url
    st.session_state["esegui"] = True


# --------------------------------------------------------------------------
# barra laterale
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### SET X-Ray")
    st.caption(f"Dividendi e analisi fondamentale - Borsa di Thailandia - versione {__version__}")

    simbolo = st.text_input("Simbolo SET", value=st.session_state.get("simbolo", "PTT"),
                            help="Per esempio PTT, AOT, CPALL, SCB. Il suffisso .BK e' facoltativo.")
    avvia = st.button("Analizza", type="primary", use_container_width=True)

    st.markdown("**Titoli molto scambiati**")
    colonne = st.columns(2)
    for i, (codice, descrizione) in enumerate(POPULAR_SET_SYMBOLS):
        if colonne[i % 2].button(codice, key=f"quick-{codice}", help=descrizione,
                                 use_container_width=True):
            st.session_state["simbolo"] = codice
            st.session_state["esegui"] = True
            st.rerun()

    with st.expander("Prova senza internet (dati finti)"):
        st.caption("Quattro aziende inventate, per vedere come funziona l'analisi "
                   "nei casi tipici. I numeri non sono reali.")
        for profilo, descrizione in PROFILES.items():
            if st.button(f"Demo: {profilo}", key=f"demo-{profilo}", help=descrizione,
                         use_container_width=True):
                st.session_state["simbolo"] = f"demo:{profilo}"
                st.session_state["esegui"] = True
                st.rerun()

    with st.expander("Ipotesi di valutazione"):
        st.caption("Cambiano il rendimento che pretendi dall'investimento, quindi il valore stimato.")
        tasso = st.slider("Tasso privo di rischio (Thailandia, 10 anni)", 0.5, 6.0, 2.8, 0.1,
                          format="%.1f%%") / 100
        premio = st.slider("Premio per il rischio azionario", 3.0, 12.0, 7.5, 0.5,
                           format="%.1f%%") / 100
        if st.button("Svuota la cache dei dati", use_container_width=True):
            rimossi = clear_cache()
            _analyze_cached.clear()
            st.success(f"Cache svuotata ({rimossi} file).")

    st.divider()
    attive = [riga["fonte"] for riga in describe_sources() if riga["attiva"]]
    st.caption(f"Dividendi da {len(attive)} fonti attive · prezzi e bilanci da Yahoo Finance. "
               "Vedi la scheda *Fonti dei dati*. Non e' consulenza finanziaria.")

if avvia:
    st.session_state["simbolo"] = simbolo
    st.session_state["esegui"] = True

if not st.session_state.get("esegui"):
    st.title("Dividendi e analisi di un'azione della Borsa di Thailandia")
    st.markdown("""
Scrivi il simbolo di un titolo quotato alla **SET** di Bangkok (per esempio `PTT`,
`AOT`, `CPALL`) e premi **Analizza**.

Lo strumento e' costruito attorno a una domanda: **come ha distribuito dividendi
questo titolo negli ultimi dieci anni, e cosa dice quella storia su cosa fare
oggi?** Ricostruisce ogni stacco, misura crescita, tagli e continuita', calcola
quanto del rendimento totale e' arrivato dalle cedole, stima cosa paghera' nei
prossimi due anni, e conclude con **comprare, mantenere o vendere** spiegando
il perche'.

L'orizzonte e' **1-2 anni minimo**: non e' uno strumento per il trading di breve.
""")
    colonne = st.columns(3)
    with colonne[0]:
        st.markdown("#### Dieci anni di cedole")
        st.caption("Dividendo per azione anno per anno, crescita media a 3, 5 e 10 anni, "
                   "tagli e anni saltati, e quanta parte del rendimento totale e' arrivata "
                   "dalle cedole invece che dal prezzo.")
    with colonne[1]:
        st.markdown("#### Il dividendo regge?")
        st.caption("Un punteggio di solidita' costruito da fattori visibili uno per uno: "
                   "copertura con gli utili, copertura con la cassa vera, debito, andamento "
                   "degli utili, storia dei tagli, continuita'.")
    with colonne[2]:
        st.markdown("#### Comprare o vendere, e perche'")
        st.caption("Il rendimento di oggi confrontato con la storia del titolo, la previsione "
                   "del dividendo a due anni, e una verifica retrospettiva di come si e' "
                   "comportato questo segnale su questo stesso titolo.")
    st.info("Non hai internet o vuoi solo vedere com'e' fatta? Apri **Prova senza "
            "internet** nella barra a sinistra: sei aziende inventate coprono i casi tipici, "
            "compreso un dividendo tagliato e un pagatore irregolare.", icon="💡")
    with st.expander("Da dove arrivano i dati sui dividendi"):
        st.caption("Lo strumento interroga piu' archivi e confronta i risultati, perche' sui "
                   "titoli SET i dividendi sono il dato piu' facile da sbagliare.")
        st.dataframe(pd.DataFrame([{
            "Fonte": riga["fonte"],
            "Serve una chiave": riga["chiave_api"],
            "Attiva adesso": "si" if riga["attiva"] else "no",
            "Note": riga["nota"],
        } for riga in describe_sources()]), use_container_width=True, hide_index=True)
    st.stop()

# --------------------------------------------------------------------------
# analisi
# --------------------------------------------------------------------------
richiesto = st.session_state.get("simbolo", "PTT")
if st.query_params.get("simbolo") != richiesto:
    st.query_params["simbolo"] = richiesto
try:
    with st.spinner(f"Scarico e analizzo {richiesto}..."):
        analisi = _analyze_cached(richiesto, tasso, premio)
except NoDataError as errore:
    st.error(str(errore), icon="⚠️")
    st.stop()
except ValueError as errore:
    st.error(f"Simbolo non valido: {errore}", icon="⚠️")
    st.stop()
except Exception as errore:  # rete, rate limit di Yahoo, formati inattesi
    st.error(f"Non e' stato possibile completare l'analisi: {type(errore).__name__} - {errore}",
             icon="⚠️")
    st.info("Se il problema si ripete, prova a svuotare la cache dei dati "
            "nella barra a sinistra, o riprova fra qualche minuto: Yahoo Finance "
            "limita il numero di richieste.")
    st.stop()

m, v, d = analisi.metrics, analisi.valuation, analisi.verdict
scuro = st.get_option("theme.base") == "dark"
valuta = m.currency

if analisi.data.is_demo:
    st.warning("**Modalita' dimostrativa.** Societa' inventata e numeri sintetici: "
               "servono solo a mostrare come funziona l'app. Non usarli per decidere.", icon="🧪")

st.markdown(f"## {m.name}")
sottotitolo = [f"`{m.symbol}`"]
if m.sector:
    sottotitolo.append(m.sector)
if m.industry:
    sottotitolo.append(m.industry)
sottotitolo.append(f"dati al {fmt.date(m.trend.get('last_date'))}")
if analisi.data.from_cache:
    sottotitolo.append("da cache locale")
st.caption(" · ".join(sottotitolo))

# --- la risposta sui dividendi, prima di tutto il resto -------------------
div = analisi.dividends
segnale = div.signal if (div and div.pays_dividends and div.signal) else None

if segnale is not None:
    colore, spiegazione = VERDICT_STYLE[segnale.action]
    sicurezza = div.safety
    st.markdown(
        f"<div class='verdetto' style='background:{colore}'>"
        f"<h1>{segnale.headline}</h1><p>{spiegazione} · orizzonte 1-2 anni · "
        f"solidita' del dividendo {fmt.num(sicurezza.score, 0)}/100 ({sicurezza.band}) · "
        f"rischio di taglio {sicurezza.cut_risk_band}</p></div>",
        unsafe_allow_html=True,
    )

    rendimento = div.yield_stats
    colonne = st.columns(4)
    percentile = rendimento.get("percentile")
    nota_percentile = ("" if percentile is None
                       else f"piu' generoso del {fmt.pct(percentile)} della sua storia")
    colonne[0].markdown(riquadro(
        "Rendimento oggi", fmt.pct(rendimento.get("attuale")),
        f"mediana storica {fmt.pct(rendimento.get('mediana'))} · {nota_percentile}",
    ), unsafe_allow_html=True)
    previsione = div.forecast
    colonne[1].markdown(riquadro(
        "Dividendo per azione", fmt.money(rendimento.get("dps_indicato"), valuta),
        (f"stima prossimi 12 mesi {fmt.money(previsione.year1_base, valuta)}"
         if previsione and previsione.ok else "su base annua, ultimi stacchi"),
    ), unsafe_allow_html=True)
    atteso = segnale.expected_return_2y
    colonne[2].markdown(riquadro(
        "Rendimento atteso a 2 anni", fmt.pct(atteso, sign=True),
        (f"{fmt.pct(segnale.income_component, sign=True)} di cedole e "
         f"{fmt.pct(segnale.price_component, sign=True)} di prezzo"),
        colore="#0ca30c" if (atteso or 0) > 0.08 else "#d03b3b" if (atteso or 0) < 0 else "",
    ), unsafe_allow_html=True)
    etichetta = ("Compra sotto" if segnale.action != SELL else "Tornerebbe interessante sotto")
    colonne[3].markdown(riquadro(
        etichetta, fmt.money(segnale.entry_price, valuta),
        f"valore stimato {fmt.money(segnale.fair_price, valuta)} · "
        f"alleggerisci sopra {fmt.money(segnale.exit_price, valuta)}",
    ), unsafe_allow_html=True)

    st.markdown("### Perche'")
    for motivo in segnale.reasons:
        st.markdown(f"- {motivo}")

    # Il giudizio generale come conferma o come contraddizione: quando i due
    # modelli divergono l'utente deve saperlo, non ricevere una media.
    generale = d.expected_return_2y
    st.markdown(
        f"<div class='secondario'><div class='titolo'>Analisi fondamentale generale "
        f"(utili, cassa, patrimonio, debito)</div>"
        f"<b>{d.headline}</b> · punteggio {fmt.num(d.composite, 0)}/100 · "
        f"rendimento atteso {fmt.pct(generale, sign=True)}"
        + ("<br><span style='font-size:0.88rem;opacity:0.85'>Il prezzo sembra basso sugli "
           "utili, ma i campanelli d'allarme sui conti prevalgono: e' il profilo tipico di "
           "una trappola di valore.</span>"
           if d.action == SELL and (generale or 0) > 0.10 else "")
        + "</div>",
        unsafe_allow_html=True,
    )
    if d.action != segnale.action:
        st.markdown(
            f"<div class='divergenza'><b>I due modelli non concordano.</b> "
            f"Sui dividendi il segnale e' <b>{segnale.action}</b>, sui fondamentali generali "
            f"<b>{d.action}</b>. Non e' un errore: guardano cose diverse. Il modello sui "
            "dividendi pesa la sostenibilita' della cedola, quello generale pesa utili e "
            "patrimonio. Se ti interessa il reddito, segui il primo e leggi il secondo come "
            "avvertimento; se ti interessa la crescita del capitale, il contrario.</div>",
            unsafe_allow_html=True,
        )
else:
    colore, spiegazione = VERDICT_STYLE[d.action]
    st.markdown(
        f"<div class='verdetto' style='background:{colore}'>"
        f"<h1>{d.headline}</h1><p>{spiegazione} · orizzonte 1-2 anni · "
        f"punteggio {fmt.num(d.composite, 0)}/100 · "
        f"affidabilita' dei dati: {d.data_quality}</p></div>",
        unsafe_allow_html=True,
    )
    st.warning("**Questo titolo non distribuisce dividendi** secondo le fonti disponibili, "
               "quindi il giudizio qui sopra viene dall'analisi fondamentale generale. "
               "La scheda *Dividendi* spiega cosa fare se sai che invece distribuisce.",
               icon="ℹ️")
    colonne = st.columns(4)
    colonne[0].markdown(riquadro("Prezzo oggi", fmt.money(m.price, valuta),
                                 f"52 settimane: {fmt.num(m.trend.get('low_52w'))} - "
                                 f"{fmt.num(m.trend.get('high_52w'))}"), unsafe_allow_html=True)
    colonne[1].markdown(riquadro("Valore stimato", fmt.money(v.fair_base, valuta),
                                 f"forchetta {fmt.num(v.fair_bear)} - {fmt.num(v.fair_bull)}"),
                        unsafe_allow_html=True)
    colonne[2].markdown(riquadro("Rendimento atteso a 2 anni",
                                 fmt.pct(d.expected_return_2y, sign=True),
                                 f"{fmt.pct(d.expected_annualized, sign=True)} all'anno"),
                        unsafe_allow_html=True)
    colonne[3].markdown(riquadro("Prezzo d'ingresso",
                                 fmt.money(d.entry_price, valuta) if d.entry_price else "n/d",
                                 "sotto questo prezzo l'obiettivo del +20% resta raggiungibile"),
                        unsafe_allow_html=True)
    st.markdown("### Perche'")
    for motivo in d.reasons:
        st.markdown(f"- {motivo}")

st.info(d.position_note, icon="💼")

if d.grave_flags or d.warning_flags:
    st.markdown("### Campanelli d'allarme sui conti")
    for flag in d.grave_flags:
        st.markdown(f"<div class='grave'><b>Grave</b> - {flag.text}</div>", unsafe_allow_html=True)
    for flag in d.warning_flags:
        st.markdown(f"<div class='avviso'><b>Attenzione</b> - {flag.text}</div>",
                    unsafe_allow_html=True)


# --------------------------------------------------------------------------
# sezioni
# --------------------------------------------------------------------------
schede = st.tabs(["Dividendi (10 anni)", "Passato", "Presente", "Futuro",
                  "Dettaglio dei punteggi", "Tabelle", "Fonti dei dati"])

with schede[0]:
    if segnale is None:
        st.markdown("#### Nessun dividendo registrato")
        for nota in (div.notes if div else []):
            st.markdown(f"- {nota}")
        st.markdown("""
Se sai che il titolo distribuisce e i dati mancano, puoi fornirli tu: copia dal
sito della SET la tabella degli stacchi in un file di testo e salvalo come
`dati/<SIMBOLO>-dividendi.csv`, con due colonne:

```
data,importo
2016-04-25,1.10
2016-09-05,1.10
```

L'app lo legge al posto delle API e lo tratta come la fonte piu' affidabile.
Vedi la scheda **Fonti dei dati** per gli altri archivi disponibili.
""")
    else:
        st.markdown("#### Dieci anni di distribuzione")
        st.markdown("<div class='blocco'>"
                    + "".join(f"<p>{p}</p>" for p in analisi.narrative["dividendi"])
                    + "</div>", unsafe_allow_html=True)

        st.plotly_chart(charts.dividend_history_chart(div, scuro), use_container_width=True)
        st.plotly_chart(charts.yield_history_chart(div, scuro), use_container_width=True)
        due = st.columns(2)
        due[0].plotly_chart(charts.payout_coverage_chart(div, scuro), use_container_width=True)
        due[1].plotly_chart(charts.total_return_chart(div, analisi.data.prices, scuro),
                            use_container_width=True)
        st.plotly_chart(charts.safety_factors_chart(div, scuro), use_container_width=True)

        st.markdown("##### Solidita' del dividendo, fattore per fattore")
        st.caption("Si parte da 50 punti. Ogni fattore aggiunge o toglie punti secondo la "
                   "regola indicata: e' un criterio dichiarato, non un modello statistico "
                   "addestrato su una base storica di tagli. Puoi non essere d'accordo su un "
                   "fattore e rifare il conto.")
        st.dataframe(pd.DataFrame([{
            "Fattore": fattore.label,
            "Valore": (fmt.pct(fattore.value) if fattore.fmt == "pct"
                       else fmt.mult(fattore.value) if fattore.fmt == "x"
                       else fmt.num(fattore.value, 0)),
            "Punti": f"{fattore.points:+.0f}",
            "Perche'": fattore.explanation,
        } for fattore in div.safety.factors]), use_container_width=True, hide_index=True)

        st.markdown("##### La previsione del dividendo, metodo per metodo")
        st.dataframe(pd.DataFrame([{
            "Metodo": metodo.label,
            "Dividendo stimato": (fmt.money(metodo.value, valuta) if metodo.usable
                                  else "non applicabile"),
            "Peso": f"{metodo.weight:.0%}" if metodo.weight else "-",
            "Ipotesi": metodo.detail or metodo.skipped_reason or "",
        } for metodo in div.forecast.methods]), use_container_width=True, hide_index=True)

        st.plotly_chart(charts.backtest_chart(div, scuro), use_container_width=True)

        st.markdown("##### I numeri, anno per anno")
        etichette_div = {
            "dps": f"Dividendo per azione ({valuta})", "stacchi": "Numero di stacchi",
            "prezzo_medio": f"Prezzo medio dell'anno ({valuta})",
            "rendimento": "Rendimento sul prezzo medio",
            "eps": f"Utile per azione ({valuta})", "payout": "Quota di utili distribuita",
            "fcf_per_azione": f"Cassa libera per azione ({valuta})",
            "copertura_cassa": "Copertura con la cassa (volte)",
            "variazione": "Variazione sull'anno precedente",
        }
        tabella_div = div.years[[c for c in etichette_div if c in div.years.columns]].copy()
        tabella_div.index = [str(int(a)) for a in tabella_div.index]
        tabella_div = tabella_div.rename(columns=etichette_div).T
        st.dataframe(tabella_div.style.format("{:,.4g}", na_rep="n/d"),
                     use_container_width=True)
        st.caption("L'ultima colonna e' l'anno in corso: e' incompleto per definizione e non "
                   "entra in nessuna media.")

        if div.notes:
            st.markdown("##### Limiti di questa analisi")
            for nota in div.notes:
                st.markdown(f"- {nota}")

with schede[1]:
    st.markdown("#### Che azienda e' stata")
    st.markdown("<div class='blocco'>" + "".join(f"<p>{p}</p>" for p in analisi.narrative["passato"])
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
    st.markdown("#### Dove si trova adesso")
    st.markdown("<div class='blocco'>" + "".join(f"<p>{p}</p>" for p in analisi.narrative["presente"])
                + "</div>", unsafe_allow_html=True)
    st.plotly_chart(charts.price_chart(m, v, analisi.data.prices, scuro), use_container_width=True)
    due = st.columns(2)
    due[0].plotly_chart(charts.multiple_history_chart(m, "pe", scuro), use_container_width=True)
    due[1].plotly_chart(charts.multiple_history_chart(m, "pb", scuro), use_container_width=True)
    st.plotly_chart(charts.health_chart(m, scuro), use_container_width=True)

with schede[3]:
    st.markdown("#### Cosa aspettarsi a 1-2 anni")
    st.markdown("<div class='blocco'>" + "".join(f"<p>{p}</p>" for p in analisi.narrative["futuro"])
                + "</div>", unsafe_allow_html=True)
    st.plotly_chart(charts.methods_chart(m, v, scuro), use_container_width=True)
    st.markdown("##### I modelli, uno per uno")
    righe = []
    for metodo in v.methods:
        righe.append({
            "Metodo": metodo.label,
            "Valore per azione": fmt.money(metodo.fair_value, valuta) if metodo.usable else "non applicabile",
            "Peso": f"{metodo.weight:.0%}" if metodo.weight else "-",
            "Ipotesi": metodo.detail or metodo.skipped_reason or "",
        })
    st.dataframe(pd.DataFrame(righe), use_container_width=True, hide_index=True)
    st.markdown("##### Quando rimettere in discussione la decisione")
    for innesco in d.review_triggers:
        st.markdown(f"- {innesco}")

with schede[4]:
    st.plotly_chart(charts.pillars_chart(d, scuro), use_container_width=True)
    st.markdown("#### Come nasce il punteggio")
    st.caption("Ogni area e' la media ponderata di alcuni indicatori. Gli indicatori "
               "senza dato non pesano, e la loro assenza abbassa l'affidabilita' complessiva.")
    for pilastro in d.pillars:
        titolo = (f"{pilastro.label} - "
                  f"{'n/d' if pilastro.score is None else f'{pilastro.score:.0f}/100'} "
                  f"(peso {pilastro.weight:.0%})")
        with st.expander(titolo, expanded=pilastro.score is not None and pilastro.score < 45):
            st.caption(pilastro.question)
            st.dataframe(pd.DataFrame([{
                "Indicatore": criterio.label,
                "Valore": criterio.formatted(),
                "Punteggio": "n/d" if criterio.score is None else f"{criterio.score:.0f}",
                "Peso": f"{criterio.weight:.1f}",
                "Nota": criterio.note,
            } for criterio in pilastro.criteria]), use_container_width=True, hide_index=True)

with schede[5]:
    st.markdown("#### I numeri, esercizio per esercizio")
    st.caption("La tabella completa: ogni grafico di questa pagina nasce da qui.")
    if m.years is not None and not m.years.empty:
        etichette = {
            "revenue": "Ricavi", "gross_profit": "Utile lordo", "operating_income": "Utile operativo",
            "ebitda": "EBITDA", "net_income": "Utile netto", "eps": "Utile per azione",
            "dps": "Dividendo per azione", "equity": "Patrimonio netto", "total_assets": "Attivo totale",
            "total_debt": "Debito totale", "net_debt": "Debito netto", "cash": "Cassa",
            "cfo": "Cassa dall'attivita'", "capex": "Investimenti", "fcf": "Cassa libera",
            "gross_margin": "Margine lordo", "operating_margin": "Margine operativo",
            "net_margin": "Margine netto", "roe": "ROE", "roic": "ROIC", "roa": "ROA",
            "net_debt_ebitda": "Debito netto / EBITDA", "debt_equity": "Debito / patrimonio",
            "interest_coverage": "Copertura interessi", "current_ratio": "Liquidita' corrente",
            "equity_ratio": "Patrimonio / attivo", "payout": "Utili distribuiti",
        }
        tabella = m.years[[c for c in etichette if c in m.years.columns]].copy()
        tabella.index = [data.strftime("%Y") for data in tabella.index]
        tabella = tabella.rename(columns=etichette).T
        st.dataframe(tabella.style.format("{:,.4g}", na_rep="n/d"), use_container_width=True)
    else:
        st.warning("Nessun bilancio disponibile su Yahoo Finance per questo titolo.")

    st.markdown("#### Ultimi dodici mesi e multipli")
    sintesi = {
        "Ricavi (12 mesi)": fmt.big(m.ttm.get("revenue"), valuta),
        "Utile netto (12 mesi)": fmt.big(m.ttm.get("net_income"), valuta),
        "Cassa libera (12 mesi)": fmt.big(m.ttm.get("fcf"), valuta),
        "Utile per azione (12 mesi)": fmt.money(m.ttm.get("eps"), valuta),
        "Capitalizzazione": fmt.big(m.market_cap, valuta),
        "P/E": fmt.mult(m.valuation.get("pe")),
        "P/B": fmt.mult(m.valuation.get("pb")),
        "EV/EBITDA": fmt.mult(m.valuation.get("ev_ebitda")),
        "Rendimento cassa libera": fmt.pct(m.valuation.get("fcf_yield")),
        "Dividendo": fmt.pct(m.dividend.get("yield_current")),
        "Beta contro indice SET": fmt.ratio(m.trend.get("beta")),
        "Volatilita' annua": fmt.pct(m.trend.get("volatility")),
        "Rendimento richiesto (modelli)": fmt.pct(v.cost_of_equity),
    }
    st.dataframe(pd.DataFrame({"Voce": list(sintesi), "Valore": list(sintesi.values())}),
                 use_container_width=True, hide_index=True)

with schede[6]:
    st.markdown("#### Da dove arrivano i dividendi")
    if div is not None and div.source is not None:
        st.markdown(f"**Serie usata:** {div.source.provenance()}")
        righe_fonti = []
        for risultato in div.source.results:
            righe_fonti.append({
                "Fonte": risultato.label,
                "Fiducia": "*" * risultato.trust,
                "Esito": (f"{risultato.payments} stacchi su {risultato.span_years:.1f} anni"
                          if risultato.ok else (risultato.error or "nessun dato")),
                "Usata": "si" if risultato.key == div.source.chosen else "",
                "Note": risultato.note,
            })
        if righe_fonti:
            st.dataframe(pd.DataFrame(righe_fonti), use_container_width=True, hide_index=True)
        if div.source.disagreements:
            st.markdown("**Le fonti non concordano su tutto:**")
            for avviso in div.source.disagreements:
                st.markdown(f"<div class='avviso'>{avviso}</div>", unsafe_allow_html=True)
            st.caption("Non tentiamo di riconciliare: su un dato come il dividendo sapere che "
                       "due archivi non concordano vale piu' di una media fra i due. "
                       "Il sito della SET e' l'arbitro.")
    else:
        st.caption("Nessuna informazione sulla provenienza dei dividendi.")

    st.markdown("#### Tutte le fonti disponibili")
    st.caption("Lo strumento interroga ogni archivio attivo e confronta i risultati. Le fonti "
               "che richiedono una chiave sono gratuite: registrati sul sito del servizio e "
               "metti la chiave nella variabile d'ambiente indicata.")
    st.dataframe(pd.DataFrame([{
        "Fonte": riga["fonte"],
        "Fiducia": "*" * riga["fiducia"],
        "Variabile d'ambiente": riga["chiave_api"],
        "Attiva adesso": "si" if riga["attiva"] else "no",
        "Note": riga["nota"],
    } for riga in describe_sources()]), use_container_width=True, hide_index=True)
    with st.expander("Come fornire i dividendi a mano (funziona sempre)"):
        st.markdown("""
Nessuna API e' garantita nel tempo. Questa strada no: copia dal sito della SET la
tabella degli stacchi e salvala come `dati/<SIMBOLO>-dividendi.csv`.

```
data,importo
2016-04-25,1.10
2016-09-05,1.10
2017-04-24,1.20
```

Vanno bene anche `date,dividend`, il punto e virgola come separatore e la virgola
decimale. Le date si leggono con il giorno prima del mese, come scrive la SET.
Il file viene trattato come la fonte piu' affidabile e usato al posto delle API.
""")

    st.markdown("#### Cosa e' stato trovato negli altri dati")
    copertura = analisi.data.data_coverage()
    st.dataframe(pd.DataFrame({
        "Dato": list(copertura),
        "Disponibile": ["si" if valore else "no" for valore in copertura.values()],
    }), use_container_width=True, hide_index=True)
    limiti = list(m.notes) + list(v.notes) + list(analisi.data.warnings)
    if limiti:
        st.markdown("#### Limiti da tenere presenti")
        for nota in limiti:
            st.markdown(f"- {nota}")
    st.markdown("#### Metodo")
    st.markdown("""
**Il segnale sui dividendi.** Il rendimento di oggi (ultimi stacchi su base annua
diviso il prezzo) viene confrontato con la propria storia giornaliera degli ultimi
dieci anni. Il valore stimato assume che il rendimento chiuda **meta'** dello scarto
verso la sua mediana entro due anni: un ritorno completo alla media sarebbe una
scommessa sul fatto che azienda e mercato tornino quelli di prima. Quando la
solidita' del dividendo scende sotto 60 punti, il rendimento obiettivo viene alzato
fino al +90%, perche' un dividendo fragile merita in modo permanente un rendimento
piu' alto. Quando il rischio di taglio e' alto, la valutazione usa il dividendo
dello **scenario pessimistico**, non quello attuale.

Il punteggio complessivo (0-100) e' la media ponderata di cinque aree:
valutazione 25%, qualita' del business 20%, crescita 20%, solidita' finanziaria
20%, tendenza del prezzo 15%. La tendenza pesa poco perche' l'orizzonte e' di
1-2 anni.

Il valore stimato nasce da quattro modelli indipendenti - multiplo storico,
dividendi scontati, flussi di cassa scontati, valore di libro giustificato -
pesati secondo il tipo di azienda. La decisione finale incrocia punteggio e
rendimento atteso, ma i problemi gravi di bilancio hanno la precedenza: due
problemi gravi portano a **vendere** anche con un punteggio alto.

I dati vengono da Yahoo Finance, che per i titoli thailandesi espone di norma
gli ultimi quattro esercizi di bilancio e oltre dieci anni di prezzi. Dove un
dato manca viene dichiarato, non stimato.
""")

st.divider()
report = analisi.report()
colonne = st.columns([1, 1, 3])
colonne[0].download_button("Scarica il report (markdown)", data=report.encode("utf-8"),
                           file_name=f"setxray-{m.symbol}.md", mime="text/markdown",
                           use_container_width=True)
if m.years is not None and not m.years.empty:
    csv = io.StringIO()
    m.years.to_csv(csv)
    colonne[1].download_button("Scarica i dati (CSV)", data=csv.getvalue().encode("utf-8"),
                               file_name=f"setxray-{m.symbol}.csv", mime="text/csv",
                               use_container_width=True)
colonne[2].caption("Elaborazione automatica di dati pubblici. Non e' consulenza finanziaria "
                   "ne' una raccomandazione personalizzata: verifica sempre i numeri sui bilanci "
                   "ufficiali della societa' e sul sito della Stock Exchange of Thailand.")
