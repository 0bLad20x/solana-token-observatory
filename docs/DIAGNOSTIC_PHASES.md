# Jupiter Token Diagnostics — Phasen- und Analysevertrag

Version: 1  
Geltungsbereich: Diagnose- und Shadow-Policy-Framework  
Maschinenlesbares Ergebnis: `analysis/diagnostics_ai_bundle.json`

## 1. Ziel und Sicherheitsgrenze

Das Framework soll aus einer stark wachsenden Token-Population Regeln ableiten,
mit denen offensichtlich wertlose Tokens früh deaktiviert oder seltener
abgefragt werden können. Es ist keine Trading-Strategie und sagt nicht voraus,
welcher Token gekauft werden soll.

Der Diagnoseprozess ist **read-only gegenüber den operativen Mint-Daten**. Die
Actions `p2`, `p3` und `retire` sind Shadow-Empfehlungen. Es wird keine
Lifecycle-Tabelle angelegt und kein `tracking_enabled` verändert. Erst separat
validierte Regeln dürfen später in gezielte SQL-Updates des Collectors
überführt werden.

Die sieben Phasen beantworten unterschiedliche Fragen. Ihre Zahlen dürfen nur
über die hier beschriebenen Nenner miteinander verglichen werden.

## 2. Gemeinsame Begriffe

### Beobachtung und Poll

- Ein **Snapshot** ist ein gespeicherter fachlicher Zustand eines Tokens.
- Ein erfolgreicher **Poll** kann denselben Payload erneut liefern. Ein
  fortgeschrittenes `last_polled_at` bestätigt trotzdem, dass der Token erneut
  erfolgreich abgefragt wurde.
- Fehlende Aktivität erzeugt nicht zwingend einen neuen Snapshot. Deshalb
  verlangen zeitabhängige Regeln erfolgreiche per-Mint-Polls, nicht zwei
  unterschiedliche Payloads.
- `missing` oder `unknown` ist keine numerische Null.

### Populationen und Nenner

- **Prevalent/Baseline:** Bereits beim ersten Monitorlauf in einem Zustand.
- **Incident:** Eintritt in einen Zustand wurde nach Monitorstart beobachtet.
- **Matching:** Regelbedingung ist im aktuellen Zustand wahr.
- **Probation:** Bedingung ist wahr, Bestätigungszeit oder Poll-Anzahl fehlt.
- **Applied:** Shadow-Action wurde ausgelöst.
- **Matured:** Der konkrete Outcome-Horizont ist abgelaufen und kontinuierlich
  beobachtbar. Nur diese Tokens gehören in den Recovery-Nenner.

## Phase 1 — State Space

### Frage

Wo befindet sich die aktuelle Token-Population, und in welchen semantischen
Regionen konzentriert sie sich?

### Methode

Jeder aktuelle Token wird deterministisch in Kategorien eingeordnet:

- Market-Cap-Bucket
- Liquiditäts-Bucket
- Holder-Bucket
- Alters-Bucket
- Aktivitäts-Bucket
- Launchpad
- Graduation
- Shadow-Policy-Zustand

Das ist bewusst kein statistisches Clustering. Die Grenzen sind fachlich
benannt und damit als spätere Query-Bedingungen reproduzierbar.

Für eine Zelle `c` gilt:

```text
population_share(c) = count(c) / tracked_tokens
```

Die wirtschaftliche Region ist das Paar:

```text
region = market_cap_bucket × liquidity_bucket
```

### Sinnvolle Vergleiche

- Zellgröße gegen Gesamtpopulation
- Holder- und Altersstruktur innerhalb derselben wirtschaftlichen Region
- Region gegen Policy-Zustand
- Missing-Anteil gegen Collector- und Feldabdeckung

### Nicht zulässige Schlussfolgerung

Eine große Region beweist noch keinen Tod. Phase 1 zeigt **wo** eine Regel
wirken könnte. Ob ein Eintritt terminal ist, prüfen Phase 3 und Phase 7.

### Relevante JSON-Felder

`phases.phase_1_state_space.source_data`, `derived.economic_regions`,
`derived.dominant_cells`, `derived.coverage`

