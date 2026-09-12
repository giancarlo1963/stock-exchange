"""Le fonti alternative dei dividendi.

Nessuna di queste API e' raggiungibile durante i test (e non deve esserlo: un
test che dipende dalla rete non e' un test). Quello che verifichiamo qui e' cio'
che conta davvero: che le risposte vengano lette bene, comprese le forme
diverse che ogni servizio usa, e che una fonte assente o guasta non faccia
fallire niente.
"""

import os

import pandas as pd
import pytest

from setxray.sources import collect_dividends, describe_sources
from setxray.sources.base import (
    DPS_MAX,
    _to_amount,
    _to_date,
    clean_series,
    parse_dividend_records,
)
from setxray.sources.csvfile import parse_csv
from setxray.sources.http import FetchError


class TestLetturaDate:
    def test_iso(self):
        assert _to_date("2025-04-25") == pd.Timestamp("2025-04-25")

    def test_convenzione_thailandese(self):
        """Il giorno viene prima del mese, come scrive la SET."""
        assert _to_date("25/04/2025") == pd.Timestamp("2025-04-25")
        # Questa e' la data ambigua: 5 settembre, non 9 maggio.
        assert _to_date("05/09/2024") == pd.Timestamp("2024-09-05")

    def test_timestamp_unix(self):
        assert _to_date(1745539200) == pd.Timestamp("2025-04-25")
        assert _to_date(1745539200000) == pd.Timestamp("2025-04-25")

    @pytest.mark.parametrize("valore", [None, "", "non una data", 0, -5, True, "1899-01-01"])
    def test_valori_da_scartare(self, valore):
        assert _to_date(valore) is None


class TestLetturaImporti:
    @pytest.mark.parametrize("valore,atteso", [
        (1.1, 1.1), ("1.1", 1.1), ("1,10", 1.1), ("THB 1.10", 1.1),
        ("12,50", 12.5),
        # Migliaia scritte alla europea e alla anglosassone: lo stesso numero.
        ("1.234,56", 1234.56), ("1,234.56", 1234.56),
    ])
    def test_formati(self, valore, atteso):
        assert _to_amount(valore) == pytest.approx(atteso)

    @pytest.mark.parametrize("valore", [None, True, 0, -1, "", "n/d", DPS_MAX + 1, 1e9])
    def test_fuori_scala_o_non_numerici(self, valore):
        # Un dividendo per azione di un titolo SET non vale mille baht: fuori
        # scala e' quasi sempre un campo sbagliato o un errore di unita'.
        assert _to_amount(valore) is None


