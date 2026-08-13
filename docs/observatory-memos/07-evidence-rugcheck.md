# `src/observatory/evidence/rugcheck.py`

## Aufgabe

Diese Datei ist der direkte read-only Adapter zu RugCheck. Sie holt für genau eine Mint den externen Provider-Report und hält diesen Evidence-Zugriff bewusst getrennt von der späteren LLM-Interpretation.

## Bird's-Eye-View

```text
exact Mint -> RugCheck API -> Raw Report -> Projection / Analyst
```

### `RugCheckError`

Typisiert Fehler des externen Evidence-Providers und trägt einen passenden HTTP-Status für die API-Schicht.

### `validate_mint(mint)`

Prüft die Mint, bevor überhaupt ein externer Request gebaut wird. Damit basiert der Provider-Aufruf auf derselben exakten Identität wie die Token-Auswahl im Observatory.

### `get_token_report(mint)`

Ruft den RugCheck-Report für genau diese Mint ab. Die Funktion speichert nichts in der operativen Datenbank und ruft selbst kein LLM auf.

Zusätzlich werden Fetch-Zeit, Rohgröße und eine grobe Token-Schätzung mitgegeben, damit später sichtbar bleibt, wie groß die externe Evidence war.

**Genutzt von:** `app.py`; das Ergebnis geht anschließend optional an `rugcheck_projection.py` und `rugcheck_analysis.py`.

## Präsentationssatz

> **`evidence/rugcheck.py` holt externe Safety-Evidence für genau die ausgewählte Mint, ohne sie mit Systemwahrheit oder LLM-Interpretation zu vermischen.**
