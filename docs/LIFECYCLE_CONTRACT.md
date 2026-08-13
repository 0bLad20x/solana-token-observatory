# Lifecycle Contract

**Contract-Version:** `0.3`  
**Status:** frozen baseline  
**Scope:** operativer Hard-Retire-Pfad für `tracking_enabled=false`

## Zweck

Dieses Dokument ist die fachliche Authority für die derzeit implementierte Lifecycle-Semantik.

Refactorings dürfen SQL, Python-Struktur, Datenzugriff und interne Orchestrierung vereinfachen, solange für denselben Datenbankzustand exakt dieselben `(mint, reason)`-Kandidaten entstehen. Eine Änderung der hier beschriebenen Semantik ist keine Simplification, sondern eine neue Contract-Version.

Die operative Reihenfolge ist:

```text
Rule 1 -> Rule 2 -> Rule 3 -> Rule 4 -> Rule 5 -> Rule 6 -> Rule 7
```

Innerhalb eines Cycles gewinnt für einen Mint die erste passende Regel. Dry-Run und Apply verwenden dieselbe Candidate-Semantik; `--apply` bestimmt ausschließlich, ob die Kandidaten über `MintRepository.disable_mints()` tatsächlich deaktiviert werden.

## Gemeinsame Zeitbegriffe

- `created_at`: Jupiter-Erstellungszeit des Tokens.
- `first_observed_at`: lokale Zeit der ersten persistierten Jupiter-Source-Version.
- `last_polled_at`: lokale Zeit des letzten erfolgreichen Jupiter-Search-Polls.
- `last_changed_at`: lokale Beobachtungszeit der jüngsten neuen Jupiter-Source-Version.
- `observed_at`: lokale Beobachtungszeit eines persistierten Snapshots.
- `source_updated_at`: zuletzt persistierte Jupiter-`updatedAt`-Version.
- `mint_snapshots`: immutable Historie beobachteter Jupiter-Source-Versionen innerhalb des Raw-Buffers.

Fehlende Werte bleiben fehlend. Ein fehlender numerischer Wert wird nicht als `0` interpretiert.

## Rule 1 — Failed to Ignite

**T0:** `first_observed_at`  
**Eligibility:** ab `T0 + 10 Minuten`, ohne Ablaufdatum  
**Evidence:** letzter persistierter Snapshot des Mints  
**Freshness:** `last_polled_at` muss vorhanden und höchstens `60 Sekunden` alt sein

Disable, wenn mindestens eine Bedingung erfüllt ist:

1. `liquidity < 1_000`
2. `mcap < 3_000` **und** `holderCount < 300`

Missing semantics:

- fehlende `liquidity` erfüllt Bedingung 1 nicht;
- fehlende `mcap` oder `holderCount` erfüllt Bedingung 2 nicht.

Disable-Reasons:

- beide Bedingungen: `liquidity_below_1000_and_mcap_below_3000_and_holders_below_300`
- nur Bedingung 1: `liquidity_below_1000`
- nur Bedingung 2: `mcap_below_3000_and_holders_below_300`

## Rule 2 — Early Continuation Failure

**T0:** `created_at`  
**Evaluation window:** `T0 + 30 Minuten` bis exklusiv `T0 + 31 Minuten`  
**Observation prerequisite:** `first_observed_at <= T0 + 10 Minuten`  
**Checkpoint prerequisite:** `last_polled_at >= T0 + 30 Minuten`

Decision payload: letzter Snapshot mit `observed_at <= T0 + 30 Minuten`.

`changes_in_window` ist die Anzahl der Snapshots mit `T0 + 10 Minuten < observed_at <= T0 + 30 Minuten`.

Kein Disable, wenn:

- `mcap` oder `liquidity` im Decision Payload fehlt; oder
- gleichzeitig `mcap >= 50_000` und `liquidity >= 5_000`.

Disable, wenn danach:

```text
changes_in_window <= 10
```

Disable-Reason: `early_continuation_failure`.

## Rule 3 — Persistent Economic Absence

**T0:** `created_at`  
**Evaluation window:** `T0 + 5 Minuten` bis exklusiv `T0 + 6 Minuten`  
**Observation prerequisite:** `first_observed_at <= T0 + 5 Minuten`  
**Checkpoint prerequisite:** `last_polled_at >= T0 + 5 Minuten`

`has_economic_data=true`, wenn bis zum Decision-Zeitpunkt in mindestens einem Snapshot mindestens `mcap` oder `liquidity` nicht leer vorhanden war.

Disable, wenn:

```text
has_economic_data == false
```

Disable-Reason: `economic_data_missing_at_5m`.

## Rule 4 — Liquidity Collapse

**T0:** `created_at`  
**Eligibility:** ab `T0 + 30 Minuten`, ohne Ablaufdatum  
**Evidence:** immutable `mint_snapshots` ab dem T+30-Grenzpunkt  
**Current-poll freshness:** keine

Disable, sobald ein noch nicht sauber abgescannter Snapshot erfüllt:

