"""Il setaccio sul mercato, con l'analisi simulata.

Il setaccio decide con i soldi di qualcuno: se un criterio e' scritto male,
scarta un titolo buono o consiglia uno che ha tagliato il dividendo l'anno
scorso. Queste prove fissano il comportamento di ogni filtro, uno per uno, e
che il motivo dello scarto sia quello vero - perche' e' il motivo, non il
verdetto, che permette a chi legge di dissentire.
"""

import pytest

from setxray.lang import using
from setxray import screener as sc


class DividendiFinti:
    def __init__(self, **campi):
        self.yield_stats = campi.get("yield_stats", {"attuale": 0.07, "mediana": 0.05,
                                                     "percentile": 0.9})
        self.streaks = campi.get("streaks", {"anni_consecutivi_pagati": 10, "tagli": 0})
        self.growth = campi.get("growth", {"cagr_5y": 0.04})
        self.safety = campi.get("safety", type("S", (), {"score": 74.0,
                                                         "cut_risk_band": "low"})())
        self.signal = campi.get("signal", type("G", (), {"action": "BUY"})())
        self._paga = campi.get("paga", True)

    @property
    def pays_dividends(self):
        return self._paga


class MetricheFinte:
    def __init__(self, payout=0.6, nome="Finta PCL", settore="Energy", prezzo=10.0):
        self.name, self.sector, self.price = nome, settore, prezzo
        self.dividend = {"payout": payout}


class AnalisiFinta:
    def __init__(self, metrics=None, dividends=None):
        self.metrics = metrics or MetricheFinte()
        self.dividends = dividends if dividends is not None else DividendiFinti()


@pytest.fixture
def analisi(monkeypatch):
    """Sostituisce analyze() con una fabbrica di analisi su misura."""
    fabbrica = {}

    def finto(symbol, **_):
        if symbol.upper() in fabbrica.get("errori", ()):
            raise RuntimeError("Yahoo non risponde")
        return fabbrica.get(symbol.upper(), AnalisiFinta())

    import setxray.engine
    monkeypatch.setattr(setxray.engine, "analyze", finto)
    return fabbrica


class TestIFiltri:
    def test_un_titolo_sano_passa(self, analisi):
        c = sc.valuta("PTT")
        assert c.passa and c.punteggio > 60
        assert c.rendimento == 0.07 and c.anni_pagati == 10

    def test_chi_non_paga_e_fuori(self, analisi):
        analisi["NOPAY"] = AnalisiFinta(dividends=DividendiFinti(paga=False))
        c = sc.valuta("NOPAY")
        assert not c.passa and "dividend" in c.scartato

    def test_rendimento_sotto_la_soglia(self, analisi):
        analisi["MAGRO"] = AnalisiFinta(dividends=DividendiFinti(
            yield_stats={"attuale": 0.015, "mediana": 0.02, "percentile": 0.3}))
        c = sc.valuta("MAGRO")
        assert not c.passa and "1.5%" in c.scartato

    def test_paga_da_troppo_poco(self, analisi):
        analisi["GIOVANE"] = AnalisiFinta(dividends=DividendiFinti(
            streaks={"anni_consecutivi_pagati": 2, "tagli": 0}))
        c = sc.valuta("GIOVANE")
        assert not c.passa and "2" in c.scartato

    def test_sicurezza_insufficiente(self, analisi):
        analisi["FRAGILE"] = AnalisiFinta(dividends=DividendiFinti(
            safety=type("S", (), {"score": 41.0, "cut_risk_band": "medium"})()))
        c = sc.valuta("FRAGILE")
        assert not c.passa and "41" in c.scartato

    def test_chi_ha_tagliato_e_fuori(self, analisi):
        analisi["TAGLIA"] = AnalisiFinta(dividends=DividendiFinti(
            streaks={"anni_consecutivi_pagati": 8, "tagli": 3}))
        c = sc.valuta("TAGLIA")
        assert not c.passa and "3" in c.scartato

    def test_payout_oltre_gli_utili(self, analisi):
        analisi["SPENDE"] = AnalisiFinta(metrics=MetricheFinte(payout=1.4))
        c = sc.valuta("SPENDE")
        assert not c.passa and "140%" in c.scartato

    def test_rischio_di_taglio_alto(self, analisi):
        analisi["RISCHIO"] = AnalisiFinta(dividends=DividendiFinti(
            safety=type("S", (), {"score": 72.0, "cut_risk_band": "high"})()))
        c = sc.valuta("RISCHIO")
        assert not c.passa and "high" in c.scartato

    def test_quello_che_ho_gia_non_me_lo_consigli(self, analisi):
        c = sc.valuta("PTT", sc.Criteri(escludi=frozenset({"PTT"})))
        assert not c.passa and "portfolio" in c.scartato or "portafoglio" in c.scartato

    def test_un_errore_di_rete_non_ferma_la_passata(self, analisi):
        analisi["errori"] = {"ROTTO"}
        c = sc.valuta("ROTTO")
        assert not c.passa and "RuntimeError" in c.scartato

    def test_i_criteri_si_possono_allentare(self, analisi):
        analisi["MAGRO"] = AnalisiFinta(dividends=DividendiFinti(
            yield_stats={"attuale": 0.025, "mediana": 0.02, "percentile": 0.6}))
        assert not sc.valuta("MAGRO").passa
        assert sc.valuta("MAGRO", sc.Criteri(rendimento_minimo=0.02)).passa


