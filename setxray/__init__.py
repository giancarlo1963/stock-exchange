"""SET X-Ray - dividendi e analisi fondamentale di azioni della Borsa di Thailandia.

Pensato per un investitore con orizzonte 1-2 anni: non fa trading, non da'
segnali intraday. Prende un simbolo (es. PTT), raccoglie da piu' archivi tutti
i dati pubblici disponibili e conclude con una singola indicazione operativa:
BUY / HOLD / SELL.

L'interfaccia parla inglese o italiano, con un interruttore: la scelta cambia
ogni parola e ogni cifra (1,234.50 contro 1.234,50). I nomi interni e i
commenti restano in italiano, la lingua in cui lo strumento e' stato scritto.

Il centro dello strumento e' la **storia dei dividendi degli ultimi dieci
anni**: quanto ha pagato, con quanta continuita', quanto del rendimento totale
e' arrivato dalle cedole, se il dividendo regge, e cosa paghera' nei prossimi
due anni. Intorno a questo c'e' l'analisi fondamentale generale, che serve a
capire se la cedola e' sostenuta dai conti.
"""

__version__ = "1.7.0"
__all__ = ["analyze", "Analysis"]


def __getattr__(name):  # import pigro: evita di caricare pandas/plotly all'import del package
    if name in ("analyze", "Analysis"):
        from setxray.engine import Analysis, analyze

        return {"analyze": analyze, "Analysis": Analysis}[name]
    raise AttributeError(name)
