"""Il motore dei dividendi: l'obiettivo dichiarato dello strumento.

Le prove piu' importanti sono quelle che verificano che il modello *non* si
entusiasmi davanti a un rendimento alto ottenuto perche' il prezzo e' crollato:
e' l'errore che costa piu' caro a chi investe per la cedola.
"""

import numpy as np
import pandas as pd
import pytest

from setxray.demo import PROFILES, build_demo
from setxray.dividends import (
    MARGINE_SICUREZZA,
    RENDIMENTO_MAX,
    RENDIMENTO_MIN,
    _consecutive_changes,
    _indicated_dividend_series,
    analyze_dividends,
)
from setxray.engine import analyze, analyze_data
from setxray.metrics import compute_metrics
from setxray.scoring import BUY, SELL
from setxray.sources import collect_dividends


@pytest.fixture(scope="module")
def analisi():
    """Un'analisi per profilo, calcolata una volta sola."""
    return {profilo: analyze(f"demo:{profilo}") for profilo in PROFILES}


# --------------------------------------------------------------------------
# ricostruzione della storia
# --------------------------------------------------------------------------
class TestStoriaDeiDividendi:
    def test_dieci_anni_di_storia(self, analisi):
        d = analisi["dividendo"].dividends
        assert d.pays_dividends
        assert d.span_years >= 10
        completi = d.complete_years()
        assert len(completi) >= 10, "l'obiettivo e' una lettura a dieci anni"

    def test_l_anno_in_corso_non_entra_nelle_medie(self, analisi):
        d = analisi["dividendo"].dividends
        anno_corrente = pd.Timestamp.now().year
        completi = d.complete_years()
        assert anno_corrente not in completi.index, \
            "l'anno in corso e' incompleto e falserebbe ogni media"
        assert anno_corrente in d.years.index, "ma va comunque mostrato"

    def test_cadenza_riconosciuta(self, analisi):
        assert analisi["dividendo"].dividends.cadence == 2
        assert analisi["irregolare"].dividends.cadence == 1

    def test_titolo_senza_dividendi(self, analisi):
        d = analisi["difficolta"].dividends
        assert not d.pays_dividends
        assert d.notes and "CSV" in " ".join(d.notes), \
            "va detto come fornire i dati a mano"
        assert d.signal is None

    def test_tabella_per_anno_completa(self, analisi):
        anni = analisi["dividendo"].dividends.years
        for colonna in ("dps", "stacchi", "prezzo_medio", "rendimento", "payout",
                        "copertura_cassa", "completo", "variazione"):
            assert colonna in anni.columns


class TestCrescitaETagli:
    def test_crescita_su_tre_orizzonti(self, analisi):
        crescita = analisi["dividendo"].dividends.growth
        for chiave in ("cagr_3y", "cagr_5y", "cagr_10y"):
            assert crescita[chiave] == pytest.approx(0.035, abs=0.01)

    def test_riconosce_il_taglio(self, analisi):
        d = analisi["tagliato"].dividends
        assert d.streaks["tagli"] == 1
        assert d.streaks["taglio_massimo"] < -0.4
        assert d.streaks["anno_ultimo_taglio"] == 2020

    def test_il_taglio_si_vede_nella_crescita_a_dieci_anni(self, analisi):
        """A cinque anni la risalita dal minimo sembra ottima: e' la trappola."""
        crescita = analisi["tagliato"].dividends.growth
        assert crescita["cagr_10y"] < 0
        assert crescita["cagr_5y"] > 0
        assert crescita["cagr_10y"] < crescita["cagr_5y"]

    def test_nessuna_crescita_media_per_un_pagatore_irregolare(self, analisi):
        """Con un anno a zero dentro la finestra il CAGR non ha significato."""
        crescita = analisi["irregolare"].dividends.growth
        assert crescita["irregolare"] is True
        assert crescita["cagr_10y"] is None
        assert crescita["cagr_5y"] is None

    def test_anni_saltati_contati(self, analisi):
        assert analisi["irregolare"].dividends.streaks["anni_saltati"] >= 3
        assert analisi["dividendo"].dividends.streaks["anni_saltati"] == 0

    def test_variazioni_solo_fra_anni_consecutivi(self):
        """Saltare il 2020 e il 2021 non e' un taglio dal 2019 al 2022."""
        tabella = pd.DataFrame(
            {"dps": [1.0, 0.0, 0.0, 1.2], "completo": [True] * 4},
            index=[2019, 2020, 2021, 2022],
        )
        variazioni = _consecutive_changes(tabella)
        assert list(variazioni.index) == [], \
            "nessuna coppia di anni adiacenti con entrambi i dividendi positivi"

    def test_aumenti_consecutivi(self, analisi):
        assert analisi["dividendo"].dividends.streaks["aumenti_consecutivi"] >= 9


