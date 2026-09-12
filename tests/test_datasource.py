"""Lo strato di scarico dati, con yfinance simulato.

Questo e' il punto piu' fragile dell'app: Yahoo Finance cambia forme e nomi
delle colonne fra le versioni, e per molti titoli thailandesi restituisce solo
una parte dei dati. Qui verifichiamo che nessuna di queste situazioni faccia
fallire l'analisi: al massimo produce un avviso.
"""

import sys
import types

import pandas as pd
import pytest

from setxray import datasource
from setxray.datasource import StockData, fetch_stock, latest_close, row, sum_last
from setxray.scoring import BUY, HOLD, SELL


# --------------------------------------------------------------------------
# yfinance finto
# --------------------------------------------------------------------------
def _prezzi(giorni=600, tz="Asia/Bangkok", con_adj=True):
    indice = pd.bdate_range(end="2026-09-11", periods=giorni, tz=tz)
    frame = pd.DataFrame({
        "Open": range(giorni), "High": range(giorni), "Low": range(giorni),
        "Close": [10.0 + i * 0.01 for i in range(giorni)],
        "Volume": [1_000_000.0] * giorni,
        "Dividends": [0.0] * giorni,
        "Stock Splits": [0.0] * giorni,
    }, index=indice)
    if con_adj:
        frame["Adj Close"] = frame["Close"] * 0.95
    return frame


def _conto_economico():
    date = pd.to_datetime(["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"])
    return pd.DataFrame(
        [[1000.0, 900, 820, 750], [120.0, 100, 88, 80], [3.0, 2.5, 2.2, 2.0]],
        index=["TotalRevenue", "NetIncome", "DilutedEPS"], columns=date,
    )


class TickerFinto:
    """Riproduce la superficie di yfinance.Ticker usata dall'app."""

    def __init__(self, symbol, *, guasto=False, vuoto=False):
        self.ticker = symbol
        self._guasto = guasto
        self._vuoto = vuoto

    def _forse(self, valore):
        if self._guasto:
            raise ConnectionError("Yahoo non risponde")
        if self._vuoto:
            return pd.DataFrame() if isinstance(valore, pd.DataFrame) else {}
        return valore

    @property
    def info(self):
        return self._forse({"longName": "Titolo Finto PCL", "currency": "THB",
                            "sector": "Energy", "marketCap": 5e10,
                            "sharesOutstanding": 1e9, "beta": 1.1})

    def history(self, **_):
        return self._forse(_prezzi())

    def get_income_stmt(self, **_):
        return self._forse(_conto_economico())

    def get_balance_sheet(self, **_):
        return self._forse(pd.DataFrame(
            [[800.0, 700, 640, 580]], index=["StockholdersEquity"],
            columns=pd.to_datetime(["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"])))

    def get_cash_flow(self, **_):
        return self._forse(pd.DataFrame(
            [[150.0, 130, 120, 110]], index=["OperatingCashFlow"],
            columns=pd.to_datetime(["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"])))

    @property
    def dividends(self):
        return self._forse(pd.Series([1.0, 1.1], index=pd.to_datetime(["2025-04-20", "2026-04-20"])))

    @property
    def analyst_price_targets(self):
        return self._forse({"mean": 22.0, "high": 28.0, "low": 15.0, "current": 16.0})

    @property
    def growth_estimates(self):
        return self._forse(pd.DataFrame({"stockTrend": [0.08]}, index=["+1y"]))

    @property
    def earnings_estimate(self):
        return self._forse(pd.DataFrame({"avg": [3.2], "growth": [0.07]}, index=["+1y"]))

    @property
    def revenue_estimate(self):
        return self._forse(pd.DataFrame({"avg": [1100.0], "growth": [0.10]}, index=["+1y"]))

    @property
    def recommendations(self):
        return self._forse(pd.DataFrame({"strongBuy": [2], "buy": [3]}, index=["0m"]))

    def get_valuation_measures(self, **_):
        return self._forse(pd.DataFrame(
            {"Current": [12.0], "12/31/2025": [11.0], "12/31/2024": [13.5]},
            index=["Trailing P/E"]))


@pytest.fixture
def yfinance_finto(monkeypatch, tmp_path):
    """Sostituisce yfinance e sposta la cache in una cartella temporanea."""
    monkeypatch.setattr(datasource, "_CACHE_DIR", str(tmp_path / "cache"))
    # La pausa fra i tentativi serve contro il limite di richieste di Yahoo.
    # Qui Yahoo non c'e': aspettare allungherebbe solo la suite.
    monkeypatch.setattr(datasource, "PAUSA_FRA_TENTATIVI", 0)
    modulo = types.ModuleType("yfinance")
    modulo.Ticker = TickerFinto
    monkeypatch.setitem(sys.modules, "yfinance", modulo)
    return modulo