```text
liquidity < 2_000
```

Disable-Reason: `liquidity_collapse_below_2000`.

Für Mints ohne Crossing wird der monotone `lifecycle_rule_state.scanned_through`-Cursor im Apply-Betrieb bis zum jüngsten geprüften Snapshot fortgeschrieben.

## Rule 5 — Market-Cap Collapse

**T0:** `created_at`  
**Eligibility:** ab `T0 + 30 Minuten`, ohne Ablaufdatum  
**Evidence:** immutable `mint_snapshots` ab dem T+30-Grenzpunkt  
**Current-poll freshness:** keine

Disable, sobald ein noch nicht sauber abgescannter Snapshot erfüllt:

```text
mcap < 2_000
```

Disable-Reason: `mcap_collapse_below_2000`.

Der Scan-Cursor folgt derselben Semantik wie Rule 4.

## Rule 6 — Early Holder Failure

**T0:** `first_observed_at`  
**Checkpoint:** `T0 + 30 Minuten`  
**Eligibility:** ab dem Checkpoint  
**Checkpoint prerequisite:** `last_polled_at >= T0 + 30 Minuten`  
**Decision payload:** letzter persistierter Snapshot mit `observed_at <= T0 + 30 Minuten`  
**Current-poll freshness:** keine

Disable, wenn im Decision Payload gilt:

```text
holderCount < 5
```

Missing semantics:

- fehlender oder leerer `holderCount` erfüllt Rule 6 nicht;
- `mcap` und `liquidity` sind irrelevant und weder Rescue- noch Zusatzbedingung.

Disable-Reason: `holder_count_below_5_at_30m`.

Rule 6 beschreibt ausschließlich fehlende frühe Holder-Distribution. Sie ist catch-up-fähig, solange ihr T+30-Decision-Payload noch im 24h-Raw-Buffer vorhanden ist. Fehlende Evidence wird nicht rekonstruiert.

## Rule 7 — Persistent Source Inactivity

**T0:** nicht altersabhängig; Voraussetzung ist ein bereits beobachteter Mint  
**Eligibility:** `first_observed_at` vorhanden  
**Evidence:** langlebige Collector-Fakten aus `mints`  
**Freshness:** `last_polled_at` höchstens `60 Sekunden` alt  
**Inactivity:** `last_changed_at` mindestens `24 Stunden` alt

Disable, wenn gleichzeitig gilt:

```text
first_observed_at IS NOT NULL
AND last_polled_at ist höchstens 60 Sekunden alt
AND last_changed_at <= now - 24 Stunden
```

Disable-Reason: `source_unchanged_for_24h`.

Semantik:

- `last_polled_at` beweist, dass Jupiter Search den Mint weiterhin erfolgreich zurückliefert;
- `last_changed_at` wird nur bei einer neueren Jupiter-`updatedAt`-Version fortgeschrieben;
- fehlendes `first_observed_at`, `last_polled_at` oder `last_changed_at` erfüllt Rule 7 nicht;
- `mcap`, `liquidity`, `holderCount` und ein vorhandener Snapshot sind weder Voraussetzung noch Rescue-Bedingung;
- die 24h-Retention erzeugt Rule 7 nicht;
- Rule 7 beendet ausschließlich die permanente aktive Jupiter-Search-Überwachung und behauptet nicht, dass der Mint auf Solana nicht mehr existiert.

## Operational Contract

Der Lifecycle läuft standardmäßig alle `15 Sekunden`.

```text
python src/lifecycle_clean.py
python src/lifecycle_clean.py --once
python src/lifecycle_clean.py --apply
python src/lifecycle_clean.py --apply --once
```

Es existieren keine CLI-Tuning-Parameter für Thresholds, Checkpoint-Fenster, Freshness oder Loop-Intervall. Diese Werte sind Bestandteil des Contracts.

Operative Mutation:

```text
LifecycleQueries
    -> Evidence
lifecycle_rules.py
    -> Reason
lifecycle_clean.py
    -> Candidate ordering / mode
MintRepository.disable_mints()
    -> tracking_enabled=false
    -> disabled_at=CURRENT_TIMESTAMP
    -> disabled_reason=<reason>
```

Read-only Downstream-Code besitzt keine Authority, diese Mutationskette zu umgehen.

## Validation Gate

Rule 1–5 sind gegenüber Contract v0.1 unverändert. Der Equivalence-Verifier muss für Änderungen an diesen Regeln weiterhin erfolgreich sein:

```powershell
python tools/verify_lifecycle_contract_v01.py
```

Rule 6 und Rule 7 werden zusätzlich über ihre gezielten Unit-Tests validiert.

## Versionierung

`0.3` wird nur ersetzt, wenn fachliche Lifecycle-Semantik bewusst geändert wird, insbesondere Thresholds, Zeitfenster, T0, Missing-Semantik, Evidence-Auswahl, Disable-Reasons, Regelreihenfolge oder First-match-Verhalten.

Interne Vereinfachungen bei identischem Candidate-Set erhöhen die Contract-Version nicht.