## Phase 2 — Region Flow

### Frage

Welche semantischen Regionen verlassen Tokens, wohin wechseln sie und wie
lange bleiben sie in ihrem Ausgangszustand?

### Methode

Eine Transition entsteht nur bei einem beobachteten Wechsel der wirtschaftlichen
Region. Market Cap und Liquidität werden getrennt geordnet. Für den Wechsel
von Zustand `a` nach `b` gilt:

```text
improved     := mcap(b) >= mcap(a) AND liq(b) >= liq(a)
                AND mindestens eine Dimension ist strikt besser
deteriorated := mcap(b) <= mcap(a) AND liq(b) <= liq(a)
                AND mindestens eine Dimension ist strikt schlechter
mixed        := eine Dimension besser, die andere schlechter
unknown      := mindestens eine erforderliche Dimension fehlt
```

Die angezeigte Exit-Rate einer Richtung verwendet ausschließlich beobachtete
Ausgänge als Nenner:

```text
improved_exit_share(region) = improved_exits / moves_out
```

Für die populationsbezogene Chance muss dagegen die Baseline verwendet werden:

```text
improved_population_share(region) = improved_exits / baseline_population
```

Diese beiden Werte beantworten verschiedene Fragen und dürfen nicht verwechselt
werden.

### Intervallzensierte Verweildauer

Der wahre Wechsel liegt zwischen zwei Polls. Deshalb gilt:

```text
dwell_lower <= true_dwell <= dwell_upper
```

Lücken werden nicht interpoliert. Unterbrochene Spells sind zensiert und dürfen
nicht als exakte Dwell-Samples behandelt werden.

### Readiness

Transitionen sind erst belastbar, wenn `coverage.sufficient_for_transitions`
wahr ist. Entscheidend sind kontinuierliche Abdeckung, Anzahl realer Moves und
Anzahl unterschiedlicher bewegter Mints — nicht allein die Laufanzahl.

### Relevante JSON-Felder

`phases.phase_2_region_flow.source_data.coverage`, `regions`, `transitions`,
`derived.population_normalized_regions`

## Phase 3 — Incident Cohorts

### Frage

Was geschieht, nachdem ein Token erstmals in einen definierten Zustand
eingetreten ist?

### Methode

Baseline-Tokens werden separat gezeigt, aber aus Outcome-Raten ausgeschlossen.
Für die primäre Auswertung wird jeder Mint ab seinem ersten beobachteten
incident Eintritt genau einmal gezählt. Dadurch dominieren oszillierende Tokens
die Statistik nicht.

Für Horizont `h` gilt:

```text
outcome_rate(k, h) = outcome_count(k, h) / matured_unique_mints(h)
```

Ein Mint ist nur `matured`, wenn:

1. der Horizont vollständig abgelaufen ist und
2. der relevante Beobachtungsbereich keine unzulässige Lücke enthält.

Die Survival-/Escape-Größe lautet:

```text
S(h) = still_inside_at_h / matured_unique_mints(h)
```

`same` bedeutet gleiche semantische Region, nicht identischer Preis.

### Sinnvolle Vergleiche

- `improved`, `deteriorated`, `same` und `unknown` bei gleichem Horizont
- 30-, 60-, 180- und 360-Minuten-Outcome derselben Kohorte
- unique-mint-Auswertung gegen episode-Auswertung als Oszillationskontrolle
- Incident-Zahl gegen Baseline-Größe als Evidenzabdeckung

### Nicht zulässige Schlussfolgerung

Eine große Baseline ist keine große Outcome-Stichprobe. Ohne incident Eintritte
und matured Horizonte ist die Kohorte nur beschrieben, nicht validiert.

### Relevante JSON-Felder

`phases.phase_3_incident_cohorts.source_data.cohorts`, `coverage`,
`derived.cohort_readiness`

## Phase 4 — Activity

### Frage

Ist ein Token wirtschaftlich aktiv, nimmt seine Aktivität ab oder fehlen die
dafür benötigten Daten?

### Methode