class TestFormeDelleRisposte:
    """Ogni servizio usa nomi e strutture diversi per la stessa informazione."""

    def test_financial_modeling_prep(self):
        dati = {"symbol": "PTT.BK", "historical": [
            {"date": "2025-04-25", "adjDividend": 1.1, "dividend": 1.1,
             "recordDate": "2025-03-10", "paymentDate": "2025-05-02"},
            {"date": "2024-09-05", "adjDividend": 1.0, "dividend": 1.0},
        ]}
        serie = parse_dividend_records(dati)
        assert list(serie.index.strftime("%Y-%m-%d")) == ["2024-09-05", "2025-04-25"]
        assert serie.iloc[-1] == pytest.approx(1.1)

    def test_eodhd(self):
        dati = [{"date": "2025-04-25", "paymentDate": "2025-05-02", "period": "Final",
                 "value": 1.1, "unadjustedValue": 1.1, "currency": "THB"}]
        serie = parse_dividend_records(dati)
        assert serie.index[0] == pd.Timestamp("2025-04-25")

    def test_alpha_vantage(self):
        dati = {"symbol": "PTT.BKK", "data": [
            {"ex_dividend_date": "2025-04-25", "payment_date": "2025-05-02", "amount": "1.1"}]}
        assert parse_dividend_records(dati).index[0] == pd.Timestamp("2025-04-25")

    def test_forma_annidata_in_profondita(self):
        dati = {"data": {"rightsBenefits": [
            {"xdDate": "25/04/2025", "benefitType": "Cash Dividend",
             "dividendPerShare": "1.10", "paymentDate": "02/05/2025"}]}}
        assert parse_dividend_records(dati).iloc[0] == pytest.approx(1.10)

    def test_preferisce_la_data_di_stacco_non_quella_di_pagamento(self):
        """Lo stacco e' l'evento che fa scendere il prezzo, ed e' quello che
        registrano gli altri archivi: mescolarli sfaserebbe il confronto."""
        dati = [{"exDate": "2025-04-25", "paymentDate": "2025-06-30", "amount": 1.0}]
        assert parse_dividend_records(dati).index[0] == pd.Timestamp("2025-04-25")

    def test_scarta_i_dividendi_in_azioni(self):
        dati = [{"xdDate": "2025-04-25", "benefitType": "Cash Dividend", "amount": 1.0},
                {"xdDate": "2025-06-01", "benefitType": "Stock Dividend", "amount": 0.5}]
        serie = parse_dividend_records(dati)
        assert len(serie) == 1, "uno stock dividend non e' un pagamento in contanti"

    def test_somma_gli_stacchi_dello_stesso_giorno(self):
        dati = [{"exDate": "2025-04-25", "amount": 0.6},
                {"exDate": "2025-04-25", "amount": 0.4}]
        assert parse_dividend_records(dati).iloc[0] == pytest.approx(1.0)

    @pytest.mark.parametrize("dati", [None, {}, [], {"historical": []},
                                      {"Error Message": "chiave non valida"},
                                      [{"date": "2025-04-25"}], [{"amount": 1.0}]])
    def test_risposte_inutilizzabili(self, dati):
        assert parse_dividend_records(dati) is None


class TestFileCsv:
    @pytest.mark.parametrize("testo", [
        "data,importo\n2016-04-25,1.10\n2016-09-05,1.20\n",
        "date;dividend\n25/04/2016;1,10\n05/09/2016;1,20\n",
        "exDate\tamount\n2016-04-25\t1.10\n2016-09-05\t1.20\n",
        "2016-04-25,1.10\n2016-09-05,1.20\n",  # senza intestazione
    ])
    def test_scritture_accettate(self, testo):
        serie = parse_csv(testo)
        assert len(serie) == 2
        assert list(serie.index.strftime("%m-%d")) == ["04-25", "09-05"]
        assert serie.iloc[1] == pytest.approx(1.20)

    @pytest.mark.parametrize("testo", ["", "   ", "data,importo\n", "solo-una-colonna\n"])
    def test_file_vuoti_o_incompleti(self, testo):
        try:
            assert parse_csv(testo) is None
        except FetchError:
            pass  # anche un errore esplicito va bene, purche' non un crollo

    def test_file_su_disco(self, tmp_path, monkeypatch):
        from setxray.sources import csvfile

        percorso = tmp_path / "PTT-dividendi.csv"
        percorso.write_text("data,importo\n2016-04-25,1.10\n", encoding="utf-8")
        monkeypatch.setenv("SETXRAY_DIVIDEND_CSV", str(percorso))
        serie = csvfile.dividends("ptt")
        assert serie is not None and serie.iloc[0] == pytest.approx(1.10)

    def test_nessun_file_non_e_un_errore(self, monkeypatch, tmp_path):
        from setxray.sources import csvfile

        monkeypatch.delenv("SETXRAY_DIVIDEND_CSV", raising=False)
        monkeypatch.setattr(csvfile, "CARTELLE", (str(tmp_path),))
        assert csvfile.dividends("XYZ") is None


