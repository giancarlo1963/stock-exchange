"""Setaccia tutta la SET e tira fuori i titoli da dividendo che reggono l'esame.

Perche' esiste, e perche' non e' una funzione da due righe. La domanda «ci sono
altri titoli solidi dove entrare oggi?» si risponde solo con dati di mercato di
oggi, e su circa ottocento titoli. Farlo a forza bruta - scaricare tutto di
tutti - vuol dire migliaia di chiamate a Yahoo, che dopo poche decine risponde
con tabelle vuote e fa sembrare il mercato deserto.

Quindi due stadi, come si fa quando il filtro costa meno del dato:

1. **Rete larga, a buon mercato.** Lo screener di Yahoo filtra lato server: gli
   si chiede «titoli thailandesi alla SET con rendimento da dividendo sopra la
   soglia» e torna un elenco corto in una richiesta sola. Se quella strada non
   funziona - lo screener cambia, i campi cambiano nome - si ripiega
   sull'elenco completo dei simboli e si filtra in casa.
2. **Esame vero, solo sui sopravvissuti.** Su quelli si fa girare l'analisi
   completa: rendimento di oggi contro la propria storia decennale, punteggio
   di sicurezza sui sette fattori, rischio di taglio, payout, anni di stacchi
   ininterrotti. E' la parte costosa, e si paga solo per i titoli che hanno una
   possibilita' di passare.

I criteri non sono inventati qui: sono le regole del report strategico, scritte
in codice perche' un criterio applicato a mano su ottocento titoli non e' un
criterio, e' un'opinione. Un titolo passa se paga da almeno tre anni, se rende
almeno quanto la soglia, se il punteggio di sicurezza regge, se il payout sta
sotto il 100% e se il rischio di taglio non e' alto.

Gli scartati restano nel risultato con il motivo dello scarto. Serve: un titolo
escluso «per payout al 130%» dice qualcosa di diverso da uno escluso «perche'
paga da due anni», e chi legge deve poter dissentire da un criterio senza
rifare il lavoro.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from setxray.lang import L, plural

# Fra un'analisi completa e la successiva: Yahoo non ama le raffiche, e un
# elenco di cinquanta titoli scaricato in venti secondi torna mezzo vuoto.
PAUSA_FRA_TITOLI = 1.2
# Quanti titoli passare all'esame completo. Oltre questo numero l'attesa non e'
# piu' accettabile per nessuno, e la rete larga ha gia' fatto la sua parte.
MASSIMO_ESAME = 60
# La soglia di rendimento con cui si chiede la preselezione a Yahoo: piu' bassa
# della soglia vera, perche' il rendimento che Yahoo pubblica e' arrotondato e
# a volte vecchio, e scartare qui sarebbe scartare alla cieca.
MARGINE_PRESELEZIONE = 0.01

RISCHI_ORDINE = {"low": 0, "basso": 0, "medium": 1, "medio": 1, "high": 2, "alto": 2}


@dataclass
class Criteri:
    """Le regole, in un posto solo, così si possono discutere."""

    rendimento_minimo: float = 0.04
    sicurezza_minima: float = 60.0
    anni_minimi: int = 3
    payout_massimo: float = 1.0
    rischio_taglio_massimo: str = "medium"
    tagli_massimi: int = 1
    escludi: frozenset[str] = frozenset()

    def descrizione(self) -> list[str]:
        return [
            L(f"dividend yield at least {self.rendimento_minimo:.1%}",
              f"rendimento da dividendo almeno {self.rendimento_minimo:.1%}"),
            L(f"dividend safety at least {self.sicurezza_minima:.0f}/100",
              f"sicurezza del dividendo almeno {self.sicurezza_minima:.0f}/100"),
            L(f"paying for at least {self.anni_minimi} years without interruption",
              f"paga da almeno {self.anni_minimi} anni senza interruzioni"),
            L(f"payout at most {self.payout_massimo:.0%} of earnings",
              f"payout non oltre il {self.payout_massimo:.0%} degli utili"),
            L(f"cut risk not above \"{self.rischio_taglio_massimo}\"",
              f"rischio di taglio non oltre «{self.rischio_taglio_massimo}»"),
            L(f"at most {self.tagli_massimi} "
              + plural(self.tagli_massimi, "cut", "cuts") + " in ten years",
              f"al massimo {self.tagli_massimi} "
              + plural(self.tagli_massimi, "taglio", "tagli") + " in dieci anni"),
        ]


@dataclass
class Candidato:
    symbol: str
    name: str = ""
    sector: str = ""
    price: Optional[float] = None
    rendimento: Optional[float] = None
    rendimento_mediano: Optional[float] = None
    percentile: Optional[float] = None
    sicurezza: Optional[float] = None
    rischio_taglio: str = ""
    anni_pagati: Optional[int] = None
    tagli: Optional[int] = None
    payout: Optional[float] = None
    crescita: Optional[float] = None
    azione: str = ""
    punteggio: float = 0.0
    motivi: list[str] = field(default_factory=list)
    scartato: str = ""

    @property
    def passa(self) -> bool:
        return not self.scartato


@dataclass
class Risultato:
    candidati: list[Candidato] = field(default_factory=list)
    scartati: list[Candidato] = field(default_factory=list)
    esaminati: int = 0
    preselezionati: int = 0
    universo: int = 0
    note: list[str] = field(default_factory=list)
    secondi: float = 0.0

    def migliori(self, quanti: int = 15) -> list[Candidato]:
        return sorted(self.candidati, key=lambda c: -c.punteggio)[:quanti]


# --------------------------------------------------------------------------
# punteggio
# --------------------------------------------------------------------------
def punteggio(c: Candidato) -> float:
    """Da 0 a 100, e ogni pezzo si puo' leggere da solo.

    Quattro voci, perche' quattro sono le cose che decidono se un titolo da
    dividendo vale la pena: quanto rende, quanto e' sicuro quel rendimento, da
    quanto tempo lo fa, e se oggi costa meno del solito rispetto alla propria
    storia. I tagli passati si pagano: chi ha tagliato una volta puo' tagliare
    ancora, e nessun rendimento compensa quella notizia.
    """
    rendimento = 40.0 * min((c.rendimento or 0.0) / 0.08, 1.0)
    sicurezza = 30.0 * (c.sicurezza or 0.0) / 100.0
    continuita = 15.0 * min((c.anni_pagati or 0) / 10.0, 1.0)
    sconto = 15.0 * (c.percentile if c.percentile is not None else 0.5)
    penalita = min(15.0, 5.0 * (c.tagli or 0))
    return max(0.0, round(rendimento + sicurezza + continuita + sconto - penalita, 1))


def _perche(c: Candidato) -> list[str]:
    """Le due o tre ragioni per cui questo titolo e' in lista."""
    motivi = []
    if c.rendimento and c.rendimento >= 0.06:
        motivi.append(L(f"yield {c.rendimento:.1%}", f"rende il {c.rendimento:.1%}"))
    if c.percentile is not None and c.percentile >= 0.7:
        motivi.append(L(f"yield higher than {c.percentile:.0%} of its own history",
                        f"rendimento più alto del {c.percentile:.0%} della sua storia"))
    if c.anni_pagati and c.tagli == 0:
        motivi.append(L(f"{c.anni_pagati} years paid, no cuts",
                        f"{c.anni_pagati} anni pagati, nessun taglio"))
    if c.sicurezza and c.sicurezza >= 70:
        motivi.append(L(f"safety {c.sicurezza:.0f}/100", f"sicurezza {c.sicurezza:.0f}/100"))
    if c.payout is not None and c.payout <= 0.7:
        motivi.append(L(f"payout {c.payout:.0%}", f"payout al {c.payout:.0%}"))
    if c.crescita and c.crescita > 0.02:
        motivi.append(L(f"dividend growing {c.crescita:.1%} a year",
                        f"dividendo che cresce del {c.crescita:.1%} l'anno"))
    return motivi[:4]


