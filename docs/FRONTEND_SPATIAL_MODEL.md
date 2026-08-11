# Frontend Spatial Model — V3

## Status

**Authority:** V3 Bubble-Cluster-Layout und `ViewSpec`-Verhalten  
**Parent authority:** `docs/FRONTEND_OBSERVATORY.md`  
**Branch:** `agent/generic-bubble-physics-v3`  
**Checkpoint:** V3-A nach fehlgeschlagener Browservalidierung neu implementiert; erneute Browservalidierung erforderlich

V2 verhinderte globale Repaints durch normale SSE-Deltas. V3 definiert darauf aufbauend eine wiederverwendbare räumliche Grammatik.

## 1. First principle

```text
Token data + ViewSpec
        ↓
groupKey / radius / optional targets
        ↓
layout-specific spatial model
        ↓
Pixi rendering
```

Der Renderer besitzt keine Launchpad-Physik. `ViewSpec.group` erzeugt `groupKey`; die Cluster Engine verarbeitet beliebige `groupKey`-Werte gleich.

Die Engine ist nur innerhalb von `layout = cluster` generisch. Projection, Flow, Tree und Network dürfen später eigene etablierte Layouts verwenden.

## 2. Minimaler Node-Vertrag

```text
mint
token
groupKey
radius
x / y
selection state
enter / retire state
temporary drag state
```

Business Truth bleibt außerhalb des Renderers. V3 führt keine freie Expression-Sprache ein.

Aktives V3-A-Preset:

```json
{
  "type": "bubble",
  "layout": "cluster",
  "group": "launchpad",
  "size": "market_cap",
  "color": "launchpad",
  "x": null,
  "y": null
}
```

## 3. Bewegungssemantik

Ein Node darf sich nur bewegen wegen:

1. sichtbarer Änderung einer gemappten Geometrie;
2. echtem `groupKey`-Wechsel;
3. User-Drag;
4. Populationseintritt oder -austritt;
5. explizitem View-Wechsel oder Resize-Refit.

Ein normales SSE-Update allein ist kein Bewegungsgrund. Subpixel-Änderungen werden akkumuliert, bis sie im aktuellen Screen Space sichtbar sind.

## 4. Cluster-Invarianten

### Zugehörigkeit

Jeder Node besitzt genau eine aktive Cluster Domain:

```text
domain = group center + group radius
```

Drag verändert niemals `groupKey`. Die Node-Mitte wird auf die eigene Domain begrenzt. Ein Node kann deshalb weder lose außerhalb liegen noch in ein fremdes Cluster abgelegt werden.

### Isolation

Collision und lokale Relaxation betrachten ausschließlich Nodes desselben `groupKey`. Cluster beeinflussen einander nicht im Live-Solver. Ihre Domains werden nur beim Bootstrap oder expliziten globalen Refit gemeinsam gepackt.

### Abstand

```text
minimum distance = radiusA + radiusB + collision gap
```

Der Bootstrap verwendet zusätzlich einen größeren Pack-Abstand. Dieser sichtbare und physische Spielraum verhindert, dass jede kleine Radiusänderung eine Kontaktkette durch den gesamten Cluster auslöst.

## 5. Zwei räumliche Zustände

### Packed rest state

Bootstrap, Resize und expliziter View-Wechsel verwenden `d3.packSiblings` und `d3.packEnclose`:

```text
Nodes pro groupKey packen
        ↓
enclosing cluster circles berechnen
        ↓
cluster circles packen
        ↓
einmal rendern und ruhen
```

Das Ergebnis ist kompakt, deterministisch, überlappungsfrei und besitzt explizite Cluster Domains.

### Bounded interaction state

Live-Interaktion verwendet keine Velocity-Simulation. Nur die betroffene Gruppe und deren geweckte Nachbarschaft werden positional aufgelöst:

```text
finite center compaction
+ quadtree collision resolution
+ circular domain constraint
```

Positionen werden direkt korrigiert. Es gibt keine Geschwindigkeit, Trägheit, Force-Reheizung oder Oszillation. Wenn keine räumliche Arbeit aktiv ist, läuft kein Layout-Code über die Population.

## 6. Ereignisse

### Radiusänderung

Der neue Radius entsteht an derselben Position. Der Node bleibt während der Relaxation verankert; ausschließlich notwendige Nachbarn weichen aus.

### Drag

Der Pointer bewegt den Node nur innerhalb seiner Domain. Kollision weckt ausschließlich berührte Nodes derselben Gruppe. Vor dem Drag werden die Restpositionen der betroffenen Nachbarschaft gespeichert; nach Release kehren Node und Nachbarn dorthin zurück. Drag ist damit vollständig temporär und zerstört keine räumliche Erinnerung.

