# `src/observatory/rugcheck_projection.py`

## Aufgabe

`rugcheck_projection.py` verdichtet den großen Raw-Report von RugCheck in eine kleine, deterministische Safety-Projektion für das LLM. Das Modell bekommt dadurch relevante Aggregate und klare Semantik statt vieler Wallet-, Market- und Account-Zeilen.

## Bird's-Eye-View

```text
Raw RugCheck Report
        |
        v
Deterministische Projektion
        |
        +-> Provider Risks
        +-> Token Controls
        +-> Ownership Aggregate
        `-> Liquidity / LP Aggregate
        |
        v
bounded LLM Context
```

### `SEMANTICS`

Definiert explizit, wie RugCheck-Felder interpretiert werden dürfen. Besonders wichtig: unbekannte Score-Formeln werden nicht nachträglich in eigene Risk-Kategorien übersetzt.

### `_risk_summary()`

Übernimmt nur die relevanten Provider-Risk-Felder wie Name, Level, Wert, Score und Beschreibung.

### `_token_metadata()`

Verdichtet Token-Control-Fakten wie Mint-/Freeze-Authority, Metadata-Mutability, Plattform und Transfer-Fee-Evidence.

### `_holder_metadata()`

Berechnet aus den Top-Holder-Zeilen Aggregate wie Top-N-Konzentration, bekannte Infrastruktur-Anteile, Insider-Evidence und Creator-Anteile. Einzelne Wallet-Adressen müssen dafür nicht an das LLM geschickt werden.

### `_market_metadata()`

Verdichtet Markets und LP-Informationen zu Market Counts, Liquiditätskonzentration und vorhandener Lock-Evidence.

### `_compact_summary()`

Führt Provider Risk, Token Control, Ownership und Liquidity in einer kompakten Struktur zusammen.

### `project_rugcheck_evidence()`

Ist der öffentliche Einstieg. Die Funktion erzeugt die bounded Projektion und dokumentiert gleichzeitig, wie stark Raw Report und LLM-Kontext reduziert wurden; Wallet-Adressen werden dabei nicht an das Modell weitergegeben.

**Genutzt von:** `rugcheck_analysis.py`.

## Präsentationssatz

> **`rugcheck_projection.py` trennt Datenmenge von Bedeutung: Der vollständige Provider-Report bleibt als Evidence erhalten, das LLM erhält aber nur deterministisch berechnete Safety-Metadaten mit klar definierten Interpretationsregeln.**
