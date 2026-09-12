"""Prove sull'intera catena: dal dato grezzo al report, senza rete."""

import re

import pandas as pd
import pytest

from setxray import charts
from setxray.datasource import StockData
from setxray.demo import PROFILES, build_demo
from setxray.engine import NoDataError, analyze, analyze_data
from setxray.narrative import build_report


@pytest.fixture(params=list(PROFILES))
def analisi(request):
    return analyze_data(build_demo(request.param))


class TestCatenaCompleta:
    def test_produce_tutte_le_parti(self, analisi):
        assert analisi.metrics.price > 0
        assert analisi.verdict.action
        assert set(analisi.narrative) == {"passato", "presente", "futuro", "dividendi"}
        for paragrafi in analisi.narrative.values():
            assert paragrafi, "ogni sezione ha almeno un paragrafo"
            assert all(isinstance(p, str) and p.strip() for p in paragrafi)

    def test_il_racconto_non_lascia_buchi(self, analisi):
        """Un 'n/d' nel testo passa, un segnaposto di formattazione no.

        La ricerca usa i confini di parola: 'finanziata' contiene 'nan'.
        """
        testo = " ".join(sum(analisi.narrative.values(), []))
        assert "{" not in testo and "}" not in testo
        for sospetto in (r"\bNone\b", r"\bnan\b", r"\bNaN\b", r"\binf\b"):
            assert not re.search(sospetto, testo), f"trovato {sospetto} nel racconto"

    def test_report_markdown(self, analisi):
        report = build_report(analisi)
        for sezione in ("# ", "## Perche'", "## Passato", "## Presente", "## Futuro",
                        "## Metodi di valutazione usati"):
            assert sezione in report
        assert "consulenza finanziaria" in report
        assert "{" not in report and not re.search(r"\bNone\b", report)

    def test_i_dati_dimostrativi_sono_dichiarati_nel_report(self, analisi):
        assert "DIMOSTRATIVI" in build_report(analisi)


class TestGrafici:
    def test_tutti_i_grafici_si_costruiscono(self, analisi):
        figure = charts.all_charts(analisi)
        assert len(figure) == 12
        for nome, figura in figure.items():
            assert figura.layout.height, f"{nome} senza altezza"

    def test_nessun_grafico_ha_due_assi_verticali(self, analisi):
        """Due scale verticali inventano correlazioni che nei dati non ci sono."""
        for nome, figura in charts.all_charts(analisi).items():
            assi = [chiave for chiave in figura.layout.to_plotly_json()
                    if chiave.startswith("yaxis")]
            secondari = [chiave for chiave in assi
                         if getattr(figura.layout[chiave], "overlaying", None) == "y"]
            assert not secondari, f"{nome} ha un secondo asse verticale"

    def test_grafici_su_dati_assenti_dicono_che_mancano(self):
        vuoto = StockData(symbol="XYZ", yahoo_symbol="XYZ.BK", info={"currency": "THB"},
                          prices=pd.DataFrame({"Close": [10.0, 11.0], "AdjClose": [10.0, 11.0]},
                                              index=pd.to_datetime(["2026-09-10", "2026-09-11"])))
        analisi = analyze_data(vuoto)
        for nome, figura in charts.all_charts(analisi).items():
            if not figura.data:  # segnaposto
                testi = [annotazione.text for annotazione in figura.layout.annotations]
                assert testi and any("disponibil" in t or "calcolabil" in t or "applicabil" in t
                                     or "Nessun" in t for t in testi), nome


class TestIngressoPubblico:
    @pytest.mark.parametrize("chiave", ["demo", "demo:solida", "demo-cara", "DEMO:dividendo"])
    def test_le_scorciatoie_demo_funzionano_senza_rete(self, chiave):
        assert analyze(chiave).verdict.action

    def test_profilo_demo_inesistente(self):
        with pytest.raises(ValueError, match="Profilo demo sconosciuto"):
            analyze("demo:inventato")

    def test_simbolo_non_valido_non_tocca_la_rete(self):
        with pytest.raises(ValueError):
            analyze("   ")

    def test_senza_prezzo_errore_chiaro(self):
        with pytest.raises(NoDataError, match="Nessun prezzo"):
            analyze_data(StockData(symbol="XYZ", yahoo_symbol="XYZ.BK"))


class TestCoerenzaInterna:
    def test_il_rendimento_atteso_coincide_col_verdetto(self, analisi):
        assert analisi.verdict.expected_return_2y == analisi.valuation.expected_return_2y
        assert analisi.verdict.entry_price == analisi.valuation.entry_price

    def test_il_prezzo_d_ingresso_e_sotto_il_valore_stimato(self, analisi):
        v = analisi.valuation
        if v.entry_price and v.fair_base:
            assert v.entry_price <= v.fair_base * 1.01

    def test_la_copertura_dei_dati_e_dichiarata(self, analisi):
        copertura = analisi.data.data_coverage()
        assert copertura["Prezzi storici"] is True
        assert all(isinstance(valore, bool) for valore in copertura.values())
