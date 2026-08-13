# `src/observatory/rugcheck_analysis.py`

## Aufgabe

Diese Datei interpretiert die vorbereitete RugCheck-Evidence mit dem Strong Model. Der Raw Report wird nicht direkt an das Modell gegeben.

### `_instructions(token)`

Baut den System-Prompt für genau einen ausgewählten Token. Die Mint bleibt die technische Identität; Name, Symbol und Launchpad ergänzen nur den lesbaren Kontext.

Der Prompt erklärt außerdem, wie fehlende oder provider-spezifische Werte behandelt werden sollen und verbietet eigene, nicht belegte Score-Definitionen.

### `analyze_rugcheck_report()`

Lässt die Evidence zuerst durch `project_rugcheck_evidence()` verdichten. Danach werden Benutzerfrage und kompakter Summary in einem Strong-Model-Request verarbeitet.

Die Antwort liefert zusätzlich Metadaten über die verwendete Evidence zurück.

**Nutzt:** `rugcheck_projection.py` und `mistral.py`.

**Aufgerufen von:** `app.py` beim Scope `rugcheck`.

## Präsentationssatz

> **`rugcheck_analysis.py` analysiert nicht blind den Raw Report: Python verdichtet die externe Evidence zuerst, danach interpretiert das Strong Model einen klar begrenzten Kontext für genau die ausgewählte Mint.**