### Retirement

Der Node signalisiert den fachlichen Austritt kurz in `destructive`, kollabiert und wird danach entfernt. Erst dann kompaktieren nahe Nodes die Vacancy in Richtung Clusterzentrum.

### Neuer Node

Ein neuer Node wird deterministisch am freien Domain-Rand seines `groupKey` geseedet und durch dieselben Collision-/Compaction-Constraints integriert.

### `groupKey`-Wechsel

Die alte Gruppe schließt die Vacancy. Der Node tritt in die neue Domain ein. Das ist die einzige Live-Interaktion, die einen fachlichen A→B-Wechsel darstellt.

## 7. Visuelle Semantik in V3-A

```text
radius       = market_cap
fill color   = groupKey / launchpad
cyan stroke  = selection
red          = retirement
motion       = ausschließlich räumliches Ereignis
```

Freshness, Liquidity und allgemeine SSE-Aktivität sind im aktiven `ViewSpec` nicht gemappt und verändern deshalb weder Alpha, Stroke noch Scale.

Die Bubble selbst pulsiert bei Updates nicht. Ein geometrisches Update ist an der tatsächlichen Radiusänderung erkennbar; der Event Feed liefert die präzise Delta-Evidence.

## 8. Research decision

### Fehlgeschlagener Ansatz

Die erste V3-A-Implementierung verwendete eine lokale `d3-force`-Simulation mit `forceX`, `forceY`, `forceCollide`, `fx/fy` und einer 96-Pixel-Quadtree-Nachbarschaft.

Die Browservalidierung widerlegte die Annahme, dass dieser Mechanismus den Vertrag erfüllt:

- Drag war nur am Viewport begrenzt, nicht an der Cluster Domain;
- Nachbarschaften waren nicht nach `groupKey` isoliert;
- mehrere Live-Deltas konnten fast den gesamten Großcluster reaktivieren;
- Velocity und erneutes Alpha-Heating erzeugten sichtbare Nervosität;
- ein Scale-Pulse verfälschte Collision-Radius und Größenwahrnehmung;
- der Cluster besaß keinen stabilen gepackten Restzustand.

Dieser Ansatz ist verworfen und wurde nicht weiter parametrisch getunt.

### Gewählter Mechanismus

```text
d3-hierarchy   exact initial/refit packing
d3-quadtree    same-group collision lookup
direct constraints without velocity
finite active neighborhoods
PixiJS         rendering and pointer input
```

Keine neue Physics Dependency ist erforderlich.

### Verworfene Alternativen

- dauerhafte `d3-force`-Simulation: bleibt velocity-basiert und muss wiederholt reheated werden;
- Matter.js: liefert Sleeping und Rigid Bodies, benötigt für diesen Vertrag aber zusätzliche Springs, Group Filtering und Domain Constraints;
- wiederholtes Full Packing bei jedem Delta: kompakt, zerstört aber Live-Spatial-Continuity;
- event-spezifische `findFreeCoordinate()`- oder `fillHole()`-Algorithmen: duplizieren räumliche Verantwortung.

## 9. V3-A-Akzeptanz

V3-A ist erst bestanden, wenn im realen Browser alle Punkte gleichzeitig gelten:

```text
bootstrap        → kompakte, getrennte Cluster
idle             → vollständig ruhig
ordinary update  → keine räumliche Reaktion
radius growth    → verankertes Wachstum, lokale Verdrängung
radius shrink    → lokale Kompaktierung
drag             → eigene Domain, gleiche Gruppe, temporäre Nachbarreaktion
release          → Rückkehr zum stabilen Restzustand
retirement       → sichtbarer Exit, danach Vacancy Closing
other groups     → exakt keine Live-Bewegung
```

V3-B beginnt vorher nicht.

## 10. V3-B und spätere Grenzen

V3-B beweist dieselbe Cluster Engine mit mindestens zwei Presets:

```text
group = launchpad
group = market_cap_tier oder age_tier
```

Semantic Zoom oder Density Aggregation ist kein V3-A-Fix. Es ist eine spätere eigene Grenze, falls die stabile Übersicht mit wachsender Population nicht mehr lesbar ist. Dabei dürfen Nodes nicht zufällig ausgeblendet werden; Overview, Cluster-Zoom und Detail-Zoom benötigen einen deterministischen View-Vertrag.

Flow, Tree, Network, Projection, LLM Cohorts und Discovery Provenance bleiben außerhalb V3-A.

## 11. Systemgrenzen

V3 verändert nur die read-only räumliche Projektion. Es verändert weder PostgreSQL-Schema, Collector, Lifecycle v0.1 noch operative Token-Zustände.