class TestPulizia:
    def test_ordina_somma_e_scarta(self):
        grezza = pd.Series(
            {"2016-09-05": 1.2, "2016-04-25": 1.1, "2016-04-25": 1.1, "2017-01-01": -5.0},
        )
        pulita = clean_series(grezza)
        assert pulita.index.is_monotonic_increasing
        assert (pulita > 0).all(), "gli importi non positivi vanno scartati"

    def test_toglie_il_fuso_orario(self):
        grezza = pd.Series([1.0], index=pd.DatetimeIndex(["2016-04-25"], tz="Asia/Bangkok"))
        assert clean_series(grezza).index.tz is None

    @pytest.mark.parametrize("grezza", [None, pd.Series(dtype="float64")])
    def test_serie_vuote(self, grezza):
        assert clean_series(grezza) is None


class TestRaccoltaEConfronto:
    def _serie(self, anni, importo=1.0, cadenza=2):
        date, valori = [], []
        for anno in anni:
            for mese in ([4, 9] if cadenza == 2 else [4]):
                date.append(pd.Timestamp(f"{anno}-{mese:02d}-25"))
                valori.append(importo)
        return pd.Series(valori, index=pd.DatetimeIndex(date))

    def test_nessuna_fonte_interrogata_senza_rete(self):
        """`only=[]` significa nessuna chiamata: e' cosi' che gira la demo."""
        insieme = collect_dividends("PTT", only=[], fallback=self._serie(range(2016, 2026)))
        assert insieme.ok
        assert insieme.chosen == "yahoo"
        assert len(insieme.results) == 1

    def test_vince_la_storia_piu_lunga(self, monkeypatch):
        import setxray.sources.base as base

        lunga = self._serie(range(2014, 2026))
        corta = self._serie(range(2022, 2026))
        monkeypatch.setattr(base, "_registro", lambda: [
            base.SourceSpec("csv", "File CSV locale", 5, None, lambda s: lunga),
        ])
        insieme = collect_dividends("PTT", fallback=corta)
        assert insieme.chosen == "csv"
        assert insieme.span_years > 10

    def test_a_pari_lunghezza_vince_la_fonte_piu_autorevole(self, monkeypatch):
        import setxray.sources.base as base

        stessa = self._serie(range(2016, 2026))
        monkeypatch.setattr(base, "_registro", lambda: [
            base.SourceSpec("set", "SET (sito ufficiale)", 5, None, lambda s: stessa.copy()),
        ])
        insieme = collect_dividends("PTT", fallback=stessa.copy())
        assert insieme.chosen == "set"

    def test_una_fonte_guasta_non_ferma_le_altre(self, monkeypatch):
        import setxray.sources.base as base

        def guasta(_):
            raise ConnectionError("host non raggiungibile")

        monkeypatch.setattr(base, "_registro", lambda: [
            base.SourceSpec("set", "SET (sito ufficiale)", 5, None, guasta),
        ])
        insieme = collect_dividends("PTT", fallback=self._serie(range(2016, 2026)))
        assert insieme.ok, "l'analisi deve continuare con la fonte che funziona"
        guasto = next(r for r in insieme.results if r.key == "set")
        assert "ConnectionError" in guasto.error

    def test_segnala_gli_anni_in_disaccordo(self, monkeypatch):
        import setxray.sources.base as base

        riferimento = self._serie(range(2016, 2026), importo=1.0)
        diversa = riferimento.copy()
        diversa.iloc[0] = 3.0  # un anno molto diverso
        monkeypatch.setattr(base, "_registro", lambda: [
            base.SourceSpec("csv", "File CSV locale", 5, None, lambda s: riferimento),
        ])
        insieme = collect_dividends("PTT", fallback=diversa)
        assert insieme.disagreements, "una differenza oltre il 5% va dichiarata"
        assert "disagrees with" in insieme.disagreements[0]

    def test_riconosce_la_confusione_fra_baht_e_satang(self, monkeypatch):
        import setxray.sources.base as base

        giusta = self._serie(range(2016, 2026), importo=1.0)
        centesimi = self._serie(range(2016, 2026), importo=0.01)
        monkeypatch.setattr(base, "_registro", lambda: [
            base.SourceSpec("csv", "File CSV locale", 5, None, lambda s: giusta),
        ])
        insieme = collect_dividends("PTT", fallback=centesimi)
        assert any("satang" in avviso for avviso in insieme.disagreements)

    def test_una_sola_fonte_viene_dichiarato(self):
        insieme = collect_dividends("PTT", only=[], fallback=self._serie(range(2016, 2026)))
        assert any("Only one source available" in nota for nota in insieme.notes)
        assert "No second source available" in insieme.provenance()

    def test_nessun_dividendo_da_nessuna_fonte(self):
        insieme = collect_dividends("PTT", only=[], fallback=None)
        assert not insieme.ok
        assert insieme.notes
        assert "No source returned any dividends" in insieme.provenance()