# --------------------------------------------------------------------------
# esame di un titolo
# --------------------------------------------------------------------------
def valuta(symbol: str, criteri: Optional[Criteri] = None) -> Candidato:
    """L'analisi completa di un titolo, tradotta in un candidato con verdetto."""
    from setxray.engine import NoDataError, analyze

    criteri = criteri or Criteri()
    c = Candidato(symbol=symbol.upper().replace(".BK", ""))
    try:
        analisi = analyze(symbol)
    except NoDataError as errore:
        c.scartato = L(f"no data: {errore}", f"nessun dato: {errore}")
        return c
    except Exception as errore:  # rete, forme inattese, titoli sospesi
        c.scartato = L(f"analysis failed ({type(errore).__name__})",
                       f"analisi non riuscita ({type(errore).__name__})")
        return c

    m, d = analisi.metrics, analisi.dividends
    c.name, c.sector, c.price = m.name, m.sector, m.price
    if d is None or not d.pays_dividends:
        c.scartato = L("pays no dividend", "non paga dividendo")
        return c

    stat = d.yield_stats or {}
    c.rendimento = stat.get("attuale")
    c.rendimento_mediano = stat.get("mediana")
    c.percentile = stat.get("percentile")
    streaks = d.streaks or {}
    c.anni_pagati = streaks.get("anni_consecutivi_pagati")
    c.tagli = streaks.get("tagli")
    c.payout = m.dividend.get("payout")
    c.crescita = (d.growth or {}).get("cagr_5y")
    if d.safety is not None:
        c.sicurezza = d.safety.score
        c.rischio_taglio = d.safety.cut_risk_band or ""
    if d.signal is not None:
        c.azione = d.signal.action

    # --- i filtri, in ordine di quanto sono dirimenti --------------------
    if c.symbol in criteri.escludi:
        c.scartato = L("already in the portfolio", "già in portafoglio")
    elif c.rendimento is None or c.rendimento < criteri.rendimento_minimo:
        c.scartato = L(f"yield {c.rendimento:.1%} below the threshold"
                       if c.rendimento is not None else "yield unknown",
                       f"rende il {c.rendimento:.1%}, sotto la soglia"
                       if c.rendimento is not None else "rendimento non calcolabile")
    elif (c.anni_pagati or 0) < criteri.anni_minimi:
        c.scartato = L(f"pays for {c.anni_pagati or 0} years only",
                       f"paga solo da {c.anni_pagati or 0} anni")
    elif c.sicurezza is not None and c.sicurezza < criteri.sicurezza_minima:
        c.scartato = L(f"safety {c.sicurezza:.0f}/100 below the threshold",
                       f"sicurezza {c.sicurezza:.0f}/100, sotto la soglia")
    elif (c.tagli or 0) > criteri.tagli_massimi:
        c.scartato = L(f"{c.tagli} " + plural(c.tagli, "cut", "cuts") + " in ten years",
                       f"{c.tagli} " + plural(c.tagli, "taglio", "tagli") + " in dieci anni")
    elif c.payout is not None and c.payout > criteri.payout_massimo:
        c.scartato = L(f"payout {c.payout:.0%} of earnings",
                       f"payout al {c.payout:.0%} degli utili")
    elif (RISCHI_ORDINE.get(c.rischio_taglio.lower(), 0)
          > RISCHI_ORDINE.get(criteri.rischio_taglio_massimo.lower(), 1)):
        c.scartato = L(f"cut risk \"{c.rischio_taglio}\"",
                       f"rischio di taglio «{c.rischio_taglio}»")

    if c.passa:
        c.punteggio = punteggio(c)
        c.motivi = _perche(c)
    return c