Activity wird aus den vorhandenen `stats1h`-Käufen/-Verkäufen und der Zeit seit
der letzten fachlichen Änderung abgeleitet. Die semantischen Buckets lauten
`hot`, `active`, `low`, `idle`, `dormant` und `unknown`.

Der wichtigste Qualitätswert ist:

```text
known_activity_coverage = tokens_with_known_activity / tracked_tokens
```

Anteile innerhalb einer Alters- oder Wirtschaftsgruppe werden zeilenweise
normalisiert:

```text
activity_share(activity | group) = count(group, activity) / count(group)
```

### Harte Interpretationsgrenze

`unknown` darf niemals als `idle`, `dormant` oder null Trades behandelt werden.
Eine sichere Extinction-Evidence liegt eher vor, wenn frühere Aktivität bekannt
war und danach bei weiterhin erfolgreichen Polls verschwindet.

### Relevante JSON-Felder

`phases.phase_4_activity.derived.coverage`, `by_age`, `by_market_cap`,
`by_liquidity`

## Phase 5 — Launchpads

### Frage

Ändern Herkunft oder Launchpad die Verteilung, Bewegung und Outcome-Raten?

### Methode

Launchpads unterscheiden sich stark in ihrer Populationsgröße. Deshalb werden
Raten innerhalb des jeweiligen Launchpads normalisiert:

```text
rate(event | launchpad) = count(event AND launchpad) / count(launchpad)
```

Rohzahlen zwischen Launchpads sind ohne diesen Nenner nicht vergleichbar. Jede
Rate muss zusammen mit `n` gelesen werden.

### Sinnvolle Verwendung

- Thresholds nach Launchpad kalibrieren
- Graduation- und Retire-Raten innerhalb derselben Herkunft vergleichen
- prüfen, ob eine Regel nur eine technische Eigenschaft eines Launchpads
  wiedererkennt

### Nicht zulässige Schlussfolgerung

Korrelation ist keine Ursache. Ein hoher Retire-Anteil beweist nicht, dass das
Launchpad den Tod verursacht. Kleine Launchpads liefern keine belastbaren
Raten.

### Relevante JSON-Felder

`phases.phase_5_launchpads.derived.profiles`, `flow_by_launchpad`

## Phase 6 — Filter Evidence

### Frage

Welche Tokens könnten jetzt mit welcher Begründung herabgestuft oder deaktiviert
werden, und wie stark würde das die Polling-Last reduzieren?

### Regel- und Zustandsmodell

Jede Regel ist eine versionierte boolesche Funktion über aktuelle und
historische Features:

```text
match(rule, token, t) -> true | false
```

Eine poll-bestätigte Regel durchläuft:

```text
NONE -> PROBATION -> APPLIED
```

`APPLIED` verlangt sowohl die konfigurierte Persistenzzeit als auch die
Mindestanzahl erfolgreicher per-Mint-Polls. Eine inhaltlich unveränderte Antwort
ist eine gültige Bestätigung, sofern `last_polled_at` fortschreitet.

Treffen mehrere Regeln zu, gewinnt die stärkste Action:

```text
retire > p3 > p2 > p1
```

### Stateful gegen instantaneous

- **Stateful allocation:** tatsächlich ausgereifte Shadow-Actions.
- **Instantaneous allocation:** hypothetische Verteilung, wenn alle aktuell
  passenden Regeln ohne Bestätigungszeit sofort greifen würden.

Die Differenz ist die aktuelle Probation-/Persistenz-Pipeline, kein Widerspruch.

### Polling-Last

Mit Population `N_a` und Cadence `c_a` einer Action `a`:

```text
poll_equivalent_per_second = Σ_a N_a / c_a
load_reduction = 1 - proposed_load / current_all_p1_load
```

`retire` trägt null individuelle Polls bei. Das ist eine Kapazitätsprojektion,
keine Datenbankmutation.

### Relevante JSON-Felder

`phases.phase_6_filter_evidence.source_data`, `derived.allocation_comparison`,
`derived.polling_load_projection`, `derived.rules`

## Phase 7 — Policy Lab

### Frage