# --------------------------------------------------------------------------
# rendimento contro la propria storia
# --------------------------------------------------------------------------
class TestRendimento:
    def test_serie_giornaliera_senza_punte(self, analisi):
        """La serie storica deve usare lo stesso criterio del rendimento di oggi.

        Con una finestra di 365 giorni su stacchi a date quasi fisse, il numero
        di pagamenti dentro la finestra oscilla fra uno e due e la serie si
        riempie di punte verticali che non esistono.
        """
        d = analisi["dividendo"].dividends
        serie = d.daily_yield
        assert serie is not None and len(serie) > 1000
        salti = serie.pct_change().abs().dropna()
        assert salti.max() < 0.30, "una punta oltre il 30% in un giorno e' un artefatto"

    def test_percentile_coerente_col_valore_di_oggi(self, analisi):
        d = analisi["dividendo"].dividends
        stat = d.yield_stats
        assert 0 <= stat["percentile"] <= 1
        assert stat["p25"] <= stat["mediana"] <= stat["p75"]
        # Il rendimento di oggi deve stare nella scala della propria serie.
        assert stat["minimo"] <= stat["attuale"] <= stat["massimo"] * 1.2

    def test_dividendo_indicato_usa_gli_ultimi_stacchi(self):
        pagamenti = pd.Series(
            [1.0, 1.1, 1.2, 1.3],
            index=pd.to_datetime(["2024-04-25", "2024-09-05", "2025-04-25", "2025-09-05"]),
        )
        indice = pd.bdate_range("2024-01-01", "2025-12-31")
        serie = _indicated_dividend_series(pagamenti, indice, cadence=2)
        # Dopo l'ultimo stacco: la somma degli ultimi due.
        assert serie.iloc[-1] == pytest.approx(2.5)

    def test_rendimento_su_titolo_che_non_paga(self, analisi):
        assert analisi["difficolta"].dividends.daily_yield is None


class TestRendimentoTotale:
    def test_scomposizione(self, analisi):
        tr = analisi["dividendo"].dividends.total_return
        assert tr["anni"] >= 9
        assert tr["totale_reinvestito"] > tr["solo_prezzo"], \
            "reinvestire le cedole non puo' peggiorare il risultato"
        assert tr["contributo_dividendi"] > 0

    def test_quota_dei_dividendi_sul_totale(self, analisi):
        """Puo' superare il 100%: se il prezzo e' sceso, le cedole hanno
        prodotto tutto il rendimento e hanno anche coperto la perdita."""
        tr = analisi["dividendo"].dividends.total_return
        assert tr["quota_dividendi"] > 0
        if tr["solo_prezzo"] >= 0:
            assert tr["quota_dividendi"] <= 1

    def test_rendimento_sul_prezzo_di_acquisto(self, analisi):
        yoc = analisi["dividendo"].dividends.yield_on_cost
        orizzonti = [chiave for chiave in ("10y", "5y") if chiave in yoc]
        assert orizzonti, "con dieci anni di prezzi almeno un orizzonte va calcolato"
        for orizzonte in orizzonti:
            assert yoc[orizzonte] > 0
            assert yoc[f"prezzo_{orizzonte}"] > 0


# --------------------------------------------------------------------------
# solidita' del dividendo
# --------------------------------------------------------------------------
class TestSolidita:
    def test_punteggio_e_fattori(self, analisi):
        sicurezza = analisi["dividendo"].dividends.safety
        assert 0 <= sicurezza.score <= 100
        assert sicurezza.band in ("solid", "watch closely", "at risk")
        assert sicurezza.cut_risk_band in ("low", "medium", "high")
        assert len(sicurezza.factors) >= 6
        for fattore in sicurezza.factors:
            assert fattore.label and fattore.explanation

    def test_i_punti_spiegano_il_punteggio(self, analisi):
        """Si parte da 50: la somma dei punti deve ricostruire il totale."""
        sicurezza = analisi["dividendo"].dividends.safety
        ricostruito = 50.0 + sum(f.points for f in sicurezza.factors)
        assert sicurezza.score == pytest.approx(max(0, min(100, ricostruito)), abs=0.01)

    def test_dividendo_tagliato_e_a_rischio(self, analisi):
        sicurezza = analisi["tagliato"].dividends.safety
        assert sicurezza.band == "at risk"
        assert sicurezza.cut_risk_band == "high"
        assert sicurezza.hard_triggers, "va detto perche' e' a rischio"

    def test_un_pagatore_irregolare_non_puo_essere_solido(self, analisi):
        """Chi salta anni non e' un titolo da reddito, per quanto sia prudente
        il payout negli anni in cui paga."""
        sicurezza = analisi["irregolare"].dividends.safety
        assert sicurezza.score <= 45
        assert sicurezza.band != "solid"
        assert any("irregular" in f.label.lower() for f in sicurezza.factors)

    def test_la_crescita_dopo_un_taglio_non_viene_premiata(self, analisi):
        """A cinque anni la risalita dal minimo sembra crescita: usare la
        misura piu' prudente evita di premiare chi ha tagliato."""
        fattore = next(f for f in analisi["tagliato"].dividends.safety.factors
                       if f.label.startswith("Average dividend growth"))
        assert fattore.points < 0


