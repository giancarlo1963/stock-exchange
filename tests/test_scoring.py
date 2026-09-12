"""Il verdetto: la parte che l'utente legge per prima, quindi quella che
deve sbagliare meno. Qui verifichiamo soprattutto che i problemi gravi di
bilancio prevalgano sempre sul prezzo conveniente."""

import pytest

from setxray.demo import PROFILE_KEYS, build_demo
from setxray.engine import analyze_data
from setxray.metrics import compute_metrics
from setxray.scoring import BUY, HOLD, SELL, Flag, band, detect_flags, evaluate
from setxray.valuation import value_company


class TestSoglie:
    def test_interpolazione(self):
        punti = [(0.0, 0.0), (0.10, 50.0), (0.20, 100.0)]
        assert band(0.0, punti) == 0
        assert band(0.05, punti) == pytest.approx(25)
        assert band(0.10, punti) == 50
        assert band(0.20, punti) == 100

    def test_fuori_intervallo_resta_all_estremo(self):
        punti = [(0.0, 10.0), (1.0, 90.0)]
        assert band(-5, punti) == 10
        assert band(5, punti) == 90

    def test_valori_non_numerici(self):
        assert band(None, [(0, 0), (1, 100)]) is None
        assert band(float("nan"), [(0, 0), (1, 100)]) is None


class TestVerdettiSuiProfiliNoti:
    """I quattro profili dimostrativi coprono i casi che contano."""

    @pytest.mark.parametrize("profilo,atteso", [
        ("solida", BUY),        # cresce, conti sani, prezzo sotto la media storica
        ("cara", SELL),         # buona azienda, prezzo molto sopra il valore
        ("difficolta", SELL),   # perdite, debito, cassa negativa
        ("dividendo", BUY),     # stabile, dividendo alto, valutazione contenuta
    ])
    def test_azione_attesa(self, profilo, atteso):
        assert analyze_data(build_demo(profilo)).verdict.action == atteso

    @pytest.mark.parametrize("profilo", list(PROFILE_KEYS))
    def test_il_verdetto_e_sempre_completo(self, profilo):
        d = analyze_data(build_demo(profilo)).verdict
        assert d.action in (BUY, HOLD, SELL)
        assert d.conviction in ("high", "medium", "low")
        assert d.headline and d.reasons and d.position_note and d.review_triggers
        assert 0 <= d.composite <= 100
        assert len(d.pillars) == 5

    def test_ripetibile(self):
        """Stessi dati, stesso verdetto: nessuna casualita' nel giudizio."""
        primo = analyze_data(build_demo("solida")).verdict
        secondo = analyze_data(build_demo("solida")).verdict
        assert (primo.action, primo.composite, primo.raw_signal) == \
               (secondo.action, secondo.composite, secondo.raw_signal)


class TestPrecedenzaDeiProblemiGravi:
    """I problemi gravi di bilancio devono prevalere sul prezzo conveniente."""

    @staticmethod
    def _verdetto_con(profilo, problemi):
        """Rivaluta lo stesso titolo sostituendo i campanelli d'allarme.

        Serve a isolare l'effetto dei problemi dal resto del punteggio.
        """
        import setxray.scoring as scoring

        m = compute_metrics(build_demo(profilo))
        v = value_company(m)
        vero = scoring.detect_flags
        scoring.detect_flags = lambda *_: list(problemi)
        try:
            return scoring.evaluate(m, v)
        finally:
            scoring.detect_flags = vero

    @pytest.mark.parametrize("profilo", list(PROFILE_KEYS))
    def test_due_problemi_gravi_portano_sempre_a_vendere(self, profilo):
        dopo = self._verdetto_con(profilo, [Flag("grave", "Shareholders' equity is negative."),
                                            Flag("grave", "Interest costs are not covered.")])
        assert dopo.action == SELL
        assert dopo.conviction == "high"

    @pytest.mark.parametrize("profilo", list(PROFILE_KEYS))
    def test_un_solo_problema_grave_esclude_comunque_l_acquisto(self, profilo):
        """Ci si puo' arrivare per due strade - la penalita' sul segnale o il
        vincolo esplicito - e il test copre entrambe senza legarsi a quale
        delle due sia scattata."""
        problema = Flag("grave", "Free cash flow is negative.")
        pulito = self._verdetto_con(profilo, [])
        segnalato = self._verdetto_con(profilo, [problema])
        assert segnalato.action != BUY
        assert any("Free cash flow" in motivo for motivo in segnalato.reasons)
        assert segnalato.raw_signal < pulito.raw_signal

    def test_senza_problemi_il_profilo_solido_resta_un_acquisto(self):
        assert self._verdetto_con("solida", []).action == BUY

    def test_senza_bilanci_non_si_consiglia_di_comprare(self):
        dati = build_demo("solida")
        dati.income_a = None
        dati.balance_a = None
        dati.cash_a = None
        dati.income_q = dati.balance_q = dati.cash_q = None
        dati.income_ttm = dati.cash_ttm = None
        analisi = analyze_data(dati)
        assert analisi.metrics.n_years == 0
        assert analisi.verdict.action != BUY
        assert analisi.verdict.data_quality == "insufficient"


class TestCampanelliDAllarme:
    def test_azienda_in_difficolta_alza_piu_bandiere(self):
        m = compute_metrics(build_demo("difficolta"))
        problemi = detect_flags(m, value_company(m))
        gravi = [p for p in problemi if p.severity == "grave"]
        assert len(gravi) >= 3
        assert all(p.text.endswith(".") for p in problemi), "ogni avviso e' una frase compiuta"

    def test_azienda_sana_non_alza_bandiere_gravi(self):
        m = compute_metrics(build_demo("solida"))
        problemi = detect_flags(m, value_company(m))
        assert not [p for p in problemi if p.severity == "grave"]

    def test_copertura_interessi_negativa_ha_una_frase_sensata(self):
        m = compute_metrics(build_demo("difficolta"))
        assert m.health["interest_coverage"] < 0
        testi = " ".join(p.text for p in detect_flags(m, value_company(m)))
        assert "negative" in testi
        assert "-0" not in testi, "non si dice 'copre -0.5 volte'"
