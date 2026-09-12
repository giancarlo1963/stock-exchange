"""I modelli di valutazione, con attenzione ai casi in cui esplodono.

Il rischio vero di un modello a crescita perpetua non e' sbagliare di poco:
e' produrre un valore enorme quando la crescita si avvicina al tasso di sconto.
Questi test esistono per impedirlo.
"""

import pytest

from setxray.demo import build_demo
from setxray.engine import analyze_data
from setxray.metrics import compute_metrics
from setxray.valuation import (
    COST_OF_EQUITY_CAP,
    COST_OF_EQUITY_FLOOR,
    PERPETUAL_GROWTH_CAP,
    cost_of_equity,
    value_company,
)


class TestCostoDelCapitale:
    def test_capm(self):
        tasso, beta = cost_of_equity(1.0, risk_free=0.03, erp=0.075)
        assert beta == 1.0
        assert tasso == pytest.approx(0.105)

    def test_beta_assurdo_viene_riportato_dentro(self):
        # Su titoli poco liquidi il beta stimato e' rumore, non informazione.
        _, basso = cost_of_equity(-3.0)
        _, alto = cost_of_equity(9.0)
        assert basso == 0.4 and alto == 1.8

    def test_beta_mancante_vale_uno(self):
        assert cost_of_equity(None)[1] == 1.0

    @pytest.mark.parametrize("beta", [0.1, 0.5, 1.0, 1.5, 3.0])
    def test_tasso_sempre_entro_i_limiti(self, beta):
        tasso, _ = cost_of_equity(beta)
        assert COST_OF_EQUITY_FLOOR <= tasso <= COST_OF_EQUITY_CAP


class TestForchettaDiValore:
    @pytest.mark.parametrize("profilo", ["solida", "cara", "difficolta", "dividendo"])
    def test_scenari_ordinati(self, profilo):
        v = value_company(compute_metrics(build_demo(profilo)))
        assert v.fair_bear <= v.fair_base <= v.fair_bull

    @pytest.mark.parametrize("profilo", ["solida", "cara", "dividendo"])
    def test_valori_in_scala_ragionevole(self, profilo):
        """Nessun modello puo' valere 10 volte il prezzo: sarebbe un artefatto."""
        m = compute_metrics(build_demo(profilo))
        v = value_company(m)
        for metodo in v.usable_methods():
            assert 0 < metodo.fair_value < m.price * 6, f"{metodo.label} fuori scala"

    def test_pesi_dei_metodi_usati_sommano_a_uno(self):
        v = value_company(compute_metrics(build_demo("dividendo")))
        pesi = [metodo.weight for metodo in v.usable_methods() if metodo.weight]
        assert sum(pesi) == pytest.approx(1.0)

    def test_crescita_perpetua_sempre_limitata(self):
        """Il tetto alla crescita perpetua e' il freno principale dei modelli."""
        for profilo in ("solida", "cara", "dividendo"):
            v = value_company(compute_metrics(build_demo(profilo)))
            for metodo in v.methods:
                if metodo.key in ("ddm", "pb") and metodo.usable:
                    crescita = float(metodo.detail.split("crescita ")[1].split("%")[0]
                                     .replace(",", ".")) / 100 if "crescita " in metodo.detail else 0.0
                    assert crescita <= PERPETUAL_GROWTH_CAP + 1e-9


class TestAziendaInPerdita:
    def test_nessun_modello_sugli_utili_e_applicabile(self):
        v = value_company(compute_metrics(build_demo("difficolta")))
        saltati = {metodo.key for metodo in v.methods if not metodo.usable}
        assert {"multiple", "ddm", "dcf", "pb"} <= saltati
        assert all(metodo.skipped_reason for metodo in v.methods if not metodo.usable)

    def test_resta_solo_il_pavimento_patrimoniale_e_lo_dichiara(self):
        v = value_company(compute_metrics(build_demo("difficolta")))
        usabili = v.usable_methods()
        assert [metodo.key for metodo in usabili] == ["book_floor"]
        assert v.reliability == "bassa"
        assert any("patrimoniale" in nota for nota in v.notes)

    def test_lo_sconto_sul_patrimonio_non_diventa_un_acquisto(self):
        """Un'azienda che brucia patrimonio non e' un affare perche' costa poco."""
        analisi = analyze_data(build_demo("difficolta"))
        assert analisi.verdict.action == "VENDI"
        assert analisi.valuation.expected_return_2y > 0  # il prezzo e' sotto il patrimonio...
        assert len(analisi.verdict.grave_flags) >= 2     # ...ma i conti non tengono


class TestIpotesiModificabili:
    def test_un_tasso_piu_alto_abbassa_il_valore(self):
        m = compute_metrics(build_demo("dividendo"))
        prudente = value_company(m, risk_free=0.055, erp=0.09)
        generoso = value_company(m, risk_free=0.020, erp=0.05)
        assert prudente.fair_base < generoso.fair_base
        assert prudente.cost_of_equity > generoso.cost_of_equity