# --------------------------------------------------------------------------
# previsione
# --------------------------------------------------------------------------
class TestPrevisione:
    def test_forchetta_ordinata(self, analisi):
        for profilo in ("dividendo", "tagliato", "irregolare"):
            previsione = analisi[profilo].dividends.forecast
            assert previsione.ok
            assert previsione.year1_low <= previsione.year1_base <= previsione.year1_high
            assert previsione.year2_low <= previsione.year2_base <= previsione.year2_high

    def test_metodi_dichiarati(self, analisi):
        previsione = analisi["dividendo"].dividends.forecast
        assert len(previsione.methods) == 3
        for metodo in previsione.methods:
            assert metodo.detail or metodo.skipped_reason
        usati = [m for m in previsione.methods if m.usable and m.weight]
        assert sum(m.weight for m in usati) == pytest.approx(1.0)

    def test_previsione_vicina_al_dividendo_attuale(self, analisi):
        """Una previsione che raddoppia o dimezza in un anno non e' una
        previsione: e' rumore amplificato."""
        d = analisi["dividendo"].dividends
        attuale = d.yield_stats["dps_indicato"]
        assert 0.5 * attuale <= d.forecast.year1_base <= 1.5 * attuale

    def test_scenario_di_taglio_quando_il_rischio_e_alto(self, analisi):
        d = analisi["tagliato"].dividends
        attuale = d.yield_stats["dps_indicato"]
        assert d.forecast.year1_low <= attuale * 0.65, \
            "con rischio alto lo scenario pessimistico deve prevedere un taglio"
        assert "cut" in d.forecast.note.lower()


# --------------------------------------------------------------------------
# il segnale operativo
# --------------------------------------------------------------------------
class TestSegnale:
    @pytest.mark.parametrize("profilo,atteso", [
        ("dividendo", BUY),         # cedola solida, crescente, prezzo generoso
        ("tagliato", SELL),         # rendimento alto perche' il prezzo e' crollato
        ("irregolare", SELL),       # nessuna continuita': non e' un titolo da reddito
    ])
    def test_azione_attesa(self, analisi, profilo, atteso):
        assert analisi[profilo].dividends.signal.action == atteso

    def test_prezzi_ordinati(self, analisi):
        """Ingresso <= valore <= uscita: derivati dallo stesso quadro."""
        for profilo in ("dividendo", "tagliato", "irregolare", "solida", "cara"):
            segnale = analisi[profilo].dividends.signal
            assert segnale.entry_price <= segnale.fair_price <= segnale.exit_price
            assert segnale.entry_price == pytest.approx(
                segnale.fair_price / (1 + MARGINE_SICUREZZA), rel=1e-6)

    def test_rendimento_obiettivo_entro_i_limiti(self, analisi):
        for profilo in ("dividendo", "tagliato", "irregolare"):
            obiettivo = analisi[profilo].dividends.signal.target_yield
            assert RENDIMENTO_MIN <= obiettivo <= RENDIMENTO_MAX

    def test_un_dividendo_fragile_pretende_un_rendimento_piu_alto(self, analisi):
        """E' il correttivo che evita di scommettere sul ritorno alla mediana
        di un'azienda che non e' piu' quella di prima."""
        fragile = analisi["tagliato"].dividends
        solido = analisi["dividendo"].dividends
        # A parita' di mediana storica simile, l'obiettivo del fragile e' piu' alto.
        assert fragile.signal.target_yield > solido.signal.target_yield

    def test_il_ritorno_alla_mediana_e_smorzato(self, analisi):
        """Si assume che si chiuda metà dello scarto, non tutto."""
        d = analisi["solida"].dividends
        attuale, mediana = d.yield_stats["attuale"], d.yield_stats["mediana"]
        obiettivo = d.signal.target_yield
        assert min(attuale, mediana) <= obiettivo <= max(attuale, mediana), \
            "l'obiettivo sta fra il rendimento di oggi e la mediana storica"

    def test_il_rendimento_atteso_resta_in_scala(self, analisi):
        """Nessun ritorno alla media vale piu' del 50% di prezzo in due anni."""
        for profilo in ("dividendo", "tagliato", "irregolare", "solida", "cara"):
            segnale = analisi[profilo].dividends.signal
            assert -0.51 <= segnale.price_component <= 0.51

    def test_le_ragioni_sono_sempre_spiegate(self, analisi):
        for profilo in ("dividendo", "tagliato", "irregolare"):
            segnale = analisi[profilo].dividends.signal
            assert len(segnale.reasons) >= 3
            assert all(motivo.strip().endswith(".") for motivo in segnale.reasons)

    def test_un_rendimento_alto_su_un_dividendo_a_rischio_non_e_un_acquisto(self, analisi):
        """Il caso che questo strumento deve prendere: il 14% di rendimento e'
        il mercato che sconta un taglio, non un regalo."""
        d = analisi["tagliato"].dividends
        assert d.yield_stats["attuale"] > 0.10
        assert d.yield_stats["percentile"] > 0.70
        assert d.signal.action == SELL
        assert d.safety.cut_risk_band == "high"
        # La ragione deve essere detta, non solo il verdetto.
        motivi = " ".join(d.signal.reasons).lower()
        assert "cut risk is high" in motivi and "pessimistic-case dividend" in motivi


