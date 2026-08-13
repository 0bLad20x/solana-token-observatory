# Observatory Python Memos

Diese Memos erklären den operativen Python-Kern von `src/observatory/`. Browser-Design, CSS und JavaScript-View-Details aus `static/` bleiben bewusst außen vor.

## Gesamtbild

```text
Benutzerfrage + Scope
        |
        v
      app.py
        |
        +--> Current Data --> data.py --> tools.py --> analyst.py
        +--> Web ----------> exact Mint -------> analyst.py
        +--> Temporal -----> Summary ----------> analyst.py
        +--> RugCheck -----> Evidence -> Projection -> rugcheck_analysis.py
                                                   |
                                                   v
                                                mistral.py
                                                   |
                                                   v
                                                Mistral API
```

## Kernidee

Der Analyst ist kein allgemeiner Chatbot mit freiem Datenzugriff. `app.py` entscheidet zuerst, welcher Evidence-Pfad für die Frage benutzt wird. Erst danach wird das passende Modell gewählt und ein Scope-spezifischer Prompt gebaut.

Bei `web`, `temporal` und `rugcheck` bleibt die ausgewählte Mint die technische Primäridentität. Name und Symbol dienen nur als lesbare Hinweise.

## Empfohlene Reihenfolge

1. [`app.py`](app.md)
2. [`analyst.py`](analyst.md)
3. [`tools.py`](tools.md)
4. [`data.py`](data.md)
5. [`model_policy.py`](model_policy.md)
6. [`mistral.py`](mistral.md)
7. [`evidence/rugcheck.py`](evidence_rugcheck.md)
8. [`rugcheck_projection.py`](rugcheck_projection.md)
9. [`rugcheck_analysis.py`](rugcheck_analysis.md)
10. [`telemetry.py`](telemetry.md)
11. [`delta.py`](delta.md)
12. [`__init__.py`](package_init.md)
13. [`evidence/__init__.py`](evidence_init.md)

## Präsentationssatz

> **Das Observatory trennt UI, Evidence und LLM-Interpretation: Der Scope bestimmt zuerst die erlaubte Datenquelle, bei Token-spezifischen Analysen bleibt die exakte Mint erhalten, und erst danach darf das passende Modell interpretieren.**