# --------------------------------------------------------------------------
# prove
# --------------------------------------------------------------------------
class TestScaricoNormale:
    def test_riempie_tutti_i_campi(self, yfinance_finto):
        dati = fetch_stock("ptt", cache_ttl_min=0)
        assert dati.symbol == "PTT" and dati.yahoo_symbol == "PTT.BK"
        assert dati.name == "Titolo Finto PCL"
        assert dati.currency == "THB"
        assert dati.prices is not None and not dati.prices.empty
        assert dati.income_a is not None and dati.balance_a is not None
        assert dati.dividends is not None
        assert dati.analyst_targets["mean"] == 22.0
        assert not dati.warnings

    def test_prezzi_normalizzati(self, yfinance_finto):
        prezzi = fetch_stock("ptt", cache_ttl_min=0).prices
        # Il fuso orario va via: altrimenti il confronto con l'indice fallisce.
        assert prezzi.index.tz is None
        # "Adj Close" e "Stock Splits" prendono nomi senza spazi.
        assert "AdjClose" in prezzi.columns and "Splits" in prezzi.columns
        assert prezzi.index.is_monotonic_increasing

    def test_adj_close_ricostruito_se_manca(self, monkeypatch, yfinance_finto):
        monkeypatch.setattr(TickerFinto, "history",
                            lambda self, **_: _prezzi(con_adj=False))
        prezzi = fetch_stock("ptt", cache_ttl_min=0).prices
        assert (prezzi["AdjClose"] == prezzi["Close"]).all()

    def test_copertura_dichiarata(self, yfinance_finto):
        copertura = fetch_stock("ptt", cache_ttl_min=0).data_coverage()
        assert copertura["Price history"] and copertura["Income statement"]
        assert isinstance(copertura["Dividends"], bool)


class TestYahooCheNonCollabora:
    def test_errori_di_rete_non_fanno_fallire_lo_scarico(self, monkeypatch, yfinance_finto):
        monkeypatch.setattr(datasource, "_CACHE_DIR", "/dev/null/inesistente")
        yfinance_finto.Ticker = lambda simbolo: TickerFinto(simbolo, guasto=True)
        dati = fetch_stock("ptt", cache_ttl_min=0)
        assert dati.prices is None
        assert dati.warnings, "un errore deve diventare un avviso leggibile"
        assert all("unavailable" in avviso or "returns no data" in avviso
                   for avviso in dati.warnings)

    def test_risposte_vuote_diventano_avvisi(self, yfinance_finto):
        yfinance_finto.Ticker = lambda simbolo: TickerFinto(simbolo, vuoto=True)
        dati = fetch_stock("ptt", cache_ttl_min=0)
        assert dati.income_a is None
        assert any("returns no data" in avviso for avviso in dati.warnings)

    def test_indice_a_piu_livelli(self):
        """Alcune versioni di yfinance aggiungono il livello 'level_detail'."""
        frame = pd.DataFrame(
            [[1000.0]], columns=pd.to_datetime(["2025-12-31"]),
            index=pd.MultiIndex.from_tuples([("TotalRevenue", "Gross Profit")]),
        )
        assert row(frame, "TotalRevenue").iloc[0] == 1000.0


class TestStoricoPrezzi:
    """Lo storico e' il dato da cui nascono meta' dei grafici: vale insistere."""

    def test_colonne_a_due_livelli(self, monkeypatch, yfinance_finto):
        """Con le colonne a due livelli "Close" non si trovava, e i prezzi
        sembravano assenti mentre erano arrivati tutti."""
        def a_due_livelli(self, **_):
            frame = _prezzi()
            frame.columns = pd.MultiIndex.from_product([frame.columns, ["PTT.BK"]])
            return frame

        monkeypatch.setattr(TickerFinto, "history", a_due_livelli)
        prezzi = fetch_stock("ptt", cache_ttl_min=0).prices
        assert prezzi is not None and "Close" in prezzi.columns
        assert len(prezzi) == 600

    def test_ritenta_su_un_periodo_piu_corto(self, monkeypatch, yfinance_finto):
        """Yahoo che limita le richieste risponde con una tabella vuota, non con
        un errore: il secondo tentativo su un periodo corto spesso passa."""
        chiamate = []

        def a_strappi(self, **kwargs):
            if self.ticker != "PTT.BK":  # l'indice SET passa dalla stessa classe
                return _prezzi()
            chiamate.append(kwargs.get("period"))
            if len(chiamate) == 1:
                return pd.DataFrame()
            return _prezzi(giorni=300)

        monkeypatch.setattr(TickerFinto, "history", a_strappi)
        dati = fetch_stock("ptt", cache_ttl_min=0, history_period="10y")
        assert dati.prices is not None and len(dati.prices) == 300
        assert chiamate == ["10y", "5y"], "il ripiego deve chiedere meno storico"
        assert any("5y" in avviso for avviso in dati.warnings), \
            "il tentativo andato a vuoto resta scritto"

    def test_rinuncia_dopo_tutti_i_tentativi(self, monkeypatch, yfinance_finto):
        chiamate = []

        def sempre_vuoto(self, **kwargs):
            if self.ticker == "PTT.BK":
                chiamate.append(kwargs.get("period"))
            return pd.DataFrame()

        monkeypatch.setattr(TickerFinto, "history", sempre_vuoto)
        dati = fetch_stock("ptt", cache_ttl_min=0, history_period="11y")
        assert dati.prices is None
        assert chiamate == ["11y", "5y", "1y"]

    def test_una_sola_seduta_non_e_uno_storico(self, monkeypatch, yfinance_finto):
        """Una riga sola non fa una serie: meglio ritentare che tenerla."""
        monkeypatch.setattr(TickerFinto, "history",
                            lambda self, **_: _prezzi(giorni=1))
        dati = fetch_stock("ptt", cache_ttl_min=0)
        assert dati.prices is None

    def test_senza_prezzi_non_si_scrive_la_cache(self, monkeypatch, yfinance_finto):
        """Un fallimento di Yahoo congelato per un'ora sarebbe un titolo rotto
        fino allo scadere del tempo, senza modo di accorgersene."""
        monkeypatch.setattr(TickerFinto, "history", lambda self, **_: pd.DataFrame())
        fetch_stock("ptt", cache_ttl_min=60)
        monkeypatch.setattr(TickerFinto, "history", lambda self, **_: _prezzi())
        secondo = fetch_stock("ptt", cache_ttl_min=60)
        assert not secondo.from_cache and secondo.prices is not None


