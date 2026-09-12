"""Prove sull'intera catena: dal dato grezzo al report, senza rete."""

import re

import pandas as pd
import pytest

from setxray import charts
from setxray.datasource import StockData
from setxray.demo import PROFILE_KEYS, build_demo
from setxray.engine import NoDataError, analyze, analyze_data
from setxray.narrative import build_report


@pytest.fixture(params=list(PROFILE_KEYS))
def analisi(request):
    return analyze_data(build_demo(request.param))


class TestCatenaCompleta:
    def test_produce_tutte_le_parti(self, analisi):
        assert analisi.metrics.price > 0
        assert analisi.verdict.action
        assert set(analisi.narrative) == {"past", "present", "future", "dividends"}
        for paragrafi in analisi.narrative.values():
            assert paragrafi, "ogni sezione ha almeno un paragrafo"
            assert all(isinstance(p, str) and p.strip() for p in paragrafi)

    def test_il_racconto_non_lascia_buchi(self, analisi):
        """Un 'n/a' nel testo passa, un segnaposto di formattazione no.

        La ricerca usa i confini di parola: 'finanziata' contiene 'nan'.
        """
        testo = " ".join(sum(analisi.narrative.values(), []))
        assert "{" not in testo and "}" not in testo
        for sospetto in (r"\bNone\b", r"\bnan\b", r"\bNaN\b", r"\binf\b"):
            assert not re.search(sospetto, testo), f"trovato {sospetto} nel racconto"

    def test_report_markdown(self, analisi):
        report = build_report(analisi)
        for sezione in ("# ", "## Why", "## Past", "## Present", "## Future",
                        "## Valuation methods used"):
            assert sezione in report
        assert "financial advice" in report
        assert "{" not in report and not re.search(r"\bNone\b", report)

    def test_i_dati_dimostrativi_sono_dichiarati_nel_report(self, analisi):
        assert "DEMONSTRATION" in build_report(analisi)


class TestGrafici:
    def test_tutti_i_grafici_si_costruiscono(self, analisi):
        figure = charts.all_charts(analisi)
        assert len(figure) == 13
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
                assert testi and any("not available" in t or "cannot be computed" in t
                                     or "not applicable" in t or "No " in t
                                     or "too short" in t for t in testi), nome


class TestIngressoPubblico:
    @pytest.mark.parametrize("chiave", ["demo", "demo:solida", "demo-cara", "DEMO:dividendo"])
    def test_le_scorciatoie_demo_funzionano_senza_rete(self, chiave):
        assert analyze(chiave).verdict.action

    def test_profilo_demo_inesistente(self):
        with pytest.raises(ValueError, match="Unknown demo profile"):
            analyze("demo:inventato")

    def test_simbolo_non_valido_non_tocca_la_rete(self):
        with pytest.raises(ValueError):
            analyze("   ")

    def test_senza_prezzo_errore_chiaro(self):
        with pytest.raises(NoDataError, match="No price available"):
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
        assert copertura["Price history"] is True
        assert all(isinstance(valore, bool) for valore in copertura.values())


class TestRSINelRacconto:
    """L'RSI compare a parole solo quando dice qualcosa."""

    def _con_coda(self, profilo: str, fattore: float):
        """Lo stesso titolo con gli ultimi 40 giorni tutti nella stessa direzione."""
        dati = build_demo(profilo)
        prezzi = dati.prices.copy()
        coda = prezzi.index[-40:]
        moltiplicatori = pd.Series(
            [fattore ** (i + 1) for i in range(len(coda))], index=coda)
        for colonna in ("Close", "AdjClose", "Open", "High", "Low"):
            if colonna in prezzi:
                prezzi.loc[coda, colonna] = prezzi.loc[coda, colonna] * moltiplicatori
        dati.prices = prezzi
        return analyze_data(dati)

    def test_ipervenduto_viene_detto(self):
        analisi = self._con_coda("solida", 0.985)
        assert analisi.metrics.trend["rsi"] < 30
        frasi = [p for p in analisi.narrative["present"] if "RSI" in p]
        assert frasi and "oversold" in frasi[0]

    def test_ipercomprato_viene_detto(self):
        analisi = self._con_coda("dividendo", 1.015)
        assert analisi.metrics.trend["rsi"] > 70
        frasi = [p for p in analisi.narrative["present"] if "RSI" in p]
        assert frasi and "overbought" in frasi[0]

    def test_in_mezzo_non_si_dice_niente(self):
        """Una frase che non aggiunge niente fa perdere fiducia in quelle accanto."""
        analisi = analyze_data(build_demo("tagliato"))
        assert 30 < analisi.metrics.trend["rsi"] < 70
        assert not [p for p in analisi.narrative["present"] if "RSI" in p]

    def test_il_grafico_dice_la_zona(self):
        from setxray import charts

        analisi = self._con_coda("solida", 0.985)
        fig = charts.rsi_chart(analisi.metrics, analisi.data.prices)
        assert "oversold" in fig.layout.title.text