class TestRegistro:
    def test_elenco_completo_e_coerente(self):
        fonti = describe_sources()
        assert len(fonti) >= 5
        chiavi = {riga["key"] for riga in fonti}
        assert {"set", "csv", "yahoo"} <= chiavi
        for riga in fonti:
            assert riga["source"] and isinstance(riga["active"], bool)
            assert 1 <= riga["trust"] <= 5

    def test_le_fonti_senza_chiave_sono_sempre_attive(self):
        senza_chiave = [r for r in describe_sources() if r["api_key"] == "not needed"]
        assert all(r["active"] for r in senza_chiave)

    def test_selezione_da_variabile_d_ambiente(self, monkeypatch):
        from setxray.sources import requested_sources

        monkeypatch.setenv("SETXRAY_SOURCES", "csv, yahoo , inesistente")
        assert requested_sources() == ["csv", "yahoo"]
        monkeypatch.delenv("SETXRAY_SOURCES")
        assert requested_sources() is None


class TestChiaviApiAssenti:
    @pytest.mark.parametrize("modulo,variabile", [
        ("eodhd", "EODHD_API_KEY"), ("fmp", "FMP_API_KEY"),
        ("alphavantage", "ALPHAVANTAGE_API_KEY"),
    ])
    def test_errore_chiaro_senza_chiave(self, modulo, variabile, monkeypatch):
        import importlib

        monkeypatch.delenv(variabile, raising=False)
        fonte = importlib.import_module(f"setxray.sources.{modulo}")
        with pytest.raises(FetchError, match=variabile):
            fonte.dividends("PTT")


class TestSitoSet:
    def test_prova_piu_indirizzi(self):
        from setxray.sources import setofficial

        indirizzi = setofficial.endpoints()
        assert len(indirizzi) >= 3
        assert all("{symbol}" in indirizzo for indirizzo in indirizzi)

    def test_indirizzo_imposto_dall_utente_ha_la_precedenza(self, monkeypatch):
        from setxray.sources import setofficial

        monkeypatch.setenv("SETXRAY_SET_API", "https://esempio.invalido/{symbol}")
        assert setofficial.endpoints()[0] == "https://esempio.invalido/{symbol}"

    def test_smette_di_provare_se_l_host_non_risponde(self, monkeypatch):
        """Quattro indirizzi per quattro timeout sono quaranta secondi persi."""
        from setxray.sources import setofficial

        tentativi = []

        def finto(url, params=None, **kwargs):
            tentativi.append(url)
            raise FetchError("ConnectionError: host non raggiungibile")

        monkeypatch.setattr(setofficial, "get_json", finto)
        with pytest.raises(FetchError):
            setofficial.dividends("PTT")
        assert len(tentativi) == 1, "un host muto non va interrogato quattro volte"

    def test_prova_l_indirizzo_successivo_su_un_404(self, monkeypatch):
        from setxray.sources import setofficial

        tentativi = []

        def finto(url, params=None, **kwargs):
            tentativi.append(url)
            raise FetchError("HTTP 404 da www.set.or.th")

        monkeypatch.setattr(setofficial, "get_json", finto)
        with pytest.raises(FetchError):
            setofficial.dividends("PTT")
        assert len(tentativi) >= 3, "un indirizzo sbagliato non esclude gli altri"


