"""La sonda sugli indirizzi delle fonti, con la rete simulata.

La sonda esiste perche' ne' la SET ne' Settrade pubblicano un'API documentata,
e chi scrive il codice puo' non avere la rete verso quei siti: la verifica la
fa chi fa girare l'app. Queste prove controllano la parte che si puo'
controllare da qui, cioe' che a ogni tipo di risposta corrisponda la
conclusione giusta - perche' e' su quella conclusione che si decide se un
indirizzo va tenuto, corretto o buttato.
"""

import io
import json
import urllib.error

import pytest

from setxray.lang import using
from setxray.sources import probe as sonda


class RispostaFinta(io.BytesIO):
    """Il minimo di urlopen() che la sonda usa: read, headers, status."""

    def __init__(self, corpo: bytes, tipo: str = "application/json", codice: int = 200):
        super().__init__(corpo)
        self.headers = {"Content-Type": tipo}
        self.status = codice

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
        return False


@pytest.fixture
def rete(monkeypatch):
    """Decide cosa risponde ogni indirizzo. Chiave: un pezzo dell'URL."""
    risposte: dict[str, object] = {}

    def urlopen(richiesta, timeout=None):
        url = richiesta.full_url
        for pezzo, risposta in risposte.items():
            if pezzo in url:
                if isinstance(risposta, Exception):
                    raise risposta
                return risposta()
        raise urllib.error.URLError("host non raggiungibile")

    monkeypatch.setattr(sonda.urllib.request, "urlopen", urlopen)
    return risposte


STACCHI = [{"date": "2025-04-20", "dividend": 1.1},
           {"date": "2024-04-18", "dividend": 1.0}]


class TestUnIndirizzoPerVolta:
    def test_dividendi_riconosciuti(self, rete):
        rete["rights-benefit"] = lambda: RispostaFinta(json.dumps(STACCHI).encode())
        esito = sonda.prova_indirizzo("https://x/api/set/stock/PTT/rights-benefit")
        assert esito.ok and esito.dividendi == 2
        assert "2025-04-20" in esito.dettaglio

    def test_json_che_non_capiamo_mostra_i_campi(self, rete):
        """E' il caso piu' utile: l'indirizzo c'e', il lettore va scritto.

        Senza i nomi dei campi la risposta "non riconosciuto" non servirebbe a
        niente; con i nomi il lettore si scrive senza avere la rete.
        """
        corpo = {"data": [{"tradingDate": "20/04/2025", "closePrice": 35.5, "volume": 1_000}]}
        rete["corporate-action"] = lambda: RispostaFinta(json.dumps(corpo).encode())
        esito = sonda.prova_indirizzo("https://x/api/set/stock/PTT/corporate-action")
        assert esito.stato == "unrecognised"
        assert esito.campione == ["tradingDate", "closePrice", "volume"]
        assert "data" in esito.forma

    def test_una_pagina_non_e_un_api(self, rete):
        rete["get-quote"] = lambda: RispostaFinta(b"<!DOCTYPE html><html>...", "text/html")
        esito = sonda.prova_indirizzo("https://x/th/get-quote")
        assert esito.stato == "html"
        assert "text/html" in esito.dettaglio

    def test_errore_http(self, rete):
        rete["factsheet"] = urllib.error.HTTPError("https://x/factsheet", 404, "Not Found", {}, None)
        esito = sonda.prova_indirizzo("https://x/api/set/factsheet/PTT/rights-benefit")
        assert esito.stato == "http" and "404" in esito.dettaglio

    def test_host_muto(self, rete):
        esito = sonda.prova_indirizzo("https://nessuno/api/x")
        assert esito.stato == "unreachable"

    def test_risposta_vuota(self, rete):
        rete["vuoto"] = lambda: RispostaFinta(b"")
        assert sonda.prova_indirizzo("https://x/vuoto").stato == "empty"

    def test_json_grande_non_viene_scambiato_per_non_json(self, rete, monkeypatch):
        """Leggere solo i primi byte faceva passare per "non JSON" una risposta
        buona, perche' un JSON tagliato a meta' non si parsa."""
        grande = json.dumps([{"date": "2025-04-20", "dividend": 1.1}]
                            + [{"nota": "x" * 50}] * 2000).encode()
        monkeypatch.setattr(sonda, "LIMITE", 8_000_000)
        rete["grande"] = lambda: RispostaFinta(grande)
        esito = sonda.prova_indirizzo("https://x/grande")
        assert esito.ok, "un JSON di mezzo megabyte va letto intero"

    def test_oltre_il_tetto_lo_dice(self, rete, monkeypatch):
        monkeypatch.setattr(sonda, "LIMITE", 200)
        rete["enorme"] = lambda: RispostaFinta(json.dumps([{"a": 1}] * 500).encode())
        esito = sonda.prova_indirizzo("https://x/enorme")
        assert esito.stato == "troppo-grande"