class TestRSISuPiuPeriodi:
    """Quattordici sessioni sono una convenzione, non l'unica domanda sensata.

    Chi tiene un titolo per anni vuole la stessa misura sul proprio orizzonte.
    Ma allungando il periodo la media smorzata schiaccia tutto verso il 50: su
    un anno di sessioni l'RSI non arriva mai a 70 ne' a 30, e disegnare comunque
    quelle due righe sarebbe decorazione. Per i periodi lunghi la fascia diventa
    quindi la meta' centrale della storia del titolo, come per il rendimento e
    per il P/E.
    """

    def _fasce(self, fig):
        """(alto, basso) leggendoli dalle due fasce disegnate."""
        alta, bassa = fig.layout.shapes[0], fig.layout.shapes[1]
        return alta.y0, bassa.y1

    def test_a_quattordici_le_soglie_restano_fisse(self):
        from setxray import charts

        analisi = analyze_data(build_demo("solida"))
        fig = charts.rsi_chart(analisi.metrics, analisi.data.prices, periodi=14)
        assert self._fasce(fig) == (70.0, 30.0)
        assert tuple(fig.layout.yaxis.range) == (0, 100)
        assert "overbought 70" in fig.to_plotly_json()["layout"]["annotations"][-2]["text"]

    def test_sui_periodi_lunghi_la_fascia_e_la_storia_del_titolo(self):
        from setxray import charts
        from setxray.metrics import rsi

        analisi = analyze_data(build_demo("solida"))
        serie = rsi(analisi.data.prices["Close"], periods=252)
        fig = charts.rsi_chart(analisi.metrics, analisi.data.prices, periodi=252)
        alto, basso = self._fasce(fig)
        assert alto == pytest.approx(float(serie.quantile(0.75)))
        assert basso == pytest.approx(float(serie.quantile(0.25)))
        # le soglie fisse qui non verrebbero mai toccate
        assert 30 < basso < alto < 70
        assert "middle half" in fig.layout.title.text

    def test_la_fascia_non_si_muove_con_lo_zoom(self):
        """Una fascia che cambia quando si cambia finestra non e' un
        riferimento: e' il riflesso di quello che si sta guardando."""
        from setxray import charts

        analisi = analyze_data(build_demo("solida"))
        stretta = charts.rsi_chart(analisi.metrics, analisi.data.prices, periodi=252, anni=0.5)
        larga = charts.rsi_chart(analisi.metrics, analisi.data.prices, periodi=252, anni=5.0)
        assert self._fasce(stretta) == self._fasce(larga)

    def test_la_finestra_taglia_solo_il_disegno(self):
        from setxray import charts

        analisi = analyze_data(build_demo("solida"))
        punti = []
        for anni in (1.0, 3.0):
            fig = charts.rsi_chart(analisi.metrics, analisi.data.prices, anni=anni)
            punti.append(len(fig.data[0].x))
        assert punti[0] < punti[1], "meno anni, meno punti disegnati"

    def test_il_titolo_dice_il_periodo_in_parole(self):
        from setxray import charts

        analisi = analyze_data(build_demo("solida"))
        for periodi, atteso in ((14, "14 sessions"), (126, "6 months"), (756, "3 years")):
            fig = charts.rsi_chart(analisi.metrics, analisi.data.prices, periodi=periodi)
            assert atteso in fig.layout.title.text

    def test_storico_troppo_corto_lo_dice(self):
        """Un riquadro vuoto senza spiegazione sembra un grafico rotto."""
        from setxray import charts

        analisi = analyze_data(build_demo("solida"))
        corto = analisi.data.prices.tail(100)
        fig = charts.rsi_chart(analisi.metrics, corto, periodi=756)
        scritta = fig.layout.annotations[0].text
        assert "too short" in scritta and "3 years" in scritta

    def test_ogni_periodo_offerto_e_disegnabile(self):
        from setxray import charts

        analisi = analyze_data(build_demo("solida"))
        for periodi in charts.PERIODI_RSI:
            for anni in charts.FINESTRE_RSI:
                fig = charts.rsi_chart(analisi.metrics, analisi.data.prices,
                                       periodi=periodi, anni=anni)
                assert fig.data, f"{periodi} sessioni su {anni} anni non disegna niente"

    def test_i_nomi_nelle_due_lingue(self):
        from setxray import charts
        from setxray.lang import using

        with using("en"):
            assert charts.nome_periodo(126) == "6 months"
            assert charts.nome_finestra(0.5) == "last 6 months"
            assert charts.nome_finestra(1.0) == "last year"
        with using("it"):
            assert charts.nome_periodo(126) == "6 mesi"
            assert charts.nome_finestra(0.5) == "ultimi 6 mesi"
            assert charts.nome_finestra(3.0) == "ultimi 3 anni"
