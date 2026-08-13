# `src/temporal_context.py`

## Aufgabe

`temporal_context.py` verdichtet die retained Snapshot-Historie eines einzelnen Tokens in ein kompaktes, deterministisch berechnetes Zeit-Summary. Das LLM muss dadurch nicht tausende Raw-Snapshots selbst zählen oder aggregieren, sondern bekommt bereits berechnete Fakten über Entwicklung, Aktivität und Verhältnisse.

[Quellcode](../../src/temporal_context.py)

## Bird's-Eye-View

```text
mint_snapshots ≤ 24h
        ↓
temporal_context.py
        ↓
deterministic summary
        ↓
src/observatory/ Analyst
        ↓
LLM interpretation
```

## `iso(value)`

Normalisiert einen Python-Zeitstempel auf UTC-ISO-Text. Damit haben die späteren Summary-Felder ein einheitliches Zeitformat.

**Genutzt von:** den Normalisierungsfunktionen.

## `numeric(value)`

Versucht einen Wert sicher in eine Zahl umzuwandeln. Fehlende oder nicht interpretierbare Werte bleiben `None` und werden nicht als null interpretiert.

**Genutzt von:** fast allen numerischen Hilfsfunktionen.

## `rounded(value, digits=6)`

Rundet berechnete Float-Werte für kompakte und stabile Summary-Ausgabe. Integer und fehlende Werte bleiben sinnvoll erhalten.

**Genutzt von:** den Summary-Berechnungen.

## `snake_case(value)`

Normalisiert dynamische Feldnamen aus `stats1h` in ein einheitliches Python-/JSON-Format. Dadurch können unterschiedlich geschriebene Source-Keys konsistent weiterverarbeitet werden.

**Genutzt von:** `numeric_object()`.

## `numeric_object(value)`

Läuft rekursiv durch verschachtelte Objekte und behält nur numerisch interpretierbare Werte. So wird der große `stats1h`-Payload auf die für zeitliche Analyse brauchbaren Zahlen reduziert.

**Genutzt von:** `_normalize_samples()`.

## `get_path(value, *path)`

Kleine Hilfsfunktion zum sicheren Lesen verschachtelter Dictionary-Pfade. Fehlt unterwegs ein Teil, wird `None` zurückgegeben.

**Genutzt von:** mehreren Metrik- und Ratio-Funktionen.

## `load_temporal_summary_rows(connection, mint)`

Lädt maximal die letzten 24 Stunden eines Mints aus `mint_snapshots`. Kernmetriken werden für alle Beobachtungen geladen; das größere rollierende `stats1h` wird nur in festen 5-Minuten-Samples gelesen, um die Datenmenge zu begrenzen.

**Genutzt von:** `src/observatory/data.py` / `FrontendReader.temporal_summary()`.

## `_normalize_history(rows)`

Wandelt die vollständigen History-Zeilen in ein einheitliches internes Format um. Nur bekannte Kernmetriken und gültige Zeitpunkte werden übernommen.

**Genutzt von:** `build_temporal_summary()`.

## `_normalize_samples(rows)`

Normalisiert die dünner gesampelten Zeilen inklusive `stats1h`. Dadurch kann die spätere Aktivitätsanalyse auf einer kleineren, kontrollierten Datenmenge arbeiten.

**Genutzt von:** `build_temporal_summary()`.

## `_percentile(values, q)`

Berechnet einen einfachen interpolierten Percentile-Wert. Im aktuellen Summary wird damit insbesondere der Median als robuste Vergleichsbasis bestimmt.

**Genutzt von:** Aktivitäts- und Organic-Summaries.

## `_metric_points(rows, *path)`

Extrahiert aus einer Reihe nur die gültigen Zeit/Wert-Paare einer gewünschten Metrik. Das ist die gemeinsame Grundlage für Start-, Current-, Min-, Max- und Change-Berechnungen.

**Genutzt von:** mehreren Summary-Helfern.

## `_change_pct(start, current)`

Berechnet die prozentuale Veränderung zwischen Start und aktuellem Wert. Bei einem Startwert von null wird bewusst kein künstlicher Prozentwert erzeugt.

**Genutzt von:** `_metric_summary()`.

## `_metric_summary(rows, *path, peak_and_drawdown=False)`

Erzeugt für eine Metrik Start, Current, Minimum, Maximum und prozentuale Veränderung. Optional werden zusätzlich Peak-Zeitpunkt und maximaler Drawdown innerhalb des beobachteten Fensters berechnet.

**Genutzt von:** `build_temporal_summary()` für Market Cap, Liquidity und Holders.

## `_sampled_values(rows, *path)`

Extrahiert nur numerische Werte aus den gesampelten Beobachtungen. Die Funktion vereinfacht wiederkehrende Median- und Ratio-Berechnungen.

**Genutzt von:** mehreren Summary-Helfern.

## `_summarize_values(values)`

Verdichtet eine Zahlenreihe auf Current, Median, Minimum und Maximum. Das wird vor allem für Aktivitäts- und Verhältniswerte genutzt.

**Genutzt von:** Ratio- und Organic-Auswertung.

## `_ratio_values(rows, left, right, mode)`

Berechnet aus zwei Metriken entweder ein Verhältnis oder einen normalisierten Netto-Wert. Beispiele sind Buy/Sell-Volume-Ratio, Net-Flow-Ratio und Liquidity/Market-Cap-Verhältnis.

**Genutzt von:** `build_temporal_summary()` und `_activity_summary()`.

## `_ownership_summary(history)`

Verdichtet Ownership-Evidence wie `top_holders_pct`, `dev_balance_pct` und aktuelle `dev_mints`. Veränderungen werden als Prozentpunkt-Differenz beschrieben, ohne daraus automatisch Akteursverhalten abzuleiten.

**Genutzt von:** `build_temporal_summary()`.

## `_activity_summary(samples)`

Vergleicht die aktuellsten rollierenden `stats1h`-Werte mit ihrem Median im beobachteten Fenster. Zusätzlich werden aus Buy/Sell-Feldern einige deterministische Verhältnisse berechnet.

**Genutzt von:** `build_temporal_summary()`.

## `_organic_summary(history, samples)`

Fasst den Organic Score und — sofern genügend Daten vorhanden sind — den Anteil organischen Volumens zusammen. Auch hier werden nur mathematisch ableitbare Werte erzeugt.

**Genutzt von:** `build_temporal_summary()`.

## `build_temporal_summary(history_rows, sample_rows=None)`

Ist die zentrale Aggregationsfunktion. Sie setzt aus History, Market Cap, Liquidity, Holders, Ownership, Activity und Organic-Evidence ein kompaktes Summary für genau den tatsächlich beobachteten Zeitraum zusammen.

**Genutzt von:** `src/observatory/data.py` / `FrontendReader.temporal_summary()`.

## `build_temporal_summary_bundle(mint, history_rows, sample_rows=None, token=None)`

Packt Token-Identität und das berechnete Summary in ein gemeinsames Bundle. Das ist eine praktische Transportform für Verbraucher, die Identität und zeitliche Evidence zusammen benötigen.

**Bereitgestellt für:** Summary-Verbraucher und Tests; der aktuelle Observatory-Pfad verwendet direkt `build_temporal_summary()`.

## Präsentationssatz

> **`temporal_context.py` macht aus bis zu 24 Stunden Raw-Snapshots ein kleines deterministisches Zeitmodell: Python berechnet Fakten wie Veränderungen, Mediane und Ratios, während das LLM anschließend nur noch deren Beziehungen interpretiert.**