# --------------------------------------------------------------------------
# preselezione: la rete larga
# --------------------------------------------------------------------------
def _da_screener_yahoo(soglia: float, limite: int) -> tuple[list[str], list[str]]:
    """Chiede a Yahoo i titoli SET sopra una soglia di rendimento.

    Filtra lato server: una richiesta invece di ottocento. Se lo screener
    cambia forma - e' successo piu' volte - ritorna un elenco vuoto e la nota
    che spiega perche', e il chiamante ripiega sull'elenco completo.
    """
    note: list[str] = []
    try:
        import yfinance as yf

        domanda = yf.EquityQuery("and", [
            yf.EquityQuery("eq", ["region", "th"]),
            yf.EquityQuery("is-in", ["exchange", "SET"]),
            yf.EquityQuery("gte", ["dividendyield", soglia * 100]),
        ])
        risposta = yf.screen(domanda, size=min(250, max(25, limite)),
                             sortField="dividendyield", sortAsc=False)
    except Exception as errore:
        note.append(L(f"Yahoo screener unavailable ({type(errore).__name__}): falling back to "
                      "the full symbol list",
                      f"screener di Yahoo non disponibile ({type(errore).__name__}): "
                      "ripiego sull'elenco completo dei simboli"))
        return [], note

    quotazioni = []
    if isinstance(risposta, dict):
        quotazioni = risposta.get("quotes") or []
    simboli = []
    for q in quotazioni:
        sigla = (q.get("symbol") or "").upper()
        if sigla.endswith(".BK"):
            simboli.append(sigla[:-3])
    if simboli:
        note.append(L(f"Yahoo screener: {len(simboli)} symbols above {soglia:.1%}",
                      f"screener di Yahoo: {len(simboli)} simboli sopra il {soglia:.1%}"))
    return simboli, note