War die Shadow-Entscheidung sicher, oder hätte ein aussortierter Token später
noch ein relevantes Ziel erreicht?

### Methode

Outcomes werden pro exaktem `rule_key` ausgewertet. Der Key enthält Regel-ID,
Version und Konfigurationshash. Historische Regeln dürfen nicht mit dem aktiven
Regelsatz vereinigt werden.

Für Regel `r` und Horizont `h`:

```text
recovery_rate(r, h) = recovered_unique_mints / matured_unique_mints
false_retirement_rate = recovery_rate
```

Mögliche Recovery-Milestones sind unter anderem:

- Market Cap über 10k als schwacher Escape
- Market Cap über 50k bei ausreichender Liquidität
- Market Cap über 200k
- Graduation nach der Action

Eine einzelne Dust-Transaktion ist keine relevante Recovery.

### Unsicherheit

Auch null beobachtete Recoveries bedeuten bei kleinem `n` nicht null wahres
Risiko. Der AI-Export berechnet deshalb ein Wilson-95%-Intervall. Bei `0/n`
ist dessen Obergrenze die relevante konservative Risikoschranke.

Eine Regel ist erst direkt bewertbar, wenn ihr aktiver `rule_key` Applied-Fälle
und mindestens einen matured Horizont besitzt. Legacy-Regeln werden separat
gezählt und aus der aktuellen Entscheidung ausgeschlossen.

### Relevante JSON-Felder

`phases.phase_7_policy_lab.active_rule_outcomes`, `rule_readiness`,
`excluded_legacy_rule_versions`

## 3. Verbindliche Cross-Phase-Vergleiche

| Entscheidung | Richtiger Vergleich |
|---|---|
| Wo steckt das größte Einsparpotenzial? | Phase 1 Population × Phase 6 aktuelle Matches |
| Ist ein Zustand überwiegend terminal? | Phase 3 matured Outcomes derselben Incident-Kohorte |
| Ist eine konkrete Regel sicher? | Phase 6 exakter `rule_key` × Phase 7 derselbe `rule_key` |
| Ist eine Bewegung häufig? | Phase 2 Moves / Baseline, nicht nur Richtung / Exits |
| Ist Inaktivität belastbar? | Phase 4 known coverage + erfolgreicher Poll-Verlauf |
| Braucht ein Launchpad andere Grenzen? | Phase 5 normalisierte Rate mit ausreichendem `n` |

## 4. Reihenfolge für eine KI-Auswertung

1. `meta`, `source_manifest` und `quality_gates` prüfen.
2. Collector Health und Technical Validation prüfen.
3. Phase 6 lesen: Welche Regel matcht, ist in Probation oder Applied?
4. Phase 7 lesen: Welche aktiven Regeln besitzen matured Outcomes und wie hoch
   ist die Wilson-Obergrenze der Recovery?
5. Phase 1 lesen: Wie groß ist die betroffene Population?
6. Phase 3 lesen: Bestätigt die zustandsbezogene Kohorte die Regelhypothese?
7. Phase 2 nur bei ausreichender Transition-Coverage interpretieren.
8. Phase 4 und 5 als Datenqualitäts- und Segmentierungsprüfung verwenden.

## 5. Fragen, die eine KI beantworten soll

- Welche aktiven Regeln sind bereits entscheidungsfähig, welche nur
  hypothesengenerierend?
- Wie groß ist das Retire-/Demote-Potenzial ohne Doppelzählung?
- Welche Recovery-Obergrenze ergibt sich je Regel und Horizont?
- Welche Ergebnisse sind durch Missingness, Lücken oder kleine Nenner begrenzt?
- Gibt es eine große Population, die keine aktuelle Regel erfasst?
- Sind Schwellenwerte zu konservativ oder zu aggressiv?
- Welche einzelne zusätzliche Messung oder Regel würde den größten blinden
  Fleck reduzieren?

Die KI muss Fakten, Schlussfolgerungen und Vorschläge getrennt ausgeben. Ein
fehlender oder unreifer Nenner darf nicht durch Plausibilität ersetzt werden.
