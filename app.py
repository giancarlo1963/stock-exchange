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
from setxray.datasource import clear_cache
from setxray.demo import PROFILE_KEYS, profile_names, profiles
from setxray.engine import Analysis, NoDataError, analyze
from setxray.lang import CODES, L, NAMES, action_label, normalize, set_language
from setxray.universe import Universo, load_universe
from setxray.scoring import BUY, HOLD, SELL
from setxray.sources import describe_sources

# La lingua si fissa prima di ogni altra cosa: da qui in giu' ogni L() la
# legge, compreso il titolo della pagina. Sta nell'indirizzo (?lang=it) perche'
# un collegamento condiviso deve aprirsi nella lingua di chi lo ha mandato, e
# nello stato della sessione perche' sopravviva a un clic sui pulsanti.
# L'indirizzo vince quando *cambia*, non a ogni giro: un collegamento con
# ?lang=it deve aprirsi in italiano, ma la pagina riscrive ?lang= da sola a
# ogni rerun, e dare sempre la precedenza all'indirizzo annullava il clic
# sull'interruttore un istante dopo averlo fatto. Percio' si ricorda l'ultimo
# valore letto: se quello nell'indirizzo e' diverso, qualcuno e' arrivato da
# fuori e ha ragione lui.
_DA_URL = normalize(st.query_params["lang"]) if st.query_params.get("lang") else None
if _DA_URL and _DA_URL != st.session_state.get("_lingua_indirizzo"):
    st.session_state["_lingua_indirizzo"] = _DA_URL
    st.session_state["lingua"] = _DA_URL
_LINGUA = set_language(st.session_state.get("lingua") or _DA_URL or "en")

st.set_page_config(page_title=L("SET X-Ray - Thai stock dividends and analysis",
                                "SET X-Ray - dividendi e analisi azioni Thailandia"),
                   page_icon="📊", layout="wide")

