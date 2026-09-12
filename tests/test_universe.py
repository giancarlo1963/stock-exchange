"""L'elenco dei titoli SET: le tre strade, e cosa succede quando cadono.

Le due strade di rete non si possono provare contro i servizi veri in un test
- sarebbe un test che dipende dal meteo - quindi si provano contro le risposte
che quei servizi danno, comprese quelle malfatte. Il resto e' il
comportamento che conta di piu': quando tutto tace, l'app deve restare in
piedi e dire che l'elenco non e' il mercato.
"""

import os
import pathlib

import pytest

from setxray import universe as uni
from setxray.lang import using
from setxray.sources.http import FetchError


# --------------------------------------------------------------------------
# il CSV: la strada che non dipende da nessuna API
# --------------------------------------------------------------------------
class TestCSV:
    def test_con_intestazione(self):
        titoli = uni._da_testo_csv(
            "symbol,name,sector\nPTT,PTT Public Company Limited,Energy\n"
            "AOT,Airports of Thailand,Transport\n")
        assert [t.symbol for t in titoli] == ["PTT", "AOT"]
        assert titoli[0].name == "PTT Public Company Limited"
        assert titoli[1].sector == "Transport"

    def test_solo_sigle_senza_intestazione(self):
        titoli = uni._da_testo_csv("PTT\nAOT\nKBANK\n")
        assert [t.symbol for t in titoli] == ["PTT", "AOT", "KBANK"]

    def test_intestazione_italiana_e_punto_e_virgola(self):
        """Un CSV nato da un Excel italiano: separatore e nomi diversi."""
        titoli = uni._da_testo_csv("simbolo;nome;settore\nPTT;PTT PCL;Energia\n"
                                   "SCC;Siam Cement;Materiali\n")
        assert [(t.symbol, t.name) for t in titoli] == [("PTT", "PTT PCL"),
                                                        ("SCC", "Siam Cement")]

    def test_righe_sporche_e_doppioni(self):
        titoli = uni._da_testo_csv(
            "symbol,name\n , \nPTT,PTT PCL\nPTT,doppione\n#commento,\nAOT.BK,Airports\n")
        assert [t.symbol for t in titoli] == ["PTT", "AOT"], "il .BK si normalizza"

    def test_vuoto_non_esplode(self):
        assert uni._da_testo_csv("") == []
        assert uni._da_testo_csv("\n\n") == []

    def test_lettura_dal_percorso(self, tmp_path, monkeypatch):
        via = tmp_path / "set-symbols.csv"
        via.write_text("symbol,name\nPTT,PTT PCL\nAOT,Airports\n", encoding="utf-8")
        monkeypatch.setenv("SETXRAY_SYMBOLS_CSV", str(via))
        titoli, etichetta = uni.dal_csv()
        assert [t.symbol for t in titoli] == ["PTT", "AOT"]
        assert str(via) in etichetta

    def test_senza_file_lo_dice(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SETXRAY_SYMBOLS_CSV", str(tmp_path / "non-esiste.csv"))
        monkeypatch.setattr(uni, "CARTELLE_CSV", (str(tmp_path),))
        with pytest.raises(FetchError):
            uni.dal_csv()

    def test_andata_e_ritorno(self, tmp_path):
        """Salvato e riletto: l'elenco non cambia."""
        universo = uni.Universo(titoli=[uni.Titolo("PTT", "PTT PCL", "Energy", "SET"),
                                        uni.Titolo("AOT", "Airports", "Transport", "SET")])
        via = tmp_path / "fuori.csv"
        assert uni.salva_csv(universo, str(via)) == 2
        riletti = uni._da_testo_csv(via.read_text())
        assert [(t.symbol, t.name, t.sector) for t in riletti] == \
               [(t.symbol, t.name, t.sector) for t in universo.titoli]


# --------------------------------------------------------------------------
# il sito della SET: interfaccia non documentata, quindi lettura difensiva
# --------------------------------------------------------------------------
class TestSitoSET:
    def _finta(self, monkeypatch, risposta):
        monkeypatch.setattr(uni, "get_json", lambda url, **k: risposta)

    def test_lista_sotto_una_chiave(self, monkeypatch):
        voci = [{"symbol": f"AA{i}", "nameEN": f"Azienda {i}", "sectorName": "ENERG"}
                for i in range(60)]
        self._finta(monkeypatch, {"securitySymbols": voci})
        titoli, etichetta = uni.dal_sito_set()
        assert len(titoli) == 60
        assert titoli[0].name.startswith("Azienda")
        assert "SET" in etichetta

    def test_lista_nuda(self, monkeypatch):
        self._finta(monkeypatch, [{"symbol": f"BB{i}"} for i in range(55)])
        titoli, _ = uni.dal_sito_set()
        assert len(titoli) == 55

    def test_solo_stringhe(self, monkeypatch):
        self._finta(monkeypatch, {"data": [f"CC{i}" for i in range(51)]})
        titoli, _ = uni.dal_sito_set()
        assert len(titoli) == 51

    def test_forma_sconosciuta_non_esplode(self, monkeypatch):
        self._finta(monkeypatch, {"result": {"ok": True}})
        with pytest.raises(FetchError):
            uni.dal_sito_set()

    def test_risposta_troppo_corta_non_e_il_listino(self, monkeypatch):
        """Tre simboli non sono la borsa: meglio provare la fonte dopo."""
        self._finta(monkeypatch, {"securitySymbols": [{"symbol": "PTT"}, {"symbol": "AOT"}]})
        with pytest.raises(FetchError) as errore:
            uni.dal_sito_set()
        assert "2" in str(errore.value)

    def test_rete_muta(self, monkeypatch):
        def esplode(url, **k):
            raise FetchError("URLError: nessuna rete")
        monkeypatch.setattr(uni, "get_json", esplode)
        with pytest.raises(FetchError):
            uni.dal_sito_set()


# --------------------------------------------------------------------------
# lo screener di Yahoo, a pagine
# --------------------------------------------------------------------------
class TestYahoo:
    def _finto_screen(self, monkeypatch, pagine: list[list[dict]]):
        import yfinance as yf

        def screen(query, offset=None, size=None, **k):
            indice = (offset or 0) // (size or 250)
            return {"quotes": pagine[indice]} if indice < len(pagine) else {"quotes": []}
        monkeypatch.setattr(yf, "screen", screen)

    def test_unisce_le_pagine(self, monkeypatch):
        pagine = [[{"symbol": f"X{i}.BK", "longName": f"Soc {i}"} for i in range(250)],
                  [{"symbol": f"Y{i}.BK", "longName": f"Soc {i}"} for i in range(40)]]
        self._finto_screen(monkeypatch, pagine)
        titoli, etichetta = uni.da_yahoo()
        assert len(titoli) == 290
        assert etichetta == "Yahoo Finance"
        assert all(not t.symbol.endswith(".BK") for t in titoli), "il suffisso si toglie"

    def test_si_ferma_su_pagina_corta(self, monkeypatch):
        self._finto_screen(monkeypatch, [[{"symbol": "PTT"}, {"symbol": "AOT"}]])
        titoli, _ = uni.da_yahoo()
        assert [t.symbol for t in titoli] == ["PTT", "AOT"]

    def test_doppioni_fra_pagine(self, monkeypatch):
        self._finto_screen(monkeypatch, [[{"symbol": "PTT"}, {"symbol": "PTT"},
                                          {"symbol": "AOT"}]])
        titoli, _ = uni.da_yahoo()
        assert [t.symbol for t in titoli] == ["PTT", "AOT"]

    def test_niente_titoli_lo_dice(self, monkeypatch):
        self._finto_screen(monkeypatch, [[]])
        with pytest.raises(FetchError):
            uni.da_yahoo()

    def test_errore_a_metà_tiene_il_parziale(self, monkeypatch):
        """Se la seconda pagina fallisce, le prime 250 restano buone."""
        import yfinance as yf

        def screen(query, offset=None, size=None, **k):
            if (offset or 0) == 0:
                return {"quotes": [{"symbol": f"Z{i}"} for i in range(250)]}
            raise RuntimeError("Yahoo ha chiuso")
        monkeypatch.setattr(yf, "screen", screen)
        titoli, _ = uni.da_yahoo()
        assert len(titoli) == 250


# --------------------------------------------------------------------------
# l'ingresso pubblico: l'ordine delle strade, e la resa onesta
# --------------------------------------------------------------------------
class TestCaricamento:
    @pytest.fixture(autouse=True)
    def _senza_cache(self, tmp_path, monkeypatch):
        """Ogni prova con la sua cartella: la cache di una non tocca l'altra."""
        monkeypatch.setattr(uni, "_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setattr(uni, "CARTELLE_CSV", (str(tmp_path / "vuota"),))
        monkeypatch.delenv("SETXRAY_SYMBOLS_CSV", raising=False)

    def test_quando_tutto_tace_resta_in_piedi(self, monkeypatch):
        monkeypatch.setattr(uni, "dal_sito_set", lambda: (_ for _ in ()).throw(FetchError("giu'")))
        monkeypatch.setattr(uni, "da_yahoo", lambda: (_ for _ in ()).throw(FetchError("giu'")))
        universo = uni.load_universe(ttl_ore=0)
        assert len(universo) == 16, "l'elenco corto incluso nel codice"
        assert universo.parziale, "e va dichiarato per quello che e'"
        assert any("giu'" in nota for nota in universo.note), "e si dice perche'"

    def test_una_fonte_che_esplode_non_ferma_le_altre(self, monkeypatch):
        monkeypatch.setattr(uni, "dal_sito_set",
                            lambda: (_ for _ in ()).throw(ValueError("bug nel parser")))
        monkeypatch.setattr(uni, "da_yahoo",
                            lambda: ([uni.Titolo(f"K{i}") for i in range(200)], "Yahoo Finance"))
        universo = uni.load_universe(ttl_ore=0)
        assert len(universo) == 200
        assert not universo.parziale
        assert any("bug nel parser" in nota for nota in universo.note)

    def test_il_sito_set_viene_prima_di_yahoo(self, monkeypatch):
        monkeypatch.setattr(uni, "dal_sito_set",
                            lambda: ([uni.Titolo(f"S{i}") for i in range(300)], "SET"))
        monkeypatch.setattr(uni, "da_yahoo",
                            lambda: ([uni.Titolo("YAHOO")], "Yahoo Finance"))
        assert uni.load_universe(ttl_ore=0).fonte == "SET"

    def test_il_csv_viene_prima_di_tutto(self, tmp_path, monkeypatch):
        """Se qualcuno ha messo li' un file, si fida di quello."""
        via = tmp_path / "mio.csv"
        via.write_text("symbol\n" + "\n".join(f"M{i}" for i in range(150)), encoding="utf-8")
        monkeypatch.setenv("SETXRAY_SYMBOLS_CSV", str(via))
        monkeypatch.setattr(uni, "dal_sito_set",
                            lambda: ([uni.Titolo(f"S{i}") for i in range(300)], "SET"))
        universo = uni.load_universe(ttl_ore=0)
        assert len(universo) == 150
        assert "CSV" in universo.fonte

    def test_senza_rete_non_chiama_la_rete(self, monkeypatch):
        def vietato():
            raise AssertionError("offline=True non deve toccare la rete")
        monkeypatch.setattr(uni, "dal_sito_set", vietato)
        monkeypatch.setattr(uni, "da_yahoo", vietato)
        universo = uni.load_universe(ttl_ore=0, offline=True)
        assert universo.parziale and len(universo) == 16

    def test_un_elenco_corto_non_e_il_mercato(self, monkeypatch):
        """Venti titoli possono essere una watchlist, non la borsa."""
        monkeypatch.setattr(uni, "dal_sito_set",
                            lambda: ([uni.Titolo(f"S{i}") for i in range(20)], "SET"))
        monkeypatch.setattr(uni, "da_yahoo", lambda: (_ for _ in ()).throw(FetchError("giu'")))
        universo = uni.load_universe(ttl_ore=0)
        assert len(universo) == 20
        assert universo.parziale
        assert any("20" in nota for nota in universo.note)

    def test_la_cache_evita_la_seconda_chiamata(self, monkeypatch):
        chiamate = []

        def una_volta():
            chiamate.append(1)
            return [uni.Titolo(f"C{i}") for i in range(200)], "SET"
        monkeypatch.setattr(uni, "dal_sito_set", una_volta)
        monkeypatch.setattr(uni, "da_yahoo", lambda: (_ for _ in ()).throw(FetchError("giu'")))
        primo = uni.load_universe()
        secondo = uni.load_universe()
        assert len(chiamate) == 1, "la seconda volta viene dalla cache"
        assert secondo.da_cache and not primo.da_cache
        assert secondo.simboli() == primo.simboli()

    def test_una_fonte_forzata_non_sporca_la_cache(self, monkeypatch):
        """Provare una fonte e' un'indagine: il risultato non vale per tutti."""
        monkeypatch.setattr(uni, "dal_sito_set",
                            lambda: ([uni.Titolo("SOLO")], "SET"))
        uni.load_universe(only=["set"])
        assert not os.path.exists(uni._percorso_cache())

    def test_i_popolari_restano_in_cima(self, monkeypatch):
        monkeypatch.setattr(uni, "dal_sito_set", lambda: (
            [uni.Titolo("ZZZZ")] + [uni.Titolo(f"A{i}") for i in range(200)]
            + [uni.Titolo("KBANK"), uni.Titolo("PTT")], "SET"))
        simboli = uni.load_universe(ttl_ore=0).simboli()
        assert simboli[0] == "PTT", "il primo dei molto scambiati"
        assert simboli.index("KBANK") < simboli.index("ZZZZ")


# --------------------------------------------------------------------------
# la ricerca dentro l'elenco
# --------------------------------------------------------------------------
class TestRicerca:
    @pytest.fixture
    def universo(self):
        return uni.Universo(titoli=[
            uni.Titolo("PTT", "PTT Public Company Limited"),
            uni.Titolo("PTTEP", "PTT Exploration and Production"),
            uni.Titolo("KBANK", "Kasikornbank"),
            uni.Titolo("SCB", "SCB X"),
            uni.Titolo("BBL", "Bangkok Bank"),
        ])

    def test_la_sigla_esatta_viene_prima(self, universo):
        assert [t.symbol for t in universo.cerca("ptt")] == ["PTT", "PTTEP"]

    def test_trova_anche_dal_nome(self, universo):
        trovati = [t.symbol for t in universo.cerca("bank")]
        assert "KBANK" in trovati and "BBL" in trovati
        assert trovati.index("KBANK") < trovati.index("BBL"), "prima la sigla, poi il nome"

    def test_senza_testo_da_i_primi(self, universo):
        assert len(universo.cerca("", limite=3)) == 3

    def test_niente_di_simile(self, universo):
        assert universo.cerca("qwerty") == []

    def test_etichetta_leggibile(self, universo):
        assert universo.titoli[0].etichetta() == "PTT - PTT Public Company Limited"
        assert uni.Titolo("XYZ").etichetta() == "XYZ", "senza nome, la sola sigla"


# --------------------------------------------------------------------------
# nelle due lingue
# --------------------------------------------------------------------------
class TestLingue:
    def test_la_provenienza_e_tradotta(self):
        universo = uni.Universo(titoli=[uni.Titolo("PTT")], fonte="SET", parziale=True)
        with using("en"):
            inglese = universo.provenienza()
        with using("it"):
            italiano = universo.provenienza()
        assert inglese != italiano
        assert "symbols from" in inglese and "simboli da" in italiano