def preselezione(criteri: Criteri, limite: int = MASSIMO_ESAME,
                 offline: bool = False) -> tuple[list[str], int, list[str]]:
    """I simboli da portare all'esame completo, e quanto e' grande il mercato."""
    from setxray.universe import load_universe

    soglia = max(0.0, criteri.rendimento_minimo - MARGINE_PRESELEZIONE)
    note: list[str] = []
    simboli: list[str] = []
    if not offline:
        simboli, avvisi = _da_screener_yahoo(soglia, limite * 3)
        note.extend(avvisi)

    universo = load_universe(offline=offline)
    note.extend(universo.note[:2])
    conosciuti = {t.symbol for t in universo.titoli}
    if simboli:
        # L'elenco di Yahoo puo' contenere sigle che l'universo non conosce
        # (quotazioni nuove): si tengono, il nome arrivera' dall'analisi.
        ordinati = [s for s in simboli if s not in criteri.escludi]
    else:
        note.append(L("No server-side filter: every symbol in the list goes to the full exam, "
                      "the most popular first.",
                      "Nessun filtro lato server: all'esame completo vanno i simboli "
                      "dell'elenco, i piu' seguiti per primi."))
        ordinati = [t.symbol for t in universo.titoli if t.symbol not in criteri.escludi]
    return ordinati[:limite], len(conosciuti) or len(ordinati), note


# --------------------------------------------------------------------------
# la passata completa
# --------------------------------------------------------------------------
def screen(criteri: Optional[Criteri] = None, *, limite: int = MASSIMO_ESAME,
           offline: bool = False, pausa: Optional[float] = None,
           avanzamento: Optional[Callable[[int, int, str], None]] = None) -> Risultato:
    """Setaccia il mercato e ritorna i candidati, gli scartati e il perche'.

    `avanzamento(fatti, totali, simbolo)` viene chiamato prima di ogni titolo:
    una passata dura minuti, e una barra ferma sembra un programma bloccato.
    """
    criteri = criteri or Criteri()
    pausa = PAUSA_FRA_TITOLI if pausa is None else pausa
    partenza = time.monotonic()
    r = Risultato()

    simboli, quanti_nel_mercato, note = preselezione(criteri, limite=limite, offline=offline)
    r.universo, r.preselezionati, r.note = quanti_nel_mercato, len(simboli), note

    for indice, sigla in enumerate(simboli):
        if avanzamento is not None:
            avanzamento(indice, len(simboli), sigla)
        if indice and pausa:
            time.sleep(pausa)
        c = valuta(sigla, criteri)
        r.esaminati += 1
        (r.candidati if c.passa else r.scartati).append(c)

    r.secondi = round(time.monotonic() - partenza, 1)
    return r


def simboli_da_file(percorso: str) -> frozenset[str]:
    """Le sigle da escludere, lette da un file: una per riga, o la prima colonna
    di un CSV. Serve a non farsi consigliare quello che si ha gia'."""
    sigle: set[str] = set()
    if not os.path.exists(percorso):
        return frozenset()
    with open(percorso, encoding="utf-8", errors="replace") as fh:
        for riga in fh:
            pezzo = riga.split(",")[0].split(";")[0].strip().upper()
            pezzo = pezzo.replace(".BK", "")
            if pezzo and pezzo.replace("-", "").replace(".", "").isalnum():
                sigle.add(pezzo)
    return frozenset(sigle)
