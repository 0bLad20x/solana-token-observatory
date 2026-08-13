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
        +--> Web ----------> ausgewählte Mint --> analyst.py
        +--> Temporal -----> Summary -----------> analyst.py
        +--> RugCheck -----> Evidence -> Projection -> Analysis
                                                   |
                                                   v
                                                mistral.py
```

## Kernidee

Der Analyst ist kein allgemeiner Chatbot mit freiem Datenzugriff. `app.py` entscheidet zuerst, welcher Evidence-Pfad für eine Frage benutzt wird. Erst danach wird das passende Modell gewählt und ein Scope-spezifischer Prompt gebaut.

Bei Web, Temporal und RugCheck bleibt die ausgewählte Mint die technische Primäridentität. Name und Symbol sind nur lesbare Hinweise.

## Empfohlene Reihenfolge

1. [`app.py`](01-app-routing.md)
2. [`analyst.py`](02-analyst.md)
3. [`tools.py`](03-tools.md)
4. [`data.py`](04-data.md)
5. [`model_policy.py`](05-model-policy.md)
6. [`mistral.py`](06-mistral.md)
7. [`evidence/rugcheck.py`](07-evidence-rugcheck.md)
8. [`rugcheck_projection.py`](08-rugcheck-projection.md)
9. [`rugcheck_analysis.py`](09-rugcheck-analysis.md)
10. [`telemetry.py`](10-telemetry.md)
11. [`delta.py`](11-delta.md)

Die beiden `__init__.py`-Dateien sind reine Package-Marker ohne eigene operative Logik und brauchen deshalb kein separates Präsentationsmemo.

## Präsentationssatz

> **Das Observatory trennt UI, Evidence und LLM-Interpretation: Der Scope bestimmt zuerst die Datenquelle, bei Token-spezifischen Analysen bleibt die Mint erhalten, und erst danach interpretiert das passende Modell die vorbereitete Evidence.**