class TestSettrade:
    """Settrade: la piattaforma della SET, stessa avvertenza del sito SET.

    Nessuno di questi indirizzi e' stato confermato contro il servizio vivo:
    dall'ambiente in cui il modulo e' stato scritto la rete verso i siti di
    mercato e' bloccata. Le prove qui coprono il comportamento che conta
    comunque - l'ordine dei tentativi, la resa quando la forma cambia, e il
    fatto che un errore finisca nel racconto invece di sparire.
    """

    def test_prova_piu_indirizzi(self):
        from setxray.sources import settrade

        indirizzi = settrade.endpoints()
        assert len(indirizzi) >= 3
        assert all("{symbol}" in indirizzo for indirizzo in indirizzi)
        assert all("settrade.com" in indirizzo for indirizzo in indirizzi)

    def test_indirizzo_imposto_dall_utente_ha_la_precedenza(self, monkeypatch):
        """Chi trova l'indirizzo giusto lo impone senza toccare il codice."""
        from setxray.sources import settrade

        monkeypatch.setenv("SETXRAY_SETTRADE_API", "https://esempio.invalido/{symbol}")
        assert settrade.endpoints()[0] == "https://esempio.invalido/{symbol}"

    def test_legge_gli_stacchi_quando_la_risposta_arriva(self, monkeypatch):
        from setxray.sources import settrade

        monkeypatch.setattr(settrade, "get_json", lambda url, params=None, **k: {
            "rightsBenefits": [
                {"xDate": "2025-04-24", "dividend": 1.20},
                {"xDate": "2025-09-05", "dividend": 1.10},
            ]})
        serie = settrade.dividends("PTT")
        assert len(serie) == 2
        assert float(serie.iloc[0]) == pytest.approx(1.20)

    def test_il_simbolo_entra_nell_indirizzo(self, monkeypatch):
        from setxray.sources import settrade

        visti = []

        def finto(url, params=None, **k):
            visti.append(url)
            return {"rightsBenefits": [{"xDate": "2025-04-24", "dividend": 1.0}]}

        monkeypatch.setattr(settrade, "get_json", finto)
        settrade.dividends("ptt.bk")
        assert "/PTT/" in visti[0], "normalizzato e senza suffisso"

    def test_smette_di_provare_se_l_host_non_risponde(self, monkeypatch):
        from setxray.sources import settrade

        tentativi = []

        def finto(url, params=None, **k):
            tentativi.append(url)
            raise FetchError("ConnectionError: host non raggiungibile")

        monkeypatch.setattr(settrade, "get_json", finto)
        with pytest.raises(FetchError):
            settrade.dividends("PTT")
        assert len(tentativi) == 1, "un host muto non va interrogato quattro volte"

    def test_prova_l_indirizzo_successivo_su_un_404(self, monkeypatch):
        from setxray.sources import settrade

        tentativi = []

        def finto(url, params=None, **k):
            tentativi.append(url)
            raise FetchError("HTTP 404 da www.settrade.com")

        monkeypatch.setattr(settrade, "get_json", finto)
        with pytest.raises(FetchError):
            settrade.dividends("PTT")
        assert len(tentativi) >= 3, "un indirizzo sbagliato non esclude gli altri"

    def test_forma_inattesa_diventa_un_errore_leggibile(self, monkeypatch):
        from setxray.sources import settrade

        monkeypatch.setattr(settrade, "get_json",
                            lambda url, params=None, **k: {"payload": {"ok": True}})
        with pytest.raises(FetchError) as errore:
            settrade.dividends("PTT")
        assert "dividend" in str(errore.value).lower()

    def test_e_nel_registro_con_la_fiducia_giusta(self):
        from setxray.sources import describe_sources

        righe = {r["key"]: r for r in describe_sources()}
        assert "settrade" in righe, "la fonte deve comparire nell'elenco"
        assert righe["settrade"]["trust"] == 5, "e' del gruppo SET: prima fila"
        assert righe["settrade"]["active"] is True, "non serve una chiave"
        assert righe["settrade"]["note"], "l'avvertenza va dichiarata"
