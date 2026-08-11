# Lifecycle Contract

**Contract-Version:** `0.1`  
**Status:** frozen baseline  
**Scope:** operativer Hard-Retire-Pfad für `tracking_enabled=false`

## Zweck

Dieses Dokument ist die fachliche Authority für die derzeit implementierte Lifecycle-Semantik.

Refactorings dürfen SQL, Python-Struktur, Datenzugriff und interne Orchestrierung vereinfachen, solange für denselben Datenbankzustand exakt dieselben `(mint, reason)`-Kandidaten entstehen. Eine Änderung der hier beschriebenen Semantik ist keine Simplification, sondern eine neue Contract-Version.

Die operative Reihenfolge ist:

```text
Rule 1 -> Rule 2 -> Rule 3 -> Rule 4 -> Rule 5
```

Innerhalb eines Cycles gewinnt für einen Mint die erste passende Regel. Dry-Run und Apply verwenden dieselbe Candidate-Semantik; `--apply` bestimmt ausschließlich, ob die Kandidaten über `MintRepository.disable_mints()` tatsächlich deaktiviert werden.

## Gemeinsame Zeitbegriffe

- `created_at`: Jupiter-Erstellungszeit des Tokens.
- `first_observed_at`: lokale Zeit der ersten von diesem Collector beobachteten neuen Jupiter-Source-Version.
- `last_polled_at`: lokale Zeit des letzten erfolgreichen Jupiter-Search-Polls.
- `observed_at`: lokale Beobachtungszeit eines persistierten Snapshots.
- `source_updated_at`: zuletzt persistierte Jupiter-`updatedAt`-Version.
- `mint_snapshots`: immutable Historie beobachteter Jupiter-Source-Versionen.

Fehlende Werte bleiben fehlend. Ein fehlender numerischer Wert wird nicht als `0` interpretiert.

## Rule 1 — Failed to Ignite

**T0:** `first_observed_at`  
**Eligibility:** ab `T0 + 10 Minuten`, ohne Ablaufdatum  
**Evidence:** letzter persistierter Snapshot des Mints  
**Freshness:** `last_polled_at` muss vorhanden und höchstens `60 Sekunden` alt sein

Disable, wenn mindestens eine der folgenden Bedingungen erfüllt ist:

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

Decision payload:

- letzter Snapshot mit `observed_at <= T0 + 30 Minuten`.

Change evidence:

- `changes_in_window` ist die Anzahl der Snapshots mit `T0 + 10 Minuten < observed_at <= T0 + 30 Minuten`.

Kein Disable, wenn:

- `mcap` oder `liquidity` im Decision Payload fehlt; oder
- gleichzeitig `mcap >= 50_000` und `liquidity >= 5_000`.

Disable, wenn danach:

```text
changes_in_window <= 10
```

Disable-Reason:

```text
early_continuation_failure
```

## Rule 3 — Persistent Economic Absence

**T0:** `created_at`  
**Evaluation window:** `T0 + 5 Minuten` bis exklusiv `T0 + 6 Minuten`  
**Observation prerequisite:** `first_observed_at <= T0 + 5 Minuten`  
**Checkpoint prerequisite:** `last_polled_at >= T0 + 5 Minuten`

`has_economic_data=true`, wenn bis zum aktuellen Decision-Zeitpunkt in mindestens einem Snapshot mindestens eines der folgenden Felder nicht leer vorhanden war:

- `mcap`
- `liquidity`

Damit ist Rule 3 bewusst konservativ: Ein Mint, für den bis zur Entscheidung irgendwann Economic Data beobachtet wurde, wird von Rule 3 nicht deaktiviert.

Disable, wenn:

```text
has_economic_data == false
```

Disable-Reason:

```text
economic_data_missing_at_5m
```

## Rule 4 — Liquidity Collapse

**T0:** `created_at`  
**Eligibility:** ab `T0 + 30 Minuten`, ohne Ablaufdatum  
**Evidence:** immutable `mint_snapshots` ab dem T+30-Grenzpunkt  
**Current-poll freshness:** keine

Disable, sobald ein noch nicht sauber abgescannter Snapshot erfüllt:

```text
liquidity < 2_000
```

Disable-Reason:

```text
liquidity_collapse_below_2000
```

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

Disable-Reason:

```text
mcap_collapse_below_2000
```

Der Scan-Cursor folgt derselben Semantik wie Rule 4.

## Operational Contract

Der Lifecycle läuft standardmäßig alle `15 Sekunden`.

CLI:

```text
python src/lifecycle_clean.py
python src/lifecycle_clean.py --once
python src/lifecycle_clean.py --apply
python src/lifecycle_clean.py --apply --once
```

Es existieren keine CLI-Tuning-Parameter für Thresholds, Checkpoint-Fenster, Freshness oder Loop-Intervall. Diese Werte sind Bestandteil des Contracts und werden im Code versioniert.

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

`disabled_at` und `disabled_reason` sind Audit-Fakten der ausgeführten Entscheidung; sie verändern nicht die Candidate-Semantik.

Read-only Downstream-Code besitzt keine Authority, diese Mutationskette zu umgehen.

## Equivalence Gate

Vor einer reinen Lifecycle-Simplification muss ausgeführt werden:

```powershell
python tools/verify_lifecycle_contract_v01.py
```

Der Verifier liest denselben PostgreSQL-Snapshot sowohl mit der aktuellen Implementierung als auch mit einer eingefrorenen v0.1-Referenz aus und vergleicht pro Regel exakt die Sets:

```text
{(mint, reason)}
```

Akzeptanzkriterium:

```text
Rule 1 current == v0.1 reference
Rule 2 current == v0.1 reference
Rule 3 current == v0.1 reference
Rule 4 current == v0.1 reference
Rule 5 current == v0.1 reference
```

Ein Unterschied ist eine fachliche Verhaltensänderung und darf nicht als reine Simplification eingecheckt werden.

## Versionierung

`0.1` wird nur dann ersetzt, wenn eine fachliche Lifecycle-Regel bewusst geändert wird, zum Beispiel:

- Threshold;
- Zeitfenster;
- T0;
- Missing-Value-Semantik;
- Evidence-Auswahl;
- Disable-Reason;
- Regelreihenfolge;
- First-match-Verhalten.

Interne Vereinfachungen bei identischem Candidate-Set erhöhen die Contract-Version nicht.
