"""Le due lingue: quello che cambia, e soprattutto quello che non deve cambiare.

La trappola di uno strumento bilingue non e' la traduzione mancante - quella
si vede - ma il codice che confronta una stringa tradotta. Un `if banda ==
"alta"` funziona nella lingua in cui e' stato scritto e tace nell'altra: non
solleva errori, cambia solo il risultato. E' successo davvero, e le prove qui
sotto esistono per quello.
"""

import re

import pytest

from setxray import charts, fmt
from setxray.demo import PROFILE_KEYS, build_demo, profile_names, profiles
from setxray.engine import analyze_data
from setxray.lang import CODES, L, action_label, language, normalize, plural, set_language, using
from setxray.scoring import BUY, HOLD, SELL


class TestScelta:
    def test_predefinita_inglese(self):
        assert language() == "en"
        assert L("yes", "si") == "yes"

    def test_normalizza_quello_che_scrive_una_persona(self):
        for scritto in ("it", "IT", "it-IT", "it_it", "italiano", "  Italiano "):
            assert normalize(scritto) == "it", scritto
        for scritto in ("en", "EN", "en-GB", "english", "", None, "klingon"):
            assert normalize(scritto) == "en", scritto

    def test_using_rimette_quella_di_prima(self):
        set_language("en")
        with using("it"):
            assert language() == "it"
        assert language() == "en"

    def test_using_annidata(self):
        with using("it"):
            with using("en"):
                assert L("a", "b") == "a"
            assert L("a", "b") == "b"

    def test_variabile_d_ambiente(self, monkeypatch):
        import setxray.lang as lang

        monkeypatch.setattr(lang, "_active", lang.contextvars.ContextVar("prova", default=None))
        monkeypatch.setenv("SETXRAY_LANG", "it")
        assert lang.language() == "it"

    def test_plurale(self):
        assert plural(1, "cut", "cuts") == "cut"
        assert plural(0, "cut", "cuts") == "cuts"
        assert plural(3, "cut", "cuts") == "cuts"
        assert plural(None, "cut", "cuts") == "cuts"


class TestNumeri:
    """La lingua non cambia solo le parole: cambia ogni cifra."""

    def test_separatori(self):
        with using("en"):
            assert fmt.num(1234.5) == "1,234.50"
            assert fmt.pct(0.0826) == "8.3%"
            assert fmt.big(98.3e9) == "98.3bn THB"
            assert fmt.na() == "n/a"
        with using("it"):
            assert fmt.num(1234.5) == "1.234,50"
            assert fmt.pct(0.0826) == "8,3%"
            assert fmt.big(98.3e9) == "98,3 mld THB"
            assert fmt.na() == "n/d"

    def test_date(self):
        import pandas as pd

        giorno = pd.Timestamp("2026-09-11")
        with using("en"):
            assert fmt.date(giorno) == "11 Sep 2026"
        with using("it"):
            assert fmt.date(giorno) == "11/09/2026"

    def test_nessun_numero_inglese_nel_testo_italiano(self):
        """Un "3.2%" accanto a "62,59 THB" nella stessa frase si nota."""
        with using("it"):
            analisi = analyze_data(build_demo("dividendo"))
            testo = " ".join(sum(analisi.narrative.values(), []))
        # un punto fra due cifre, in italiano, e' un separatore di migliaia:
        # quindi va seguito da tre cifre, non da una o due.
        sbagliati = re.findall(r"\d\.\d{1,2}(?!\d)", testo)
        assert not sbagliati, f"numeri all'inglese nel testo italiano: {sbagliati[:5]}"


class TestIdentificatoriStabili:
    """Quello che il codice confronta non deve cambiare con la lingua."""

    @pytest.mark.parametrize("profilo", list(PROFILE_KEYS))
    def test_azione_e_sempre_un_identificatore(self, profilo):
        for lingua in CODES:
            with using(lingua):
                analisi = analyze_data(build_demo(profilo))
                assert analisi.verdict.action in (BUY, HOLD, SELL)
                segnale = analisi.dividends.signal if analisi.dividends else None
                if segnale is not None:
                    assert segnale.action in (BUY, HOLD, SELL)

    def test_etichetta_dell_azione_invece_e_tradotta(self):
        with using("en"):
            assert action_label(BUY) == "BUY"
        with using("it"):
            assert action_label(BUY) == "COMPRA"
            assert action_label(SELL) == "VENDI"
            assert action_label(HOLD) == "MANTIENI"

    def test_chiavi_del_racconto_stabili(self):
        for lingua in CODES:
            with using(lingua):
                analisi = analyze_data(build_demo("dividendo"))
                assert set(analisi.narrative) == {"past", "present", "future", "dividends"}

    def test_chiavi_delle_fonti_stabili(self):
        from setxray.sources import describe_sources

        for lingua in CODES:
            with using(lingua):
                for riga in describe_sources():
                    assert {"key", "source", "trust", "api_key", "active", "note"} <= set(riga)

    def test_chiavi_dei_grafici_stabili(self):
        nomi = {}
        for lingua in CODES:
            with using(lingua):
                analisi = analyze_data(build_demo("dividendo"))
                nomi[lingua] = set(charts.all_charts(analisi)) | set(charts.dividend_charts(analisi))
        assert nomi["en"] == nomi["it"]

    def test_affidabilita_ha_una_chiave_oltre_alla_parola(self):
        """Il caso vero: il confronto era sulla parola, e in inglese taceva."""
        for lingua in CODES:
            with using(lingua):
                analisi = analyze_data(build_demo("difficolta"))
                assert analisi.valuation.reliability_key == "low"


