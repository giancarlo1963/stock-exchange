"""La formattazione italiana e' l'unica cosa che l'utente legge in ogni numero."""

from setxray import fmt


def test_separatori_italiani():
    assert fmt.num(1234.5) == "1.234,50"
    assert fmt.num(1234567.891, 1) == "1.234.567,9"
    assert fmt.num(-0.5) == "-0,50"


def test_percentuali():
    assert fmt.pct(0.0826) == "8,3%"
    # Python arrotonda i pareggi al pari (8,25 -> 8,2): lo mettiamo per iscritto
    # cosi' un eventuale cambio di regola resta una scelta, non una sorpresa.
    assert fmt.pct(0.0825) == "8,2%"
    assert fmt.pct(0.12, sign=True) == "+12,0%"
    assert fmt.pct(-0.12, sign=True) == "-12,0%"
    assert fmt.pct(0.0, sign=True) == "0,0%"  # lo zero non prende il segno


def test_importi_grandi():
    assert fmt.big(98.3e9) == "98,3 mld THB"
    assert fmt.big(1.5e12) == "1.500,0 mld THB"
    assert fmt.big(4.2e6) == "4,2 mln THB"
    assert fmt.big(-98.3e9) == "-98,3 mld THB"


def test_valori_mancanti_sempre_dichiarati():
    for funzione in (fmt.num, fmt.pct, fmt.mult, fmt.money, fmt.big, fmt.ratio, fmt.date):
        assert funzione(None) == "n/d"
    assert fmt.num(float("nan")) == "n/d" or fmt.num(float("nan")) == "nan"