class TestCache:
    def test_riusa_i_dati_gia_scaricati(self, yfinance_finto):
        primo = fetch_stock("ptt", cache_ttl_min=60)
        assert not primo.from_cache
        secondo = fetch_stock("PTT.BK", cache_ttl_min=60)  # stesso titolo, altra grafia
        assert secondo.from_cache
        assert secondo.name == primo.name

    def test_ttl_zero_riscarica_sempre(self, yfinance_finto):
        fetch_stock("ptt", cache_ttl_min=60)
        assert not fetch_stock("ptt", cache_ttl_min=0).from_cache

    def test_svuotamento(self, yfinance_finto):
        fetch_stock("ptt", cache_ttl_min=60)
        assert datasource.clear_cache() >= 1
        assert not fetch_stock("ptt", cache_ttl_min=60).from_cache


class TestAiuti:
    def test_somma_degli_ultimi_trimestri(self):
        frame = pd.DataFrame([[10.0, 9, 8, 7, 6]], index=["TotalRevenue"],
                             columns=pd.to_datetime(["2026-06-30", "2026-03-31", "2025-12-31",
                                                     "2025-09-30", "2025-06-30"]))
        assert sum_last(frame, 4, "TotalRevenue") == 34.0
        assert sum_last(frame, 9, "TotalRevenue") is None  # meno periodi del richiesto

    def test_prezzo_dalla_scheda_se_manca_lo_storico(self):
        dati = StockData(symbol="X", yahoo_symbol="X.BK", info={"regularMarketPrice": 42.0})
        assert latest_close(dati) == 42.0
        assert latest_close(StockData(symbol="X", yahoo_symbol="X.BK")) is None

    @pytest.mark.parametrize("settore,industria,atteso", [
        ("Financial Services", "Banks - Regional", True),
        ("Financial Services", "Insurance - Life", True),
        ("Energy", "Oil & Gas Integrated", False),
        (None, None, False),
    ])
    def test_riconoscimento_dei_finanziari(self, settore, industria, atteso):
        # Banche e assicurazioni vanno valutate su P/B e ROE, non su EV/EBITDA.
        dati = StockData(symbol="X", yahoo_symbol="X.BK",
                         info={"sector": settore, "industry": industria})
        assert dati.is_financial is atteso


class TestDalloScaricoAlVerdetto:
    """La prova piu' importante: dati arrivati da yfinance -> decisione."""

    def test_catena_completa_su_dati_scaricati(self, yfinance_finto):
        from setxray.engine import analyze_data

        analisi = analyze_data(fetch_stock("ptt", cache_ttl_min=0))
        assert analisi.verdict.action in (BUY, HOLD, SELL)
        assert analisi.metrics.n_years == 4
        assert analisi.metrics.valuation["pe"] is not None
        assert analisi.report().startswith("# Titolo Finto PCL")

    def test_catena_completa_con_yahoo_muto(self, monkeypatch, yfinance_finto):
        """Se Yahoo non da' niente, l'errore deve essere spiegato all'utente."""
        from setxray.engine import NoDataError, analyze_data

        monkeypatch.setattr(datasource, "_CACHE_DIR", "/dev/null/inesistente")
        yfinance_finto.Ticker = lambda simbolo: TickerFinto(simbolo, guasto=True)
        with pytest.raises(NoDataError, match="No price available"):
            analyze_data(fetch_stock("ptt", cache_ttl_min=0))