class TestStessaAnalisiInDueLingue:
    """I numeri e la struttura non dipendono dalla lingua. Solo le parole."""

    @pytest.mark.parametrize("profilo", list(PROFILE_KEYS))
    def test_i_numeri_coincidono(self, profilo):
        risultati = {}
        for lingua in CODES:
            with using(lingua):
                a = analyze_data(build_demo(profilo))
                risultati[lingua] = (
                    round(a.verdict.composite, 6),
                    round(a.valuation.fair_base or 0, 6),
                    round(a.verdict.expected_return_2y or 0, 6),
                    a.verdict.action,
                    len(a.verdict.flags),
                    len(a.verdict.pillars),
                    round(a.dividends.safety.score, 6) if a.dividends and a.dividends.safety else None,
                    round(a.dividends.signal.entry_price, 6)
                    if a.dividends and a.dividends.signal else None,
                )
        assert risultati["en"] == risultati["it"]

    @pytest.mark.parametrize("profilo", list(PROFILE_KEYS))
    def test_stesso_numero_di_frasi(self, profilo):
        conta = {}
        for lingua in CODES:
            with using(lingua):
                a = analyze_data(build_demo(profilo))
                conta[lingua] = [len(a.narrative[s]) for s in
                                 ("past", "present", "future", "dividends")]
        assert conta["en"] == conta["it"]

    @pytest.mark.parametrize("profilo", list(PROFILE_KEYS))
    def test_il_racconto_e_diverso_in_ogni_sezione(self, profilo):
        """Se una sezione uscisse identica, non sarebbe tradotta."""
        testi = {}
        for lingua in CODES:
            with using(lingua):
                a = analyze_data(build_demo(profilo))
                testi[lingua] = {s: " ".join(a.narrative[s]) for s in
                                 ("past", "present", "future", "dividends")}
        for sezione in testi["en"]:
            if len(testi["en"][sezione]) > 80:
                assert testi["en"][sezione] != testi["it"][sezione], sezione

    @pytest.mark.parametrize("profilo", list(PROFILE_KEYS))
    def test_nessun_segnaposto_in_nessuna_lingua(self, profilo):
        for lingua in CODES:
            with using(lingua):
                a = analyze_data(build_demo(profilo))
                testo = a.report() + " ".join(sum(a.narrative.values(), []))
                assert "{" not in testo and "}" not in testo
                for sospetto in (r"\bNone\b", r"\bnan\b", r"\bNaN\b", r"\binf\b"):
                    assert not re.search(sospetto, testo), f"{lingua}/{profilo}: {sospetto}"

    def test_le_sezioni_del_report_ci_sono_in_entrambe(self):
        attese = {
            "en": ("## Why", "## Past", "## Present", "## Future",
                   "## Ten years of dividends", "## Valuation methods used"),
            "it": ("## Perche'", "## Passato", "## Presente", "## Futuro",
                   "## Dieci anni di dividendi", "## Metodi di valutazione usati"),
        }
        for lingua, sezioni in attese.items():
            with using(lingua):
                report = analyze_data(build_demo("dividendo")).report()
                for sezione in sezioni:
                    assert sezione in report, f"{lingua}: manca {sezione}"


class TestProfiliDimostrativi:
    def test_nomi_e_descrizioni_tradotti(self):
        for lingua in CODES:
            with using(lingua):
                assert set(profiles()) == set(PROFILE_KEYS)
                assert set(profile_names()) == set(PROFILE_KEYS)
        with using("en"):
            inglese = profiles()["tagliato"]
        with using("it"):
            assert profiles()["tagliato"] != inglese