class TestTuttiGliIndirizzi:
    def test_prova_set_e_settrade(self, rete):
        rete["settrade.com/api/set/stock"] = lambda: RispostaFinta(json.dumps(STACCHI).encode())
        esiti = sonda.probe("ptt")
        assert {e.source for e in esiti} == {"set", "settrade"}
        assert all("PTT" in e.url for e in esiti), "il simbolo va normalizzato senza .BK"
        buoni = [e for e in esiti if e.ok]
        assert buoni and buoni[0].source == "settrade"

    def test_si_ferma_al_primo_se_richiesto(self, rete):
        rete["set.or.th"] = lambda: RispostaFinta(json.dumps(STACCHI).encode())
        esiti = sonda.probe("ptt", fermati_al_primo=True)
        assert len(esiti) == 1 and esiti[0].ok

    def test_il_riassunto_distingue_i_tre_casi(self, rete):
        rete["settrade.com/api/set/stock"] = lambda: RispostaFinta(json.dumps(STACCHI).encode())
        testo = sonda.riassunto(sonda.probe("ptt"))
        assert "settrade: works" in testo
        # nessun indirizzo della SET risponde: e' rete, non indirizzo sbagliato
        assert "set: unreachable from here" in testo

    def test_riassunto_quando_il_lettore_e_da_scrivere(self, rete):
        # una risposta di quotazione, senza stacchi dentro
        corpo = {"quote": {"last": 112.5, "change": -1.0, "volume": 4_100_000}}
        rete["set.or.th"] = lambda: RispostaFinta(json.dumps(corpo).encode())
        testo = sonda.riassunto(sonda.probe("ptt", sources=("set",)))
        assert "does not recognise" in testo
        assert "{quote}" in testo, "la forma del JSON va detta nel riassunto"

    def test_fonte_sconosciuta_non_ha_indirizzi(self):
        assert sonda.indirizzi("yahoo", "PTT") == []


class TestNelleDueLingue:
    def test_gli_esiti_sono_tradotti(self, rete):
        rete["rights-benefit"] = lambda: RispostaFinta(json.dumps(STACCHI).encode())
        esito = sonda.prova_indirizzo("https://x/api/set/stock/PTT/rights-benefit")
        with using("en"):
            riga = esito.riga()
            assert riga["Outcome"] == "works" and "payments" in riga["Detail"]
        with using("it"):
            riga = esito.riga()
            assert riga["Esito"] == "funziona"

    def test_il_riassunto_e_tradotto(self, rete):
        with using("it"):
            testo = sonda.riassunto(sonda.probe("ptt", sources=("settrade",)))
        assert "irraggiungibile" in testo


def test_la_pagina_di_settrade_punta_al_titolo():
    """Quando la lettura automatica non funziona il dato non e' perduto: e'
    scritto su una pagina, e il collegamento la apre sul titolo giusto."""
    from setxray.sources.settrade import pagina

    assert pagina("SCB") == "https://www.settrade.com/th/get-quote?symbol=SCB"


def test_gli_indirizzi_hanno_il_segnaposto():
    """Un indirizzo senza {symbol} sarebbe lo stesso titolo per tutti."""
    from setxray.sources import setofficial, settrade

    for modulo in (setofficial, settrade):
        for modello in modulo.INDIRIZZI:
            assert "{symbol}" in modello, modello


def test_niente_serie_vuote_dalla_sonda(rete):
    """Una serie vuota non e' un successo: sarebbe un indirizzo "che funziona"
    e non porta dati."""
    rete["vuota"] = lambda: RispostaFinta(json.dumps([]).encode())
    esito = sonda.prova_indirizzo("https://x/vuota")
    assert not esito.ok and esito.dividendi == 0