class TestPunteggio:
    def test_le_quattro_voci_sommano_a_cento(self):
        perfetto = sc.Candidato("X", rendimento=0.09, sicurezza=100, anni_pagati=12,
                                percentile=1.0, tagli=0)
        assert sc.punteggio(perfetto) == 100.0

    def test_i_tagli_costano(self):
        base = dict(rendimento=0.07, sicurezza=80, anni_pagati=10, percentile=0.8)
        pulito = sc.punteggio(sc.Candidato("A", tagli=0, **base))
        sporco = sc.punteggio(sc.Candidato("B", tagli=2, **base))
        assert pulito - sporco == pytest.approx(10.0)

    def test_la_penalita_ha_un_tetto(self):
        base = dict(rendimento=0.07, sicurezza=80, anni_pagati=10, percentile=0.8)
        assert (sc.punteggio(sc.Candidato("A", tagli=3, **base))
                == sc.punteggio(sc.Candidato("B", tagli=9, **base)))

    def test_rendimento_altissimo_non_sfonda_il_tetto(self):
        """Un rendimento del 30% e' un avviso, non un punteggio tre volte piu' alto."""
        a = sc.punteggio(sc.Candidato("A", rendimento=0.08, sicurezza=70, anni_pagati=10,
                                      percentile=0.5))
        b = sc.punteggio(sc.Candidato("B", rendimento=0.30, sicurezza=70, anni_pagati=10,
                                      percentile=0.5))
        assert a == b

    def test_senza_storia_il_percentile_non_regala_punti(self):
        c = sc.Candidato("X", rendimento=0.06, sicurezza=70, anni_pagati=5, percentile=None)
        assert sc.punteggio(c) == sc.punteggio(
            sc.Candidato("Y", rendimento=0.06, sicurezza=70, anni_pagati=5, percentile=0.5))


class TestLaPassata:
    def test_scorre_la_preselezione_e_divide_i_due_gruppi(self, analisi, monkeypatch):
        analisi["BRUTTO"] = AnalisiFinta(metrics=MetricheFinte(payout=1.5))
        monkeypatch.setattr(sc, "preselezione",
                            lambda *a, **k: (["PTT", "BRUTTO", "AOT"], 812, ["nota"]))
        visti = []
        r = sc.screen(pausa=0, avanzamento=lambda f, t, s: visti.append(s))
        assert r.esaminati == 3 and len(r.candidati) == 2 and len(r.scartati) == 1
        assert r.universo == 812 and r.preselezionati == 3
        assert visti == ["PTT", "BRUTTO", "AOT"], "l'avanzamento va chiamato per ogni titolo"
        assert r.scartati[0].symbol == "BRUTTO"

    def test_i_migliori_sono_ordinati_per_punteggio(self):
        r = sc.Risultato(candidati=[sc.Candidato("A", punteggio=61),
                                    sc.Candidato("B", punteggio=88),
                                    sc.Candidato("C", punteggio=74)])
        assert [c.symbol for c in r.migliori(2)] == ["B", "C"]

    def test_lo_screener_di_yahoo_che_non_risponde_non_e_fatale(self, monkeypatch):
        """Se il filtro lato server non c'e', si ripiega sull'elenco completo."""
        import setxray.universe as u
        monkeypatch.setattr(sc, "_da_screener_yahoo",
                            lambda soglia, limite: ([], ["screener non disponibile"]))
        monkeypatch.setattr(u, "load_universe", lambda **k: u.Universo(
            titoli=[u.Titolo("PTT", "PTT PCL"), u.Titolo("AOT", "AOT PCL")],
            fonte="prova", note=[]))
        simboli, quanti, note = sc.preselezione(sc.Criteri(), limite=10, offline=False)
        assert simboli == ["PTT", "AOT"] and quanti == 2
        assert any("screener" in n for n in note)

    def test_la_preselezione_rispetta_le_esclusioni(self, monkeypatch):
        monkeypatch.setattr(sc, "_da_screener_yahoo",
                            lambda soglia, limite: (["PTT", "AOT", "SCB"], []))
        simboli, _, _ = sc.preselezione(sc.Criteri(escludi=frozenset({"AOT"})),
                                        limite=10, offline=True)
        assert "AOT" not in simboli


class TestEsclusioniDaFile:
    def test_legge_una_sigla_per_riga(self, tmp_path):
        f = tmp_path / "mie.txt"
        f.write_text("PTT\nAOT\nscb.bk\n\n")
        assert sc.simboli_da_file(str(f)) == {"PTT", "AOT", "SCB"}

    def test_legge_la_prima_colonna_di_un_csv(self, tmp_path):
        f = tmp_path / "mie.csv"
        f.write_text("symbol,qty\nBBL,20200\nKBANK,5300\n")
        assert sc.simboli_da_file(str(f)) == {"SYMBOL", "BBL", "KBANK"}

    def test_un_file_che_non_esiste_non_e_un_errore(self, tmp_path):
        assert sc.simboli_da_file(str(tmp_path / "niente.txt")) == frozenset()


def test_i_criteri_si_descrivono_nelle_due_lingue():
    with using("en"):
        righe = sc.Criteri().descrizione()
        assert any("dividend yield at least 4.0%" in r for r in righe)
    with using("it"):
        righe = sc.Criteri().descrizione()
        assert any("rendimento da dividendo almeno 4.0%" in r for r in righe)
