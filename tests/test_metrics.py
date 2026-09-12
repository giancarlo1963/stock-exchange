"""Le funzioni di calcolo: qui un errore si propaga a tutto il resto."""

import numpy as np
import pandas as pd
import pytest

from setxray.datasource import StockData, normalize_symbol, row
from setxray.metrics import cagr, compute_metrics, pct, percentile_of, safe_div


class TestNormalizzazioneSimbolo:
    @pytest.mark.parametrize("ingresso,atteso", [
        (" ptt ", ("PTT", "PTT.BK")),
        ("AOT.BK", ("AOT", "AOT.BK")),
        ("cpall", ("CPALL", "CPALL.BK")),
        ("SCB-R", ("SCB", "SCB.BK")),       # classe per investitori esteri
        ("ADVANC.BKK", ("ADVANC", "ADVANC.BK")),
    ])
    def test_forme_accettate(self, ingresso, atteso):
        assert normalize_symbol(ingresso) == atteso

    @pytest.mark.parametrize("ingresso", ["", "   ", ".BK", None])
    def test_ingressi_non_validi(self, ingresso):
        with pytest.raises(ValueError):
            normalize_symbol(ingresso)


class TestAiutiNumerici:
    def test_divisione_protetta(self):
        assert safe_div(10, 2) == 5
        assert safe_div(10, 0) is None
        assert safe_div(None, 2) is None
        assert safe_div(10, 1e-15) is None

    def test_cagr(self):
        assert cagr(100, 200, 2) == pytest.approx(0.4142, abs=1e-4)
        assert cagr(100, 100, 3) == 0

    def test_cagr_su_base_negativa_non_ha_senso(self):
        # Da una perdita non si calcola un tasso di crescita: meglio niente
        # che un numero che sembra valido.
        assert cagr(-50, 100, 3) is None
        assert cagr(100, -50, 3) is None
        assert cagr(100, 200, 0) is None

    def test_variazione_percentuale(self):
        assert pct(110, 100) == pytest.approx(0.10)
        assert pct(90, 100) == pytest.approx(-0.10)
        assert pct(10, 0) is None

    def test_percentile(self):
        serie = pd.Series([10.0, 12, 14, 16, 18])
        assert percentile_of(serie, 10) == pytest.approx(0.2)
        assert percentile_of(serie, 18) == pytest.approx(1.0)
        assert percentile_of(pd.Series([1.0, 2]), 1) is None  # troppo pochi dati


class TestLetturaBilanci:
    def _frame(self):
        return pd.DataFrame(
            {pd.Timestamp("2025-12-31"): [100.0, 20.0], pd.Timestamp("2024-12-31"): [90.0, 18.0]},
            index=["TotalRevenue", "NetIncome"],
        )

    def test_trova_la_voce_in_camel_case(self):
        assert row(self._frame(), "TotalRevenue").iloc[0] == 100.0

    def test_trova_la_voce_anche_scritta_diversamente(self):
        # yfinance cambia grafia fra versioni e con pretty=True.
        assert row(self._frame(), "Total Revenue").iloc[0] == 100.0
        assert row(self._frame(), "total_revenue").iloc[0] == 100.0

    def test_prova_le_alternative_in_ordine(self):
        assert row(self._frame(), "OperatingRevenue", "TotalRevenue").iloc[0] == 100.0

    def test_voce_assente(self):
        assert row(self._frame(), "Goodwill") is None
        assert row(None, "TotalRevenue") is None
        assert row(pd.DataFrame(), "TotalRevenue") is None


class TestDatiInsufficienti:
    def test_titolo_con_soli_prezzi_non_esplode(self):
        giorni = pd.bdate_range(end="2026-09-11", periods=400)
        prezzi = pd.DataFrame({"Close": np.linspace(10, 20, 400),
                               "AdjClose": np.linspace(10, 20, 400),
                               "Volume": 1e6}, index=giorni)
        dati = StockData(symbol="XYZ", yahoo_symbol="XYZ.BK", prices=prezzi,
                         info={"currency": "THB"})
        m = compute_metrics(dati)
        assert m.price == pytest.approx(20.0)
        assert m.n_years == 0
        assert m.notes, "un titolo senza bilanci deve dichiararlo"

    def test_titolo_completamente_vuoto(self):
        m = compute_metrics(StockData(symbol="XYZ", yahoo_symbol="XYZ.BK"))
        assert m.price is None
        assert m.n_years == 0
