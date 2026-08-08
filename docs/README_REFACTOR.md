# Diagnose refactor + Phase 1 state space

This package keeps the V5 diagnostic/policy behavior split into modules and adds a first read-only semantic-region dashboard.

## Responsibilities

- `src/diagnose_inactivity.py` — CLI only.
- `src/diagnostics/constants.py` — paths, thresholds, current rule defaults.
- `src/diagnostics/data.py` — TEMP-table construction, context, collector-health reads, policy feature extraction.
- `src/diagnostics/analysis.py` — read-only diagnostic and population aggregations.
- `src/diagnostics/regions.py` — semantic Phase-1 region classification and `region_snapshot.json`.
- `src/diagnostics/policy.py` — experimental rule evaluation and longitudinal policy state.
- `src/diagnostics/storage.py` — JSON/JSONL persistence of diagnostic artifacts.
- `src/diagnostics/visualization.py` — legacy/static SVG rendering only.
- `src/diagnostics/dashboard.py` — Plotly/Dash presentation only; reads `region_snapshot.json`, no DB queries.
- `src/diagnostics/reporting.py` — builds and prints the current report.
- `src/diagnostics/monitor.py` — monitor-cycle orchestration.
- `src/diagnostics_dashboard.py` — tiny dashboard entrypoint.

No rule thresholds were intentionally changed and no permanent database writes were added.

## Phase 1 semantic dimensions

- Market Cap: `<$200`, `$200–2k`, `$2k–5k`, `$5k–10k`, `$10k–50k`, `$50k–250k`, `>=250k`
- Liquidity: `<$1`, `$1–100`, `$100–2k`, `$2k–10k`, `$10k–50k`, `>=50k`
- Holders: `0–2`, `3–10`, `11–30`, `31–100`, `101–500`, `>500`
- Age: `<30m`, `30–60m`, `1–3h`, `3–8h`, `8–24h`, `>=24h`
- Launchpad and graduation state are retained as filter dimensions.

These are explicit research regions, not production policy thresholds.

## Run

Install dashboard dependencies once:

```powershell
python -m pip install -r requirements-dashboard.txt
```

Generate a current snapshot/report:

```powershell
python src/diagnose_inactivity.py
```

Run one monitor cycle if policy-state advancement is desired:

```powershell
python src/diagnose_inactivity.py --monitor --max-runs 1
```

Start the local dashboard:

```powershell
python src/diagnostics_dashboard.py
```

Open `http://127.0.0.1:8050`.