# --------------------------------------------------------------------------
# verifica retrospettiva
# --------------------------------------------------------------------------
class TestVerificaRetrospettiva:
    def test_gruppi_e_avvertenza(self, analisi):
        verifica = analisi["dividendo"].dividends.backtest
        assert verifica.observations > 24
        assert len(verifica.buckets) == 3
        assert ("not a rule that holds in general" in verifica.note
                or "a hint" in verifica.note), \
            "il limite del metodo va dichiarato accanto al risultato"

    def test_non_guarda_nel_futuro(self, analisi):
        """Ogni osservazione deve avere due anni di dati *successivi*: senza
        questo controllo il risultato sarebbe costruito sul futuro."""
        d = analisi["dividendo"].dividends
        verifica = d.backtest
        mesi_disponibili = (d.daily_yield.index[-1] - d.daily_yield.index[0]).days / 30.44
        assert verifica.observations <= mesi_disponibili - 20

    def test_poche_osservazioni_vengono_dichiarate(self, analisi):
        verifica = analisi["irregolare"].dividends.backtest
        if verifica.observations < 24:
            assert not verifica.usable
            assert "poche" in verifica.note or "bastano" in verifica.note


# --------------------------------------------------------------------------
# integrazione
# --------------------------------------------------------------------------
class TestIntegrazione:
    def test_i_dividendi_alimentano_anche_il_modello_generale(self):
        """La serie scelta dalle fonti deve alimentare rendimento e payout, non
        solo la scheda dividendi."""
        a = analyze("demo:dividendo")
        assert a.metrics.dividend["yield_current"] == pytest.approx(
            a.dividends.yield_stats["attuale"], rel=1e-6)

    def test_il_racconto_esiste_e_non_ha_buchi(self, analisi):
        import re

        for profilo in PROFILES:
            paragrafi = analisi[profilo].narrative["dividends"]
            assert paragrafi
            testo = " ".join(paragrafi)
            assert "{" not in testo
            for sospetto in (r"\bNone\b", r"\bnan\b", r"\binf\b"):
                assert not re.search(sospetto, testo), f"{profilo}: {sospetto}"

    def test_il_report_contiene_i_dividendi(self, analisi):
        report = analisi["dividendo"].report()
        assert "## Dividends: the signal" in report
        assert "## Ten years of dividends" in report
        assert "Dividend safety, factor by factor" in report

    def test_senza_prezzi_non_esplode(self):
        """Un titolo di cui abbiamo i dividendi ma non lo storico prezzi."""
        dati = build_demo("dividendo")
        pagamenti = dati.dividends
        metriche = compute_metrics(dati)
        raccolta = collect_dividends("X", only=[], fallback=pagamenti)
        d = analyze_dividends(metriche, None, raccolta)
        assert d.pays_dividends
        assert d.daily_yield is None
        assert d.signal is not None

    def test_ripetibile(self):
        primo = analyze("demo:tagliato").dividends.signal
        secondo = analyze("demo:tagliato").dividends.signal
        assert (primo.action, primo.expected_return_2y) == \
               (secondo.action, secondo.expected_return_2y)
