# Filter-Framework v2

## Sicherheitsgrenze

- Der Diagnose-Lauf fuehrt kein `UPDATE mints` aus.
- Er setzt weder `tracking_enabled` noch eine Prioritaet in PostgreSQL.
- Es wird keine persistente Lifecycle-, Rule- oder Evidence-Tabelle angelegt.
- `diag_*`-Tabellen sind transaktionale PostgreSQL-`TEMP TABLE`s und verschwinden
  beim Schliessen der Report-Verbindung.
- GMGN wird optional und rein lesend per Mint mit der neuesten Beobachtung
  verbunden. Fehlende GMGN-Daten verhindern keine Jupiter-Entscheidung.

## Neue Shadow-Actions

| Action | Vorgeschlagener Poll | Bedeutung |
|---|---:|---|
| P1 | 60 s | normal weiter beobachten |
| P2 | 300 s | jung/unklar, hohe Frequenz nicht mehr gerechtfertigt |
| P3 | 3600 s | Graveyard-Verdacht, nur noch selten pruefen |
| Retired | keiner | Shadow-Empfehlung zur Deaktivierung |

## Regeln

- `failed_at_birth_floor`: PIPE/AI-artige Fehlstarts koennen nach rund 30–60 s
  erkannt werden, sofern der erfolgreiche Mint-Poll frisch ist.
- `liquidity_removed_hard`: fast vollstaendiger Liquiditaetsabzug ist sofortige
  terminale Evidence.
- `pre_migration_return_to_floor`: echter Peak, Rueckkehr in den Floor,
  Holder-Verlust und erloschene 5-Minuten-Aktivitaet.
- `micro_pool_exhausted`: sehr kleiner Pool, sehr wenige Holder, keine Aktivitaet.
- `graveyard_low_signal_p3`: ab 15 Minuten P3-Kandidat.
- `graveyard_confirmed_retire`: ab 25 Minuten plus zwei Minuten Persistenz und
  zwei erfolgreiche per-Mint-Polls Retired-Kandidat.

Ein unveraenderter Payload braucht keinen zweiten Snapshot. Die Bestaetigung
zaehlt, wenn `mints.last_polled_at` fuer genau diesen Mint fortschreitet. Ein
ausgebliebener oder fehlgeschlagener Poll zaehlt nicht.

## Erster Lauf

Die vorhandene `data/policy_rules.json` durch die mitgelieferte Version ersetzen.
Ein alter `policy_state.json` mit Schema 1 wird beim Start absichtlich nicht
weiterverwendet, weil dessen Bestaetigungen auf globaler Monitor-Kontinuitaet
beruhten. Alte Decision-Events bleiben fuer Outcomes lesbar.

```powershell
python src/diagnose_inactivity.py
```

Danach fuer einen begrenzten Shadow-Test mit 60-Sekunden-Takt:

```powershell
python src/diagnose_inactivity.py --monitor --interval-seconds 60 --max-runs 30
```

Dashboard:

```powershell
python src/diagnostics_dashboard.py
```

Relevant sind zuerst Phase 6 **Filter evidence** und danach Phase 7
**Policy lab**. Phase 6 zeigt Allokation, Gruende, Regelstatus und kompakte
Token-Beispiele als Tabellen und Balken statt einer weiteren Heatmap.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Nach dem Shadow-Lauf bitte mindestens diese Dateien vergleichen:

- `data/investigation_report.json`
- `data/policy_runs.jsonl`
- `data/decision_events.jsonl`
- `data/policy_outcomes.json`
- `data/policy_state.json`

Erst nach ausgewerteten Outcome-Horizonten sollten die Shadow-Actions in echte
SQL-`UPDATE`s des Collectors ueberfuehrt werden.