VERDICT_STYLE = {
    BUY: ("#0ca30c", L("Buy or accumulate", "Comprare o accumulare")),
    HOLD: ("#fab219", L("Hold, without adding", "Tenere, senza aumentare")),
    SELL: ("#d03b3b", L("Sell or reduce", "Vendere o ridurre")),
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


@st.cache_data(show_spinner=False, ttl=24 * 3600)
def _universo_cached(completo: bool, lang: str) -> Universo:
    """L'elenco dei titoli SET.

    `completo=False` non tocca la rete: legge la cache su disco o il CSV, e se
    non ci sono si accontenta dell'elenco corto. Interrogare la SET e lo
    screener di Yahoo puo' costare decine di secondi, e nessuno deve
    aspettarli per vedere apparire la pagina: la strada lunga si prende solo
    quando qualcuno la chiede, e da quel momento la cache su disco la rende
    gratis per una settimana.
    """
    set_language(lang)
    return load_universe(offline=not completo)


@st.cache_data(show_spinner=False, ttl=1800)
def _analyze_cached(symbol: str, risk_free: float, erp: float, lang: str) -> Analysis:
    """Una richiesta per simbolo, ipotesi e lingua: Yahoo non ama le raffiche.

    La lingua entra nella chiave perche' le frasi nascono dentro il motore e
    restano dentro l'oggetto: la stessa analisi in due lingue sono due
    risultati diversi. I dati grezzi non si riscaricano comunque - quelli hanno
    la loro cache su disco - quindi cambiare lingua costa un ricalcolo, non
    una rete.
    """
    set_language(lang)
    return analyze(symbol, risk_free=risk_free, erp=erp)


def card(label: str, value: str, note: str = "", colour: str = "") -> str:
    # Nessuna L() qui: e' HTML, uguale nelle due lingue. Con la L() la seconda
    # meta' leggeva una variabile omonima definita altrove nella pagina, e in
    # italiano la card prendeva il colore del verdetto invece del suo.
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
    # L'interruttore in cima, prima di tutto il resto: chi apre la pagina nella
    # lingua sbagliata lo trova subito, senza scorrere.
    st.caption(L(f"Dividends and fundamental analysis - Stock Exchange of Thailand - version "
                 f"{__version__}",
                 f"Dividendi e analisi fondamentale - Borsa di Thailandia - versione {__version__}"))

    simbolo = st.text_input(L("SET symbol",
                              "Simbolo SET"), value=st.session_state.get("simbolo", "PTT"),
                            help=L("For example PTT, AOT, CPALL, SCB. The .BK suffix is optional.",
                                   "Per esempio PTT, AOT, CPALL, SCB. Il suffisso .BK e' "
                                   "facoltativo."))
    avvia = st.button(L("Analyse", "Analizza"), type="primary", use_container_width=True)

    # --- scegliere da un elenco invece di indovinare una sigla ------------
    # La casella sopra resta: accetta qualunque sigla, anche una quotata ieri
    # che nessun elenco conosce ancora. Questo serve a chi non la sa a memoria.
    # La rotella solo quando si prende la strada lunga: la prima volta puo'
    # durare dei secondi, e una pagina ferma senza spiegazione sembra rotta.
    _completo = bool(st.session_state.get("universo_completo"))
    if _completo:
        with st.spinner(L("Fetching every SET symbol...",
                          "Scarico tutti i simboli della SET...")):
            _universo = _universo_cached(True, _LINGUA)
    else:
        _universo = _universo_cached(False, _LINGUA)
    _scelto = st.selectbox(
        L(f"Or pick from the list ({len(_universo)})",
          f"Oppure scegli dall'elenco ({len(_universo)})"),
        _universo.titoli, index=None,
        format_func=lambda titolo: titolo.etichetta(),
        placeholder=L("Type a symbol or a company name...",
                      "Scrivi una sigla o un nome di azienda..."),
        key="scelta-elenco",
    )
    if _scelto is not None and _scelto.symbol != st.session_state.get("simbolo"):
        st.session_state["simbolo"] = _scelto.symbol
        st.session_state["esegui"] = True
        st.rerun()

    if _universo.parziale:
        # L'elenco corto non e' il mercato, e va detto: chi non lo sapesse
        # penserebbe che alla SET sono quotate sedici societa'.
        if st.button(L("Fetch every SET symbol", "Scarica tutti i simboli della SET"),
                     use_container_width=True,
                     help=L("Asks the SET website and Yahoo once, then keeps the list for a week.",
                            "Interroga una volta il sito della SET e Yahoo, poi tiene l'elenco "
                            "per una settimana.")):
            st.session_state["universo_completo"] = True
            _universo_cached.clear()
            st.rerun()
    st.caption(_universo.provenienza())

    with st.expander(L("Try it without internet (made-up data)",
                       "Prova senza internet (dati finti)")):
        st.caption(L("Six invented companies, to see how the analysis behaves in the typical "
                     "cases. The numbers are not real.",
                     "Quattro aziende inventate, per vedere come funziona l'analisi "
                     "nei casi tipici. I numeri non sono reali."))
        descrizioni, nomi = profiles(), profile_names()
        for profilo in PROFILE_KEYS:
            descrizione, nome = descrizioni[profilo], nomi.get(profilo, profilo)
            if st.button(L(f"Demo: {nome}",
                           f"Demo: {profilo}"), key=f"demo-{profilo}", help=descrizione,
                         use_container_width=True):
                st.session_state["simbolo"] = f"demo:{profilo}"
                st.session_state["esegui"] = True
                st.rerun()

    with st.expander(L("Valuation assumptions", "Ipotesi di valutazione")):
        st.caption(L("These change the return you demand from the investment, and therefore the "
                     "estimated value.",
                     "Cambiano il rendimento che pretendi dall'investimento, quindi il valore "
                     "stimato."))
        tasso = st.slider(L("Risk-free rate (Thailand, 10 years)",
                            "Tasso privo di rischio (Thailandia, 10 anni)"), 0.5, 6.0, 2.8, 0.1,
                          format="%.1f%%") / 100
        premio = st.slider(L("Equity risk premium",
                             "Premio per il rischio azionario"), 3.0, 12.0, 7.5, 0.5,
                           format="%.1f%%") / 100
        if st.button(L("Clear the data cache",
                       "Svuota la cache dei dati"), use_container_width=True):
            rimossi = clear_cache()
            _analyze_cached.clear()
            st.success(L(f"Cache cleared ({rimossi} files).",
                         f"Cache svuotata ({rimossi} file)."))

    st.divider()
    attive = [riga["source"] for riga in describe_sources() if riga["active"]]
    st.caption(L(f"Dividends from {len(attive)} active sources · prices and statements from Yahoo "
                 "Finance. See the *Data sources* tab. This is not financial advice.",
                 f"Dividendi da {len(attive)} fonti attive · prezzi e bilanci da Yahoo Finance. "
                 "Vedi la scheda *Fonti dei dati*. Non e' consulenza finanziaria."))

if avvia:
    st.session_state["simbolo"] = simbolo
    st.session_state["esegui"] = True

# --------------------------------------------------------------------------
# la lingua: in cima alla pagina, non nella barra laterale
# --------------------------------------------------------------------------
# Stava nella barra laterale, che sul telefono Streamlit apre chiusa: chi
# arrivava da li' non la vedeva e non aveva modo di sapere che ci fosse. Qui
# e' la prima cosa della pagina, su entrambi gli schermi, e ce n'e' una sola:
# due controlli per la stessa scelta si contraddicono il giorno in cui uno dei
# due non viene aggiornato.
# Un radio orizzontale e non due pulsanti in colonne: sul telefono le colonne
# di Streamlit si impilano, e due pulsanti a piena larghezza in cima alla
# pagina rubano la scena a quello che c'e' sotto. Il radio resta su una riga a
# qualunque larghezza, e non si puo' deselezionare - una lingua "nessuna" non
# esiste.
#
# Cambiare lingua rifa l'analisi: le frasi nascono dentro il motore e sono
# state costruite nella lingua di prima. I dati non si riscaricano - hanno la
# loro cache su disco - quindi costa un ricalcolo, non una rete.
# L'etichetta resta visibile: senza, due parole con un pallino in cima alla
# pagina si possono prendere per decorazione. Con scritto "Lingua" sopra, si
# capisce che e' un comando anche senza toccarlo.
st.radio(L("Language", "Lingua"), CODES, key="lingua", horizontal=True,
         index=CODES.index(_LINGUA), format_func=lambda codice: NAMES[codice])
if _DA_URL != _LINGUA:
    st.session_state["_lingua_indirizzo"] = _LINGUA
    st.query_params["lang"] = _LINGUA

if not st.session_state.get("esegui"):
    st.title(L("Dividends and analysis of a Stock Exchange of Thailand share",
               "Dividendi e analisi di un'azione della Borsa di Thailandia"))
    st.markdown(L("""
  Type the symbol of a stock listed on the **SET** in Bangkok (for example `PTT`,
  `AOT`, `CPALL`) and press **Analyse**.
  
  The tool is built around one question: **how has this stock paid dividends over
  the last ten years, and what does that history say about what to do today?** It
  reconstructs every payment, measures growth, cuts and continuity, works out how
  much of the total return came from the coupons, estimates what it will pay over
  the next two years, and ends with **buy, hold or sell** and the reasons why.
  
  The horizon is **one to two years at the very least**: this is not a tool for
  short-term trading.
  """,
                  """
  Scrivi il simbolo di un titolo quotato alla **SET** di Bangkok (per esempio `PTT`,
  `AOT`, `CPALL`) e premi **Analizza**.
  
  Lo strumento e' costruito attorno a una domanda: **come ha distribuito dividendi
  questo titolo negli ultimi dieci anni, e cosa dice quella storia su cosa fare
  oggi?** Ricostruisce ogni stacco, misura crescita, tagli e continuita', calcola
  quanto del rendimento totale e' arrivato dalle cedole, stima cosa paghera' nei
  prossimi due anni, e conclude con **comprare, mantenere o vendere** spiegando
  il perche'.
  
  L'orizzonte e' **1-2 anni minimo**: non e' uno strumento per il trading di breve.
  """))
    colonne = st.columns(3)
    with colonne[0]:
        st.markdown(L("#### Ten years of coupons", "#### Dieci anni di cedole"))
        st.caption(L("Dividend per share year by year, average growth over 3, 5 and 10 years, "
                     "cuts and skipped years, and how much of the total return came from the "
                     "coupons rather than from the price.",
                     "Dividendo per azione anno per anno, crescita media a 3, 5 e 10 anni, "
                     "tagli e anni saltati, e quanta parte del rendimento totale e' arrivata "
                     "dalle cedole invece che dal prezzo."))
    with colonne[1]:
        st.markdown(L("#### Will the dividend hold?", "#### Il dividendo regge?"))
        st.caption(L("A safety score built from factors you can see one by one: cover from "
                     "earnings, cover from real cash, debt, the trend in earnings, the history "
                     "of cuts, continuity.",
                     "Un punteggio di solidita' costruito da fattori visibili uno per uno: "
                     "copertura con gli utili, copertura con la cassa vera, debito, andamento "
                     "degli utili, storia dei tagli, continuita'."))
    with colonne[2]:
        st.markdown(L("#### Buy or sell, and why", "#### Comprare o vendere, e perche'"))
        st.caption(L("Today's yield against the stock's own history, the two-year dividend "
                     "forecast, and a backtest of how this signal behaved on this very stock.",
                     "Il rendimento di oggi confrontato con la storia del titolo, la previsione "
                     "del dividendo a due anni, e una verifica retrospettiva di come si e' "
                     "comportato questo segnale su questo stesso titolo."))
    st.info(L("No internet, or you just want to see what it looks like? Open **Try it without "
              "internet** in the sidebar: six invented companies cover the typical cases, "
              "including a dividend that was cut and an irregular payer.",
              "Non hai internet o vuoi solo vedere com'e' fatta? Apri **Prova senza "
              "internet** nella barra a sinistra: sei aziende inventate coprono i casi tipici, "
              "compreso un dividendo tagliato e un pagatore irregolare."), icon="💡")
    with st.expander(L("Where the dividend data comes from",
                       "Da dove arrivano i dati sui dividendi")):
        st.caption(L("The tool queries several archives and compares the results, because on SET "
                     "stocks the dividend is the figure that is easiest to get wrong.",
                     "Lo strumento interroga piu' archivi e confronta i risultati, perche' sui "
                     "titoli SET i dividendi sono il dato piu' facile da sbagliare."))
        st.dataframe(pd.DataFrame([{
            L("Source", "Fonte"): riga["source"],
            L("Needs a key", "Serve una chiave"): riga["api_key"],
            L("Active now", "Attiva adesso"): L("yes", "si") if riga["active"] else "no",
            L("Notes", "Note"): riga["note"],
        } for riga in describe_sources()]), use_container_width=True, hide_index=True)
    st.stop()

# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------
richiesto = st.session_state.get("simbolo", "PTT")
if st.query_params.get(L("symbol", "simbolo")) != richiesto:
    st.query_params["symbol"] = richiesto
try:
    with st.spinner(L(f"Fetching and analysing {richiesto}...",
                      f"Scarico e analizzo {richiesto}...")):
        analisi = _analyze_cached(richiesto, tasso, premio, _LINGUA)
except NoDataError as errore:
    st.error(str(errore), icon="⚠️")
    st.stop()
except ValueError as errore:
    st.error(L(f"Invalid symbol: {errore}", f"Simbolo non valido: {errore}"), icon="⚠️")
    st.stop()
except Exception as errore:  # network, Yahoo rate limit, unexpected formats
    st.error(L(f"The analysis could not be completed: {type(errore).__name__} - {errore}",
               f"Non e' stato possibile completare l'analisi: {type(errore).__name__} - {errore}"),
             icon="⚠️")
    st.info(L("If it keeps happening, try clearing the data cache in the sidebar, or come back "
              "in a few minutes: Yahoo Finance limits how many requests it accepts.",
              "Se il problema si ripete, prova a svuotare la cache dei dati "
              "nella barra a sinistra, o riprova fra qualche minuto: Yahoo Finance "
              "limita il numero di richieste."))
    st.stop()

m, v, d = analisi.metrics, analisi.valuation, analisi.verdict
scuro = st.get_option("theme.base") == "dark"
valuta = m.currency

if analisi.data.is_demo:
    st.warning(L("**Demo mode.** Invented company and synthetic numbers: they exist only to show "
                 "how the app works. Do not use them to decide anything.",
                 "**Modalita' dimostrativa.** Societa' inventata e numeri sintetici: "
                 "servono solo a mostrare come funziona l'app. Non usarli per decidere."), icon="🧪")

# Yahoo, quando decide che le richieste sono troppe, non risponde con un
# errore: risponde con una tabella vuota. Cosi' capita che di un titolo arrivi
# la scheda anagrafica intera - nome, settore, prezzo di oggi - e non arrivi un
# solo prezzo storico. L'analisi resta in piedi, ma tutto quello che nasce dalla
# serie dei prezzi (il grafico del prezzo, l'RSI, il confronto con l'indice, lo
# storico dei multipli) diventa un riquadro vuoto, e chi guarda pensa che manchi
# il grafico invece del dato. Va detto qui, in cima, una volta, con il pulsante
# per riprovare accanto: e' un problema che passa da solo dopo qualche minuto.
_storico = analisi.data.prices
_sessioni = 0 if _storico is None else len(_storico)
if not analisi.data.is_demo and _sessioni <= charts.RSI_PERIODS:
    st.warning(
        L(f"**Yahoo did not return the daily price history for {m.symbol}** "
          f"({_sessioni} sessions received; the RSI needs at least "
          f"{charts.RSI_PERIODS + 1}). Everything based on the price series is empty: the price "
          "chart, the RSI, the comparison with the index and the history of the multiples. "
          "The rest of the analysis - dividends, financial statements, valuation - is unaffected. "
          "It is almost always Yahoo limiting requests, and it passes: try again in a minute.",
          f"**Yahoo non ha restituito lo storico dei prezzi di {m.symbol}** "
          f"({_sessioni} sessioni ricevute, all'RSI ne servono almeno "
          f"{charts.RSI_PERIODS + 1}). Tutto quello che nasce dalla serie dei prezzi resta "
          "vuoto: il grafico del prezzo, l'RSI, il confronto con l'indice e lo storico dei "
          "multipli. Il resto dell'analisi - dividendi, bilanci, valutazione - non ne soffre. "
          "Quasi sempre e' Yahoo che limita le richieste, e passa: riprova fra un minuto."),
        icon="📉")
    if st.button(L("Download the prices again", "Riscarica i prezzi"), key="riprova-prezzi"):
        # Serve svuotare la cache del *risultato*: quella su disco non tiene i
        # dati senza prezzi, ma l'analisi calcolata resta valida mezz'ora.
        _analyze_cached.clear()
        st.rerun()

st.markdown(f"## {m.name}")
sottotitolo = [f"`{m.symbol}`"]
if m.sector:
    sottotitolo.append(m.sector)
if m.industry:
    sottotitolo.append(m.industry)
sottotitolo.append(L(f"data as of {fmt.date(m.trend.get('last_date'))}",
                     f"dati al {fmt.date(m.trend.get('last_date'))}"))
if analisi.data.from_cache:
    sottotitolo.append(L("from local cache", "da cache locale"))
# La versione qui e non solo nella barra laterale: sul telefono la barra e'
# chiusa, e quando si aspetta un aggiornamento la prima domanda e' "e'
# arrivato?". Una riga che risponde da sola vale i sei caratteri che occupa.
sottotitolo.append(f"v{__version__}")
st.caption(" · ".join(sottotitolo))

# --- the dividend answer, before everything else --------------------------
div = analisi.dividends
segnale = div.signal if (div and div.pays_dividends and div.signal) else None

if segnale is not None:
    colore, spiegazione = VERDICT_STYLE[segnale.action]
    sicurezza = div.safety
    st.markdown(
        L(f"<div class='verdict' style='background:{colore}'>"
          f"<h1>{segnale.headline}</h1><p>{spiegazione} · horizon 1-2 years · "
          f"dividend safety {fmt.num(sicurezza.score, 0)}/100 ({sicurezza.band}) · "
          f"cut risk {sicurezza.cut_risk_band}</p></div>",
          f"<div class='verdict' style='background:{colore}'>"
          f"<h1>{segnale.headline}</h1><p>{spiegazione} · orizzonte 1-2 anni · "
          f"solidita' del dividendo {fmt.num(sicurezza.score, 0)}/100 ({sicurezza.band}) · "
          f"rischio di taglio {sicurezza.cut_risk_band}</p></div>"),
        unsafe_allow_html=True,
    )

    rendimento = div.yield_stats
    colonne = st.columns(4)
    percentile = rendimento.get("percentile")
    nota_percentile = ("" if percentile is None
                       else L(f"more generous than {fmt.pct(percentile)} of its own history",
                              f"piu' generoso del {fmt.pct(percentile)} della sua storia"))
    colonne[0].markdown(card(
        L("Yield today", "Rendimento oggi"), fmt.pct(rendimento.get("attuale")),
        L(f"historical median {fmt.pct(rendimento.get('mediana'))} · {nota_percentile}",
          f"mediana storica {fmt.pct(rendimento.get('mediana'))} · {nota_percentile}"),
    ), unsafe_allow_html=True)
    previsione = div.forecast
    colonne[1].markdown(card(
        L("Dividend per share",
          "Dividendo per azione"), fmt.money(rendimento.get("dps_indicato"), valuta),
        (L(f"next 12 months estimated at {fmt.money(previsione.year1_base, valuta)}",
           f"stima prossimi 12 mesi {fmt.money(previsione.year1_base, valuta)}")
         if previsione and previsione.ok else L("annualised, most recent payments",
                                                "su base annua, ultimi stacchi")),
    ), unsafe_allow_html=True)
    atteso = segnale.expected_return_2y
    colonne[2].markdown(card(
        L("Expected return over 2 years", "Rendimento atteso a 2 anni"), fmt.pct(atteso, sign=True),
        (L(f"{fmt.pct(segnale.income_component, sign=True)} from coupons and "
           f"{fmt.pct(segnale.price_component, sign=True)} from the price",
           f"{fmt.pct(segnale.income_component, sign=True)} di cedole e "
           f"{fmt.pct(segnale.price_component, sign=True)} di prezzo")),
        colour="#0ca30c" if (atteso or 0) > 0.08 else "#d03b3b" if (atteso or 0) < 0 else "",
    ), unsafe_allow_html=True)
    etichetta = (L("Buy below",
                   "Compra sotto") if segnale.action != SELL else L("Would become interesting below",
                                                              "Tornerebbe interessante sotto"))
    colonne[3].markdown(card(
        etichetta, fmt.money(segnale.entry_price, valuta),
        L(f"estimated value {fmt.money(segnale.fair_price, valuta)} · "
          f"trim above {fmt.money(segnale.exit_price, valuta)}",
          f"valore stimato {fmt.money(segnale.fair_price, valuta)} · "
          f"alleggerisci sopra {fmt.money(segnale.exit_price, valuta)}"),
    ), unsafe_allow_html=True)

    st.markdown(L("### Why", "### Perche'"))
    for motivo in segnale.reasons:
        st.markdown(f"- {motivo}")

    # The general verdict as a confirmation or as a contradiction: when the two
    # models diverge the user must be told, not handed an average.
    generale = d.expected_return_2y
    st.markdown(
        L(f"<div class='secondary'><div class='heading'>General fundamental analysis "
          f"(earnings, cash, equity, debt)</div>"
          f"<b>{d.headline}</b> · score {fmt.num(d.composite, 0)}/100 · "
          f"expected return {fmt.pct(generale, sign=True)}",
          f"<div class='secondary'><div class='heading'>Analisi fondamentale generale "
          f"(utili, cassa, patrimonio, debito)</div>"
          f"<b>{d.headline}</b> · punteggio {fmt.num(d.composite, 0)}/100 · "
          f"rendimento atteso {fmt.pct(generale, sign=True)}")
        + (L("<br><span style='font-size:0.88rem;opacity:0.85'>The price looks low against "
             "earnings, but the red flags in the accounts win out: this is the classic profile "
             "of a value trap.</span>",
             "<br><span style='font-size:0.88rem;opacity:0.85'>Il prezzo sembra basso sugli "
             "utili, ma i campanelli d'allarme sui conti prevalgono: e' il profilo tipico di "
             "una trappola di valore.</span>")
           if d.action == SELL and (generale or 0) > 0.10 else "")
        + "</div>",
        unsafe_allow_html=True,
    )
    if d.action != segnale.action:
        st.markdown(
            L(f"<div class='disagreement'><b>The two models disagree.</b> "
              f"On dividends the signal is <b>{action_label(segnale.action)}</b>, on general "
              f"fundamentals "
              f"<b>{action_label(d.action)}</b>. This is not a bug: they look at different things. "
              f"The dividend "
              "model weighs how sustainable the coupon is, the general one weighs earnings and "
              "equity. If you are after income, follow the first and read the second as a "
              "warning; if you are after capital growth, the other way round.</div>",
              f"<div class='disagreement'><b>I due modelli non concordano.</b> "
              f"Sui dividendi il segnale e' <b>{action_label(segnale.action)}</b>, sui "
              f"fondamentali generali "
              f"<b>{action_label(d.action)}</b>. Non e' un errore: guardano cose diverse. Il "
              f"modello sui "
              "dividendi pesa la sostenibilita' della cedola, quello generale pesa utili e "
              "patrimonio. Se ti interessa il reddito, segui il primo e leggi il secondo come "
              "avvertimento; se ti interessa la crescita del capitale, il contrario.</div>"),
            unsafe_allow_html=True,
        )
else:
    colore, spiegazione = VERDICT_STYLE[d.action]
    st.markdown(
        L(f"<div class='verdict' style='background:{colore}'>"
          f"<h1>{d.headline}</h1><p>{spiegazione} · horizon 1-2 years · "
          f"score {fmt.num(d.composite, 0)}/100 · "
          f"data reliability: {d.data_quality}</p></div>",
          f"<div class='verdict' style='background:{colore}'>"
          f"<h1>{d.headline}</h1><p>{spiegazione} · orizzonte 1-2 anni · "
          f"punteggio {fmt.num(d.composite, 0)}/100 · "
          f"affidabilita' dei dati: {d.data_quality}</p></div>"),
        unsafe_allow_html=True,
    )
    st.warning(L("**This stock pays no dividend** according to the sources available, so the "
                 "verdict above comes from the general fundamental analysis. The *Dividends* tab "
                 "explains what to do if you know that it does pay one.",
                 "**Questo titolo non distribuisce dividendi** secondo le fonti disponibili, "
                 "quindi il giudizio qui sopra viene dall'analisi fondamentale generale. "
                 "La scheda *Dividendi* spiega cosa fare se sai che invece distribuisce."),
               icon="ℹ️")
    colonne = st.columns(4)
    colonne[0].markdown(card(L("Price today", "Prezzo oggi"), fmt.money(m.price, valuta),
                             L(f"52 weeks: {fmt.num(m.trend.get('low_52w'))} - "
                               f"{fmt.num(m.trend.get('high_52w'))}",
                               f"52 settimane: {fmt.num(m.trend.get('low_52w'))} - "
                               f"{fmt.num(m.trend.get('high_52w'))}")), unsafe_allow_html=True)
    colonne[1].markdown(card(L("Estimated value", "Valore stimato"), fmt.money(v.fair_base, valuta),
                             L(f"range {fmt.num(v.fair_bear)} - {fmt.num(v.fair_bull)}",
                               f"forchetta {fmt.num(v.fair_bear)} - {fmt.num(v.fair_bull)}")),
                        unsafe_allow_html=True)
    colonne[2].markdown(card(L("Expected return over 2 years", "Rendimento atteso a 2 anni"),
                             fmt.pct(d.expected_return_2y, sign=True),
                             L(f"{fmt.pct(d.expected_annualized, sign=True)} a year",
                               f"{fmt.pct(d.expected_annualized, sign=True)} all'anno")),
                        unsafe_allow_html=True)
    colonne[3].markdown(card(L("Entry price", "Prezzo d'ingresso"),
                             fmt.money(d.entry_price, valuta) if d.entry_price else fmt.na(),
                             L("below this price the +20% target stays within reach",
                               "sotto questo prezzo l'obiettivo del +20% resta raggiungibile")),
                        unsafe_allow_html=True)
    st.markdown(L("### Why", "### Perche'"))
    for motivo in d.reasons:
        st.markdown(f"- {motivo}")

st.info(d.position_note, icon="💼")

if d.grave_flags or d.warning_flags:
    st.markdown(L("### Red flags in the accounts", "### Campanelli d'allarme sui conti"))
    for flag in d.grave_flags:
        st.markdown(L(f"<div class='serious'><b>Serious</b> - {flag.text}</div>",
                      f"<div class='serious'><b>Grave</b> - {flag.text}</div>"),
                    unsafe_allow_html=True)
    for flag in d.warning_flags:
        st.markdown(L(f"<div class='warning'><b>Watch out</b> - {flag.text}</div>",
                      f"<div class='warning'><b>Attenzione</b> - {flag.text}</div>"),
                    unsafe_allow_html=True)


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------
schede = st.tabs([L("Dividends (10 years)",
                    "Dividendi (10 anni)"), L("Past",
                                                                      "Passato"), L("Present",
                                                                                            "Presente"), L("Future",
                                                                                                                      "Futuro"),
                  L("Score detail",
                    "Dettaglio dei punteggi"), L("Tables",
                                                                 "Tabelle"), L("Data sources",
                                                                                         "Fonti dei dati")])

with schede[0]:
    if segnale is None:
        st.markdown(L("#### No dividend on record", "#### Nessun dividendo registrato"))
        for nota in (div.notes if div else []):
            st.markdown(f"- {nota}")
        st.markdown(L("""
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
  """,
                      """
  Se sai che il titolo distribuisce e i dati mancano, puoi fornirli tu: copia dal
  sito della SET la tabella degli stacchi in un file di testo e salvalo come
  `data/<SIMBOLO>-dividends.csv`, con due colonne:
  
  ```
  date,dividend
  2016-04-25,1.10
  2016-09-05,1.10
  ```
  
  L'app lo legge al posto delle API e lo tratta come la fonte piu' affidabile.
  Vedi la scheda **Fonti dei dati** per gli altri archivi disponibili.
  """))
    else:
        st.markdown(L("#### Ten years of distribution", "#### Dieci anni di distribuzione"))
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

        st.markdown(L("##### Dividend safety, factor by factor",
                      "##### Solidita' del dividendo, fattore per fattore"))
        st.caption(L("It starts from 50 points. Each factor adds or removes points according to "
                     "the rule shown: this is a stated criterion, not a statistical model trained "
                     "on a historical database of cuts. You are free to disagree on a factor and "
                     "redo the sum.",
                     "Si parte da 50 punti. Ogni fattore aggiunge o toglie punti secondo la "
                     "regola indicata: e' un criterio dichiarato, non un modello statistico "
                     "addestrato su una base storica di tagli. Puoi non essere d'accordo su un "
                     "fattore e rifare il conto."))
        st.dataframe(pd.DataFrame([{
            L("Factor", "Fattore"): fattore.label,
            L("Value", "Valore"): (fmt.pct(fattore.value) if fattore.fmt == "pct"
                      else fmt.mult(fattore.value) if fattore.fmt == "x"
                      else fmt.num(fattore.value, 0)),
            L("Points", "Punti"): f"{fattore.points:+.0f}",
            L("Why", "Perche'"): fattore.explanation,
        } for fattore in div.safety.factors]), use_container_width=True, hide_index=True)

        st.markdown(L("##### The dividend forecast, method by method",
                      "##### La previsione del dividendo, metodo per metodo"))
        st.dataframe(pd.DataFrame([{
            L("Method", "Metodo"): metodo.label,
            L("Estimated dividend",
              "Dividendo stimato"): (fmt.money(metodo.value, valuta) if metodo.usable
                                   else L("not applicable", "non applicabile")),
            L("Weight", "Peso"): f"{metodo.weight:.0%}" if metodo.weight else "-",
            L("Assumptions", "Ipotesi"): metodo.detail or metodo.skipped_reason or "",
        } for metodo in div.forecast.methods]), use_container_width=True, hide_index=True)

        st.plotly_chart(charts.backtest_chart(div, scuro), use_container_width=True)

        st.markdown(L("##### The numbers, year by year", "##### I numeri, anno per anno"))
        etichette_div = {
            "dps": L(f"Dividend per share ({valuta})",
                     f"Dividendo per azione ({valuta})"), "stacchi": L("Number of payments",
                                                                  "Numero di stacchi"),
            "prezzo_medio": L(f"Average price for the year ({valuta})",
                              f"Prezzo medio dell'anno ({valuta})"),
            "rendimento": L("Yield on the average price", "Rendimento sul prezzo medio"),
            "eps": L(f"Earnings per share ({valuta})",
                     f"Utile per azione ({valuta})"), "payout": L("Share of earnings paid out",
                                                                 "Quota di utili distribuita"),
            "fcf_per_azione": L(f"Free cash flow per share ({valuta})",
                                f"Cassa libera per azione ({valuta})"),
            "copertura_cassa": L("Cover from free cash flow (times)",
                                 "Copertura con la cassa (volte)"),
            "variazione": L("Change on the previous year", "Variazione sull'anno precedente"),
        }
        tabella_div = div.years[[c for c in etichette_div if c in div.years.columns]].copy()
        tabella_div.index = [str(int(a)) for a in tabella_div.index]
        tabella_div = tabella_div.rename(columns=etichette_div).T
        st.dataframe(tabella_div.style.format("{:,.4g}", na_rep=fmt.na()),
                     use_container_width=True)
        st.caption(L("The last column is the year in progress: it is incomplete by definition and "
                     "enters no average.",
                     "L'ultima colonna e' l'anno in corso: e' incompleto per definizione e non "
                     "entra in nessuna media."))

        if div.notes:
            st.markdown(L("##### Limits of this analysis", "##### Limiti di questa analisi"))
            for nota in div.notes:
                st.markdown(f"- {nota}")

with schede[1]:
    st.markdown(L("#### What kind of company it has been", "#### Che azienda e' stata"))
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
    st.markdown(L("#### Where it stands now", "#### Dove si trova adesso"))
    st.markdown("<div class='prose'>" + "".join(f"<p>{p}</p>" for p in analisi.narrative["present"])
                + "</div>", unsafe_allow_html=True)
    st.plotly_chart(charts.price_chart(m, v, analisi.data.prices, scuro), use_container_width=True)
    # L'RSI subito sotto il prezzo: e' la stessa domanda vista da vicino.
    # I due menu perche' quattordici sessioni sono la convenzione di Wilder, non
    # una legge di natura: chi tiene un titolo per anni vuole la stessa misura
    # sul proprio orizzonte. Cambiando periodo cambia anche il modo di leggere
    # la banda, e il grafico lo spiega da solo.
    scelte = st.columns(2)
    _periodi = scelte[0].selectbox(
        L("RSI period", "Periodo dell'RSI"), charts.PERIODI_RSI,
        index=charts.PERIODI_RSI.index(charts.RSI_PERIODS),
        format_func=charts.nome_periodo, key="rsi-periodo",
        help=L("14 sessions is the convention, and the only period for which the 70/30 "
               "thresholds mean anything: over more sessions the RSI never reaches them, so "
               "the chart switches to this stock's own middle half.",
               "Quattordici sessioni sono la convenzione, e l'unico periodo per cui le soglie "
               "70/30 vogliono dire qualcosa: su piu' sessioni l'RSI non le raggiunge mai, "
               "quindi il grafico passa alla meta' centrale della storia del titolo."),
    )
    _finestra = scelte[1].selectbox(
        L("How much history to show", "Quanto storico mostrare"), charts.FINESTRE_RSI,
        index=charts.FINESTRE_RSI.index(2.0),
        format_func=charts.nome_finestra, key="rsi-finestra",
        help=L("Only changes the width of the chart. The band is computed on the full history, "
               "so zooming does not move it.",
               "Cambia solo la larghezza del grafico. La fascia si calcola su tutto lo storico, "
               "quindi lo zoom non la sposta."),
    )
    st.plotly_chart(charts.rsi_chart(m, analisi.data.prices, scuro,
                                     anni=_finestra, periodi=_periodi),
                    use_container_width=True)
    due = st.columns(2)
    due[0].plotly_chart(charts.multiple_history_chart(m, "pe", scuro), use_container_width=True)
    due[1].plotly_chart(charts.multiple_history_chart(m, "pb", scuro), use_container_width=True)
    st.plotly_chart(charts.health_chart(m, scuro), use_container_width=True)

with schede[3]:
    st.markdown(L("#### What to expect over 1-2 years", "#### Cosa aspettarsi a 1-2 anni"))
    st.markdown("<div class='prose'>" + "".join(f"<p>{p}</p>" for p in analisi.narrative["future"])
                + "</div>", unsafe_allow_html=True)
    st.plotly_chart(charts.methods_chart(m, v, scuro), use_container_width=True)
    st.markdown(L("##### The models, one by one", "##### I modelli, uno per uno"))
    righe = []
    for metodo in v.methods:
        righe.append({
            L("Method", "Metodo"): metodo.label,
            L("Value per share",
              "Valore per azione"): (fmt.money(metodo.fair_value, valuta) if metodo.usable
                                else L("not applicable", "non applicabile")),
            L("Weight", "Peso"): f"{metodo.weight:.0%}" if metodo.weight else "-",
            L("Assumptions", "Ipotesi"): metodo.detail or metodo.skipped_reason or "",
        })
    st.dataframe(pd.DataFrame(righe), use_container_width=True, hide_index=True)
    st.markdown(L("##### When to revisit the decision",
                  "##### Quando rimettere in discussione la decisione"))
    for innesco in d.review_triggers:
        st.markdown(f"- {innesco}")

with schede[4]:
    st.plotly_chart(charts.pillars_chart(d, scuro), use_container_width=True)
    st.markdown(L("#### How the score is built", "#### Come nasce il punteggio"))
    st.caption(L("Each area is the weighted average of a handful of indicators. Indicators with "
                 "no data carry no weight, and their absence lowers the overall reliability.",
                 "Ogni area e' la media ponderata di alcuni indicatori. Gli indicatori "
                 "senza dato non pesano, e la loro assenza abbassa l'affidabilita' complessiva."))
    for pilastro in d.pillars:
        titolo = (L(f"{pilastro.label} - "
                    f"{fmt.na() if pilastro.score is None else f'{pilastro.score:.0f}/100'} "
                    f"(weight {pilastro.weight:.0%})",
                    f"{pilastro.label} - "
                    f"{'n/d' if pilastro.score is None else f'{pilastro.score:.0f}/100'} "
                    f"(peso {pilastro.weight:.0%})"))
        with st.expander(titolo, expanded=pilastro.score is not None and pilastro.score < 45):
            st.caption(pilastro.question)
            st.dataframe(pd.DataFrame([{
                L("Indicator", "Indicatore"): criterio.label,
                L("Value", "Valore"): criterio.formatted(),
                L("Score",
                  "Punteggio"): fmt.na() if criterio.score is None else f"{criterio.score:.0f}",
                L("Weight", "Peso"): f"{fmt.num(criterio.weight, 1)}",
                L("Note", "Nota"): criterio.note,
            } for criterio in pilastro.criteria]), use_container_width=True, hide_index=True)

with schede[5]:
    st.markdown(L("#### The numbers, financial year by financial year",
                  "#### I numeri, esercizio per esercizio"))
    st.caption(L("The full table: every chart on this page is built from it.",
                 "La tabella completa: ogni grafico di questa pagina nasce da qui."))
    if m.years is not None and not m.years.empty:
        etichette = {
            "revenue": L("Revenue", "Ricavi"), "gross_profit": L("Gross profit", "Utile lordo"),
            "operating_income": L("Operating income", "Utile operativo"),
            "ebitda": "EBITDA", "net_income": L("Net income",
                                                "Utile netto"), "eps": L("Earnings per share",
                                                                     "Utile per azione"),
            "dps": L("Dividend per share",
                     "Dividendo per azione"), "equity": L("Shareholders' equity",
                                                                                "Patrimonio netto"),
            "total_assets": L("Total assets", "Attivo totale"),
            "total_debt": L("Total debt",
                            "Debito totale"), "net_debt": L("Net debt",
                                                                          "Debito netto"), "cash": L("Cash",
                                                                                                                 "Cassa"),
            "cfo": L("Cash from operations",
                     "Cassa dall'attivita'"), "capex": L("Capital spending",
                                                                                 "Investimenti"), "fcf": L("Free cash flow",
                                                                                 "Cassa libera"),
            "gross_margin": L("Gross margin",
                              "Margine lordo"), "operating_margin": L("Operating margin",
                                                                  "Margine operativo"),
            "net_margin": L("Net margin",
                            "Margine netto"), "roe": "ROE", "roic": "ROIC", "roa": "ROA",
            "net_debt_ebitda": L("Net debt / EBITDA",
                                 "Debito netto / EBITDA"), "debt_equity": L("Debt / equity",
                                                                     "Debito / patrimonio"),
            "interest_coverage": L("Interest coverage",
                                   "Copertura interessi"), "current_ratio": L("Current ratio",
                                                                         "Liquidita' corrente"),
            "equity_ratio": L("Equity / assets",
                              "Patrimonio / attivo"), "payout": L("Share of earnings paid out",
                                                           "Utili distribuiti"),
        }
        tabella = m.years[[c for c in etichette if c in m.years.columns]].copy()
        tabella.index = [data.strftime("%Y") for data in tabella.index]
        tabella = tabella.rename(columns=etichette).T
        st.dataframe(tabella.style.format("{:,.4g}", na_rep=fmt.na()), use_container_width=True)
    else:
        st.warning(L("No financial statements available on Yahoo Finance for this stock.",
                     "Nessun bilancio disponibile su Yahoo Finance per questo titolo."))

    st.markdown(L("#### Trailing twelve months and multiples",
                  "#### Ultimi dodici mesi e multipli"))
    sintesi = {
        L("Revenue (12 months)", "Ricavi (12 mesi)"): fmt.big(m.ttm.get("revenue"), valuta),
        L("Net income (12 months)",
          "Utile netto (12 mesi)"): fmt.big(m.ttm.get("net_income"), valuta),
        L("Free cash flow (12 months)",
          "Cassa libera (12 mesi)"): fmt.big(m.ttm.get("fcf"), valuta),
        L("Earnings per share (12 months)",
          "Utile per azione (12 mesi)"): fmt.money(m.ttm.get("eps"), valuta),
        L("Market capitalisation", "Capitalizzazione"): fmt.big(m.market_cap, valuta),
        "P/E": fmt.mult(m.valuation.get("pe")),
        "P/B": fmt.mult(m.valuation.get("pb")),
        "EV/EBITDA": fmt.mult(m.valuation.get("ev_ebitda")),
        L("Free cash flow yield", "Rendimento cassa libera"): fmt.pct(m.valuation.get("fcf_yield")),
        L("Dividend yield", "Dividendo"): fmt.pct(m.dividend.get("yield_current")),
        L("Beta against the SET index", "Beta contro indice SET"): fmt.ratio(m.trend.get("beta")),
        L("Annual volatility", "Volatilita' annua"): fmt.pct(m.trend.get("volatility")),
        L(f"RSI ({charts.RSI_PERIODS} sessions)", f"RSI ({charts.RSI_PERIODS} sessioni)"):
            fmt.num(m.trend.get("rsi"), 0),
        L("Required return (models)", "Rendimento richiesto (modelli)"): fmt.pct(v.cost_of_equity),
    }
    st.dataframe(pd.DataFrame({L("Item",
                                 "Voce"): list(sintesi), L("Value",
                                                                   "Valore"): list(sintesi.values())}),
                 use_container_width=True, hide_index=True)

with schede[6]:
    st.markdown(L("#### Where the dividends come from", "#### Da dove arrivano i dividendi"))
    if div is not None and div.source is not None:
        st.markdown(L(f"**Series used:** {div.source.provenance()}",
                      f"**Serie usata:** {div.source.provenance()}"))
        righe_fonti = []
        for risultato in div.source.results:
            righe_fonti.append({
                L("Source", "Fonte"): risultato.label,
                L("Trust", "Fiducia"): "*" * risultato.trust,
                L("Outcome",
                  "Esito"): (L(f"{risultato.payments} payments over "
                               f"{fmt.num(risultato.span_years, 1)} years",
                              f"{risultato.payments} stacchi su {fmt.num(risultato.span_years, 1)} "
                              f"anni")
                            if risultato.ok else (risultato.error or L("no data", "nessun dato"))),
                L("Used", "Usata"): L("yes", "si") if risultato.key == div.source.chosen else "",
                L("Notes", "Note"): risultato.note,
            })
        if righe_fonti:
            st.dataframe(pd.DataFrame(righe_fonti), use_container_width=True, hide_index=True)
        if div.source.disagreements:
            st.markdown(L("**The sources do not agree on everything:**",
                          "**Le fonti non concordano su tutto:**"))
            for avviso in div.source.disagreements:
                st.markdown(f"<div class='warning'>{avviso}</div>", unsafe_allow_html=True)
            st.caption(L("We make no attempt to reconcile them: on a figure like the dividend, "
                         "knowing that two archives disagree is worth more than an average of the "
                         "two. The SET website is the referee.",
                         "Non tentiamo di riconciliare: su un dato come il dividendo sapere che "
                         "due archivi non concordano vale piu' di una media fra i due. "
                         "Il sito della SET e' l'arbitro."))
    else:
        st.caption(L("No information on where the dividend data came from.",
                     "Nessuna informazione sulla provenienza dei dividendi."))

    st.markdown(L("#### Every source available", "#### Tutte le fonti disponibili"))
    st.caption(L("The tool queries every active archive and compares the results. The sources that "
                 "require a key are free: register on the service's website and put the key in the "
                 "environment variable shown.",
                 "Lo strumento interroga ogni archivio attivo e confronta i risultati. Le fonti "
                 "che richiedono una chiave sono gratuite: registrati sul sito del servizio e "
                 "metti la chiave nella variabile d'ambiente indicata."))
    st.dataframe(pd.DataFrame([{
        L("Source", "Fonte"): riga["source"],
        L("Trust", "Fiducia"): "*" * riga["trust"],
        L("Environment variable", "Variabile d'ambiente"): riga["api_key"],
        L("Active now", "Attiva adesso"): L("yes", "si") if riga["active"] else "no",
        L("Notes", "Note"): riga["note"],
    } for riga in describe_sources()]), use_container_width=True, hide_index=True)
    with st.expander(L("How to supply the dividends by hand (always works)",
                       "Come fornire i dividendi a mano (funziona sempre)")):
        st.markdown(L("""
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
  """,
                      """
  Nessuna API e' garantita nel tempo. Questa strada no: copia dal sito della SET la
  tabella degli stacchi e salvala come `data/<SIMBOLO>-dividends.csv`.
  
  ```
  date,dividend
  2016-04-25,1.10
  2016-09-05,1.10
  2017-04-24,1.20
  ```
  
  Vanno bene anche `data,importo`, il punto e virgola come separatore e la virgola
  decimale. Le date si leggono con il giorno prima del mese, come scrive la SET.
  Il file viene trattato come la fonte piu' affidabile e usato al posto delle API.
  """))

    st.markdown(L("#### What was found in the rest of the data",
                  "#### Cosa e' stato trovato negli altri dati"))
    copertura = analisi.data.data_coverage()
    st.dataframe(pd.DataFrame({
        L("Item", "Dato"): list(copertura),
        L("Available",
          "Disponibile"): [L("yes",
                                          "si") if valore else "no" for valore in copertura.values()],
    }), use_container_width=True, hide_index=True)
    limiti = list(m.notes) + list(v.notes) + list(analisi.data.warnings)
    if limiti:
        st.markdown(L("#### Limits worth keeping in mind", "#### Limiti da tenere presenti"))
        for nota in limiti:
            st.markdown(f"- {nota}")
    st.markdown(L("#### Method", "#### Metodo"))
    st.markdown(L("""
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
  """,
                  """
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
  """))

st.divider()
report = analisi.report()
colonne = st.columns([1, 1, 3])
colonne[0].download_button(L("Download the report (markdown)",
                             "Scarica il report (markdown)"), data=report.encode("utf-8"),
                           file_name=f"setxray-{m.symbol}.md", mime="text/markdown",
                           use_container_width=True)
if m.years is not None and not m.years.empty:
    csv = io.StringIO()
    m.years.to_csv(csv)
    colonne[1].download_button(L("Download the data (CSV)",
                                 "Scarica i dati (CSV)"), data=csv.getvalue().encode("utf-8"),
                               file_name=f"setxray-{m.symbol}.csv", mime="text/csv",
                               use_container_width=True)
colonne[2].caption(L("Automated processing of public data. This is not financial advice, nor a "
                     "personalised recommendation: always check the figures against the company's "
                     "official statements and the Stock Exchange of Thailand website.",
                     "Elaborazione automatica di dati pubblici. Non e' consulenza finanziaria "
                     "ne' una raccomandazione personalizzata: verifica sempre i numeri sui bilanci "
                     "ufficiali della societa' e sul sito della Stock Exchange of Thailand."))
