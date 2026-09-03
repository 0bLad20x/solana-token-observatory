# Solana Token Observatory

[![CI](https://github.com/0bLad20x/solana-token-observatory/actions/workflows/verify.yml/badge.svg)](https://github.com/0bLad20x/solana-token-observatory/actions/workflows/verify.yml)

**A live, self-curating research environment for emerging Solana tokens.**

<!-- TODO: replace the static hero with a short Observatory product demo once captured. -->

<p align="center">
  <img src="docs/assets/observatory-universe.png" alt="Solana Token Observatory – Token Universe" width="100%">
</p>

New Solana tokens appear continuously. Keeping every discovered mint under permanent observation does not scale.

The Observatory discovers candidates across multiple live sources, observes their changing state, preserves meaningful source versions, and uses deterministic lifecycle rules to retire weak observation targets.

The surviving population becomes explorable: Market Pulse shows the system at population level, the Token Universe turns active launchpads and tokens into a live spatial environment, and selecting a token leads directly into current, temporal, web, and RugCheck evidence.

> The project is an observation and research system. It does not execute trades or make investment decisions.

## From discovery to investigation

```text
DISCOVER
PumpPortal · Jupiter · Meteora
        ↓
OBSERVE
parallel rate-limit-aware Jupiter Search lanes
        ↓
REMEMBER CHANGE
persist distinct upstream source versions
        ↓
SELF-CURATE
deterministic lifecycle rules
        ↓
EXPLORE
Market Pulse · Token Universe
        ↓
INVESTIGATE
Current · Temporal · Web · RugCheck
```

The core problem is not finding another mint. It is maintaining a useful working population while large volumes of external observations continue to arrive.

## Observation at scale

<!-- TODO: replace TBD values with one clearly dated measured runtime window. -->

> Runtime numbers below are pending measurement. They will describe one explicit observation window rather than static project guarantees.

| Measured runtime window | Observed |
|---|---:|
| Jupiter Search API keys | **TBD** |
| New mints discovered | **TBD** |
| Search requests | **TBD** |
| Mint observations | **TBD** |
| Distinct source versions persisted | **TBD** |
| Redundant observations not persisted | **TBD** |
| Tokens retired by lifecycle | **TBD** |
| Active population at end of window | **TBD** |

### A poll is not a snapshot

Repeated observation is necessary because the collector cannot know whether an upstream token state changed before asking for it. Persistence is change-aware: observing the same Jupiter `updatedAt` again advances observation state but does not create another historical snapshot.

The measured relationship between mint observations and distinct persisted source versions will make that difference visible here once the runtime counters are available.

## Explore the population

### Market Pulse

<!-- TODO: add a current Market Pulse screenshot or short capture. -->

Market Pulse provides the macro view of the observed population: activity, liquidity, breadth, concentration, and buy/sell behavior.

It answers:

> **What is the population doing right now?**

### Token Universe

<p align="center">
  <img src="docs/assets/observatory-universe.png" alt="Solana Token Observatory – Token Universe" width="100%">
</p>

The Token Universe is the mesoscopic view. Active tokens inhabit launchpad-centered clusters in a custom browser physics simulation. Market state affects bubble size, token age influences radial position, and lifecycle transitions change the visible population itself.

It answers:

> **What exists, where did it come from, and what catches my attention?**

### Investigate a token

<p align="center">
  <img src="docs/assets/analyst-search.png" alt="Solana Token Observatory – selected token investigation" width="100%">
</p>

Selecting a token synchronizes the Observatory around the same mint.

| Scope | Evidence |
|---|---|
| **Current** | projected current token state |
| **Temporal** | deterministic summary of retained observations |
| **Web** | external research bound to the exact mint |
| **RugCheck** | projected RugCheck evidence |

AI interprets bounded evidence. **Deterministic lifecycle rules alone control hard retirement.**

## The system curates itself

Discovery is intentionally broad. Continuous observation is expensive.

Seven deterministic lifecycle rules evaluate historical evidence and remove observation targets that no longer justify continued polling.

```text
new candidate
     ↓
observation
     ↓
temporal evidence accumulates
     ↓
┌──────────────────────┐
│ lifecycle evaluation │
└──────────┬───────────┘
           │
      ┌────┴────┐
      ↓         ↓
   survive    retire
      ↓          ↓
continue      stop consuming
observation   observation capacity
```

This creates a bounded working population instead of an ever-growing list of everything ever discovered.

The exact lifecycle semantics live in [`docs/LIFECYCLE_CONTRACT.md`](docs/LIFECYCLE_CONTRACT.md).

## What happens underneath

### Parallel observation

Multiple Jupiter API keys operate as independent, phase-shifted observation lanes over a shared active population. Adding observation capacity does not require duplicating lifecycle or persistence logic.

### Change-aware history

The collector distinguishes **seeing a token again** from **seeing a new source version**. Only distinct Jupiter source versions become historical snapshots.

### Deterministic temporal context

The Analyst does not receive an unrestricted dump of historical records. Core trajectory data is retained exactly while heavier rolling payloads are sampled into bounded temporal context before model interpretation.

### Evidence stays separate from interpretation

Raw/native evidence, deterministic projections, and AI interpretation remain distinct. `missing`, `unknown`, and numeric zero are not interchangeable.

## See the machine working

<p align="center">
  <img src="docs/assets/system-dataflow.gif" alt="Solana Token Observatory – Operational Flow" width="100%">
</p>

Operational Flow visualizes live Discovery, Search, persistence, and Lifecycle activity through a best-effort telemetry side channel.

The visualization is explanatory, not authoritative: durable domain state remains in PostgreSQL.

## Architecture

```mermaid
flowchart LR
    D["Discovery<br/>PumpPortal · Jupiter · Meteora"]
    O["Observation<br/>parallel Search lanes"]
    P["PostgreSQL<br/>identity + source versions"]
    L["Lifecycle<br/>deterministic reduction"]
    V["Observatory<br/>Market Pulse · Universe"]
    A["Investigation<br/>Current · Temporal · Web · RugCheck"]

    D --> O
    O --> P
    P --> L
    L --> O
    P --> V
    V --> A
```

The important boundary is simple:

```text
external sources
      ↓
observation
      ↓
durable evidence
      ↓
deterministic reduction
      ↓
human / AI investigation
```

The Observatory reads the resulting state; it does not own the underlying domain truth.

## Where this can grow

The current architecture is centered on tokens and their observed external state. A natural next direction is richer evidence rather than simply more features.

```text
Token
 ├── Jupiter market evidence
 ├── RugCheck evidence
 ├── Web evidence
 └── possible future on-chain / pool evidence
          └── Meteora DLMM state
```

Pool association, DLMM liquidity structure, and RPC/IDL-decoded on-chain state could make it possible to study how token behavior relates to the market structure underneath it.

These are **possible extensions of the existing research model, not current capabilities**.

## Run locally

### Requirements

- **Python 3.14**
- **PostgreSQL** — [Download](https://www.postgresql.org/download/)
- **Jupiter API key(s)** — [Jupiter Developer Portal](https://developers.jup.ag/portal)
- **PumpPortal API key** — required for the corresponding discovery source
- **Mistral API key** — [Mistral Console](https://console.mistral.ai/) for Analyst features
- **Node.js 24** — only needed for frontend contract tests

### Install

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Add local credentials to `.env`. The file is ignored by Git and must not be committed.

Initialize the schema:

```powershell
python src/main.py init-schema
```

Run the three operational paths:

```powershell
python src/main.py run
python src/lifecycle_clean.py --apply
python src/frontend.py
```

The Observatory is available by default at `http://127.0.0.1:8000`.

## Verification

Core deterministic verification:

```powershell
python -m compileall -q src tools
python -m unittest discover -s tests -v
python src/main.py --help
python src/lifecycle_clean.py --help
```

Frontend contracts:

```powershell
$tests = Get-ChildItem tests\*.mjs | ForEach-Object { $_.FullName }
node --test $tests
```

GitHub Actions runs the deterministic suite on pushes and pull requests to `main`.

Database-backed lifecycle equivalence and live external-provider behavior remain separate from deterministic CI.

## Deep dives

- [`docs/architecture.md`](docs/architecture.md) — architecture, ownership, and data flow
- [`docs/LIFECYCLE_CONTRACT.md`](docs/LIFECYCLE_CONTRACT.md) — exact lifecycle semantics
- [`docs/FRONTEND_OBSERVATORY.md`](docs/FRONTEND_OBSERVATORY.md) — Observatory, live state, telemetry, and Analyst contracts
- [`AGENTS.md`](AGENTS.md) — repository development rules
