"""SET X-Ray — analisi fondamentale di azioni della Borsa di Thailandia (SET).

Pensato per un investitore con orizzonte 1-2 anni: non fa trading, non da'
segnali intraday. Prende un simbolo (es. PTT), scarica tutti i dati pubblici
disponibili, li trasforma in metriche da analista, li valuta e conclude con
una singola indicazione operativa: COMPRA / MANTIENI / VENDI.
"""

__version__ = "1.0.0"
__all__ = ["analyze", "Analysis"]


def __getattr__(name):  # import pigro: evita di caricare pandas/plotly all'import del package
    if name in ("analyze", "Analysis"):
        from setxray.engine import Analysis, analyze

        return {"analyze": analyze, "Analysis": Analysis}[name]
    raise AttributeError(name)
