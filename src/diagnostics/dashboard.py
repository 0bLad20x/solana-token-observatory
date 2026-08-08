"""Local dashboard for the Jupiter token state space.

Reads the artifacts produced by the analysis layer and nothing else — no
database, no policy logic, no writes. Every view is a prepared question rather
than a generic chart builder: the filters are shared across all phases, and a
region picked in the state space stays pinned while you walk through flow,
cohorts, activity, launchpads and the policy lab.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import theme
from .constants import (
    COHORT_OUTCOMES_PATH,
    OUTPUT_PATH,
    POLICY_OUTCOMES_PATH,
    REGION_DEGRADED_SNAPSHOT_PATH,
    REGION_FLOW_PATH,
    REGION_SNAPSHOT_PATH,
)
from .regions import (
    ACTIVITY_BUCKETS,
    SEMANTIC_SCHEMA_HASH,
    region_coords,
    CELL_SCHEMA,
    LIQUIDITY_BUCKETS,
    LIQUIDITY_LABELS,
    MCAP_BUCKETS,
    MCAP_LABELS,
    region_id,
    region_label,
    split_region_id,
)

IDX = {name: position for position, name in enumerate(CELL_SCHEMA)}
COUNT = IDX["count"]

VIEWS = [
    ("state", "1", "State space", "Where the population is right now"),
    ("flow", "2", "Flow & dwell", "Where tokens move and how long they stay"),
    ("cohorts", "3", "Cohorts", "What happens after a token enters a state"),
    ("activity", "4", "Activity", "Accelerating, stable, decaying or dormant"),
    ("origin", "5", "Launchpads", "Does origin change the outcome"),
    ("filter", "6", "Filter evidence", "Who can be demoted or retired, and why"),
    ("policy", "7", "Policy lab", "Which rule would remove load safely"),
]

MODES = [("log", "Log colour"), ("count", "Linear"), ("share", "% of filter")]

# Prepared filter sets. Each preset writes the whole filter bar at once, so a
# question can be asked in one click instead of six.
PRESETS: list[dict[str, Any]] = [
    {"key": "all", "label": "Full population", "filters": {}},
    {
        "key": "mass_point",
        "label": "Mass point $2k–5k",
        "filters": {"mcap": ["2k_5k"], "liquidity": ["2k_10k"]},
    },
    {
        "key": "fresh",
        "label": "Fresh <1h",
        "filters": {"age": ["under_30m", "30_60m"]},
    },
    {
        "key": "zombies",
        "label": "Dormant (no trades)",
        "filters": {"activity": ["dormant", "idle"], "age": ["1_3h", "3_8h", "8_24h", "24h_plus"]},
    },
    {
        "key": "dust",
        "label": "Dust corner",
        "filters": {"mcap": ["under_200", "200_2k"], "liquidity": ["under_1", "1_100"]},
    },
    {
        "key": "orphan",
        "label": "Liquidity without holders",
        "filters": {"liquidity": ["10k_50k", "50k_plus"], "holders": ["0_2", "3_10"]},
    },
    {
        "key": "pre_grad",
        "label": "Approaching graduation",
        "filters": {"mcap": ["50k_250k", "250k_plus"], "graduation": "not_graduated"},
    },
    {
        "key": "retire",
        "label": "Retire candidates",
        "filters": {"policy": "would_retire"},
    },
]

FILTER_FIELDS = ["launchpad", "graduation", "age", "holders", "activity", "mcap", "liquidity", "policy"]


# --------------------------------------------------------------------------
# artifacts
# --------------------------------------------------------------------------

def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_snapshot(path: Path = REGION_SNAPSHOT_PATH) -> dict[str, Any]:
    snapshot = _load_json(path)
    if snapshot is None:
        raise FileNotFoundError(
            f"Region snapshot fehlt oder ist unlesbar: {path}. "
            "Zuerst diagnose_inactivity.py ausführen."
        )
    if snapshot.get("schema_version") != 2:
        raise SystemExit(
            "region_snapshot.json hat schema_version "
            f"{snapshot.get('schema_version')}; dieses Dashboard erwartet 2. "
            "Einmal diagnose_inactivity.py neu laufen lassen."
        )
    if snapshot.get("semantic_schema_hash") != SEMANTIC_SCHEMA_HASH:
        raise SystemExit(
            "region_snapshot.json gehoert zu einer anderen Bucket-Definition. "
            "Einmal einen neuen gesunden Diagnose-Lauf erzeugen."
        )
    return snapshot


def load_artifacts(snapshot_path: Path = REGION_SNAPSHOT_PATH) -> dict[str, Any]:
    return {
        "snapshot": load_snapshot(snapshot_path),
        "degraded_snapshot": _load_json(REGION_DEGRADED_SNAPSHOT_PATH),
        "flow": _load_json(REGION_FLOW_PATH),
        "cohorts": _load_json(COHORT_OUTCOMES_PATH),
        "policy_outcomes": _load_json(POLICY_OUTCOMES_PATH),
        "report": _load_json(OUTPUT_PATH),
    }


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------

def _dimension(snapshot: dict, dimension: str) -> tuple[list[str], dict[str, str]]:
    rows = snapshot["dimensions"][dimension]
    return [row["key"] for row in rows], {row["key"]: row["label"] for row in rows}


def filtered_rows(snapshot: dict, filters: dict, ignore: set[str] | None = None) -> list[list]:
    ignore = ignore or set()
    sets = {}
    for field, column in (
        ("launchpad", "launchpad"),
        ("age", "age_bucket"),
        ("holders", "holder_bucket"),
        ("activity", "activity_bucket"),
        ("mcap", "mcap_bucket"),
        ("liquidity", "liquidity_bucket"),
    ):
        if field in ignore:
            continue
        values = filters.get(field)
        if values:
            sets[IDX[column]] = set(values)

    graduation = filters.get("graduation")
    if graduation and graduation != "all" and "graduation" not in ignore:
        sets[IDX["graduation"]] = {graduation}
    policy = filters.get("policy")
    if policy and policy != "all" and "policy" not in ignore:
        sets[IDX["policy_status"]] = {policy}

    region = filters.get("region")
    region_keys = None
    if region and "region" not in ignore:
        region_keys = split_region_id(region)

    rows = []
    for row in snapshot["cells"]:
        if any(row[position] not in allowed for position, allowed in sets.items()):
            continue
        if region_keys is not None and (
            row[IDX["mcap_bucket"]] != region_keys[0]
            or row[IDX["liquidity_bucket"]] != region_keys[1]
        ):
            continue
        rows.append(row)
    return rows


def total_of(rows: list[list]) -> int:
    return sum(row[COUNT] for row in rows)


def tally(rows: list[list], column: str) -> Counter:
    counter: Counter = Counter()
    position = IDX[column]
    for row in rows:
        counter[row[position]] += row[COUNT]
    return counter


def cross_tally(rows: list[list], x_column: str, y_column: str) -> dict[tuple[str, str], int]:
    xi, yi = IDX[x_column], IDX[y_column]
    result: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        result[(row[xi], row[yi])] += row[COUNT]
    return result


def fmt(value: float | int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f}" if abs(value) >= 1 or value == 0 else f"{value:.2f}"


def abbr(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"{value / 1_000:.0f}k"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(value)


def pct(part: float, whole: float) -> str:
    return f"{part / whole * 100:.1f}%" if whole else "—"


# --------------------------------------------------------------------------
# small presentational helpers
# --------------------------------------------------------------------------

def kpi(label: str, value: str, foot: str = "", tone: str = ""):
    from dash import html

    return html.Div(
        [
            html.Div(label, className="k-label"),
            html.Div(value, className=f"k-value {tone}"),
            html.Div(foot, className="k-foot"),
        ],
        className="card kpi",
    )


def card(title: str, *children, note: str = "", flush: bool = False):
    from dash import html

    head = [html.P(title, className="card-title")]
    if note:
        head.append(html.P(note, className="card-note"))
    return html.Div(head + list(children), className="card flush" if flush else "card")


def empty_state(title: str, *lines):
    from dash import html

    return html.Div([html.Strong(title)] + list(lines), className="empty")


def filters_not_applied(*fields: str):
    """Say plainly that the left-hand filters do not reach this view."""
    from dash import html

    return html.Div(
        [
            html.Strong("The filters on the left are not applied here."),
            html.Span(
                "This view is rendered from the aggregated history artifact, which "
                "currently carries "
                + (", ".join(fields) if fields else "no filterable dimensions")
                + ". Everything below describes the whole tracked population."
            ),
        ],
        className="empty",
        style={"borderColor": theme.AMBER, "marginBottom": "14px"},
    )


def snapshot_health_banner(data: dict):
    """Visible warning when the canonical view is stale or a newer run degraded."""
    from dash import html

    healthy = data.get("snapshot") or {}
    degraded = data.get("degraded_snapshot") or {}
    healthy_at = datetime.fromisoformat(healthy["generated_at"]) if healthy.get("generated_at") else None
    degraded_at = datetime.fromisoformat(degraded["generated_at"]) if degraded.get("generated_at") else None
    if healthy_at and healthy_at.tzinfo is None:
        healthy_at = healthy_at.replace(tzinfo=timezone.utc)
    if degraded_at and degraded_at.tzinfo is None:
        degraded_at = degraded_at.replace(tzinfo=timezone.utc)

    reasons = []
    if degraded_at and (healthy_at is None or degraded_at > healthy_at):
        reasons.append(
            f"A newer collector run at {degraded_at.isoformat()} was degraded; the dashboard keeps the last healthy snapshot."
        )
    if healthy_at:
        expected = int(healthy.get("expected_interval_seconds") or 300)
        age_seconds = max((datetime.now(timezone.utc) - healthy_at).total_seconds(), 0.0)
        if age_seconds > expected * 2.5:
            reasons.append(f"The last healthy snapshot is {age_seconds / 60:.0f} minutes old.")

    if not reasons:
        return None
    return html.Div(
        [html.Strong("Snapshot warning. "), html.Span(" ".join(reasons))],
        className="empty",
        style={"borderColor": theme.AMBER, "marginBottom": "14px"},
    )


def bar_list(items: list[tuple[str, int]], color: str, limit: int = 8):
    from dash import html

    rows = []
    biggest = max((count for _label, count in items), default=0) or 1
    for label, count in items[:limit]:
        rows.append(
            html.Div(
                [
                    html.Div(label, className="name", title=label),
                    html.Div(
                        html.Div(
                            style={
                                "width": f"{count / biggest * 100:.1f}%",
                                "background": color,
                            },
                            className="fill",
                        ),
                        className="track",
                    ),
                    html.Div(fmt(count), className="val"),
                ],
                className="bar-row",
            )
        )
    return html.Div(rows or [html.Div("no data", className="readout")])


def graph(figure, height: int = 460, element_id: str | None = None):
    from dash import dcc

    kwargs = {"id": element_id} if element_id else {}
    return dcc.Graph(
        figure=figure,
        config=theme.GRAPH_CONFIG,
        style={"height": f"{height}px"},
        **kwargs,
    )


# --------------------------------------------------------------------------
# figures
# --------------------------------------------------------------------------

def state_space_figure(snapshot: dict, rows: list[list], mode: str, base_rows: list[list] | None = None):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    x_order, x_labels = _dimension(snapshot, "mcap")
    y_order, y_labels = _dimension(snapshot, "liquidity")
    counts = cross_tally(rows, "mcap_bucket", "liquidity_bucket")
    grand_total = total_of(rows) or 1

    base_counts = None
    if mode == "retire" and base_rows is not None:
        base_counts = cross_tally(base_rows, "mcap_bucket", "liquidity_bucket")

    z: list[list[float]] = []
    raw: list[list[int]] = []
    for y_key in y_order:
        z_row, raw_row = [], []
        for x_key in x_order:
            count = counts.get((x_key, y_key), 0)
            raw_row.append(count)
            if mode == "count":
                z_row.append(count)
            elif mode == "share":
                z_row.append(count / grand_total * 100)
            elif mode == "retire":
                base = (base_counts or {}).get((x_key, y_key), 0)
                z_row.append(count / base * 100 if base >= 10 else None)
            else:
                z_row.append(math.log10(count + 1))
        z.append(z_row)
        raw.append(raw_row)

    if mode == "log":
        peak = max((value for row in z for value in row), default=0)
        ticks = [1, 10, 100, 1_000, 10_000, 100_000]
        ticks = [value for value in ticks if math.log10(value + 1) <= peak + 0.4]
        colorbar = {
            "title": {"text": "tokens", "font": {"size": 10}},
            "tickvals": [math.log10(value + 1) for value in ticks],
            "ticktext": [abbr(value) for value in ticks],
        }
        scale = theme.DENSITY_SCALE
    elif mode == "share":
        colorbar = {"title": {"text": "% filtered", "font": {"size": 10}}}
        scale = theme.DENSITY_SCALE
    elif mode == "retire":
        colorbar = {"title": {"text": "% retire", "font": {"size": 10}}}
        scale = theme.RISK_SCALE
    else:
        colorbar = {"title": {"text": "tokens", "font": {"size": 10}}}
        scale = theme.DENSITY_SCALE

    figure = make_subplots(
        rows=2,
        cols=2,
        column_widths=[0.86, 0.14],
        row_heights=[0.17, 0.83],
        horizontal_spacing=0.012,
        vertical_spacing=0.02,
        shared_xaxes=True,
        shared_yaxes=True,
        specs=[[{}, None], [{}, {}]],
    )

    hover_extra = "Share of filtered: %{customdata[1]:.2f}%"
    if mode == "retire":
        hover_extra = "Would-retire share: %{z:.1f}%"

    figure.add_trace(
        go.Heatmap(
            x=[x_labels[key] for key in x_order],
            y=[y_labels[key] for key in y_order],
            z=z,
            customdata=[[[raw[j][i], raw[j][i] / grand_total * 100] for i in range(len(x_order))] for j in range(len(y_order))],
            colorscale=scale,
            colorbar=colorbar | {"thickness": 11, "len": 0.78, "y": 0.4, "outlinewidth": 0, "tickfont": {"size": 10}},
            hovertemplate=(
                "Market cap %{x}<br>Liquidity %{y}<br>"
                "Tokens: %{customdata[0]:,}<br>" + hover_extra + "<extra></extra>"
            ),
            xgap=2,
            ygap=2,
            zmin=0,
        ),
        row=2,
        col=1,
    )

    mcap_marginal = [sum(raw[j][i] for j in range(len(y_order))) for i in range(len(x_order))]
    liq_marginal = [sum(row) for row in raw]

    figure.add_trace(
        go.Bar(
            x=[x_labels[key] for key in x_order],
            y=mcap_marginal,
            marker_color="rgba(76,141,246,0.55)",
            hovertemplate="%{x}<br>%{y:,} tokens<extra></extra>",
            showlegend=False,
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Bar(
            x=liq_marginal,
            y=[y_labels[key] for key in y_order],
            orientation="h",
            marker_color="rgba(47,191,160,0.5)",
            hovertemplate="%{y}<br>%{x:,} tokens<extra></extra>",
            showlegend=False,
        ),
        row=2,
        col=2,
    )

    heat = figure.data[0]
    xref, yref = heat.xaxis or "x", heat.yaxis or "y"
    annotations = []
    peak_raw = max((value for row in raw for value in row), default=0) or 1
    for j, y_key in enumerate(y_order):
        for i, x_key in enumerate(x_order):
            count = raw[j][i]
            if not count:
                continue
            if mode == "retire":
                base = (base_counts or {}).get((x_key, y_key), 0)
                text = f"{count / base * 100:.0f}%" if base >= 10 else ""
            else:
                text = abbr(count)
            if not text:
                continue
            intensity = math.log10(count + 1) / math.log10(peak_raw + 1)
            annotations.append(
                {
                    "x": x_labels[x_key],
                    "y": y_labels[y_key],
                    "text": text,
                    "showarrow": False,
                    "xref": xref,
                    "yref": yref,
                    "font": {
                        "family": theme.FONT_MONO,
                        "size": 10,
                        "color": "#0A0E15" if intensity > 0.82 else "rgba(231,235,243,0.78)",
                    },
                }
            )

    figure.update_layout(
        annotations=annotations,
        margin={"l": 96, "r": 20, "t": 18, "b": 62},
        bargap=0.25,
        showlegend=False,
    )

    # Unknown is a category, not a value: keep it in the picture but fenced off.
    if "missing" in x_order:
        figure.add_shape(
            type="line",
            x0=x_order.index("missing") - 0.5,
            x1=x_order.index("missing") - 0.5,
            y0=-0.5,
            y1=len(y_order) - 0.5,
            line={"color": theme.FAINT, "width": 1, "dash": "3,4"},
            row=2,
            col=1,
        )
    if "missing" in y_order:
        figure.add_shape(
            type="line",
            x0=-0.5,
            x1=len(x_order) - 0.5,
            y0=y_order.index("missing") - 0.5,
            y1=y_order.index("missing") - 0.5,
            line={"color": theme.FAINT, "width": 1, "dash": "3,4"},
            row=2,
            col=1,
        )
    figure.update_xaxes(showticklabels=False, showgrid=False, row=1, col=1)
    figure.update_yaxes(title_text="tokens", showgrid=False, row=1, col=1, tickfont={"size": 9})
    figure.update_xaxes(title_text="Market cap region", tickangle=-25, showgrid=False, row=2, col=1)
    figure.update_yaxes(title_text="Liquidity region", showgrid=False, row=2, col=1)
    figure.update_xaxes(showticklabels=False, showgrid=False, row=2, col=2)
    figure.update_yaxes(showticklabels=False, showgrid=False, row=2, col=2)
    return figure


def transition_matrix_figure(flow: dict, limit: int = 14):
    import plotly.graph_objects as go

    source_rows = [row for row in flow["regions"] if row.get("left") or row.get("moves_out")][:limit]
    source_rows.sort(key=lambda row: (region_coords(row["region"]) is None, region_coords(row["region"]) or (0, 0)))
    sources = [row["region"] for row in source_rows]
    if not sources:
        return None

    relevant = [row for row in flow.get("transitions", []) if row.get("from_region") in sources]
    target_counts: Counter[str] = Counter()
    for row in relevant:
        target_counts[row.get("to_region") or "unknown"] += int(row.get("count") or 0)

    # Keep the matrix readable but preserve a 100% denominator: destinations
    # outside the visible top set are aggregated into OTHER; left_population is
    # always explicit because it is a real exit destination.
    ordinary_targets = [key for key, _count in target_counts.most_common(limit) if key != "left_population"]
    targets = ordinary_targets[:limit]
    if target_counts.get("left_population"):
        targets.append("left_population")
    hidden_targets = set(target_counts) - set(targets)
    if hidden_targets:
        targets.append("other_regions")

    source_index = {value: idx for idx, value in enumerate(sources)}
    target_index = {value: idx for idx, value in enumerate(targets)}
    z = [[0.0 for _ in targets] for _ in sources]
    counts = [[[0, ""] for _ in targets] for _ in sources]

    for row in relevant:
        source = row["from_region"]
        raw_target = row["to_region"]
        target = raw_target if raw_target in target_index else "other_regions"
        if source not in source_index or target not in target_index:
            continue
        i, j = source_index[source], target_index[target]
        z[i][j] += float(row.get("share_of_source_pct") or 0.0)
        counts[i][j][0] += int(row.get("count") or 0)
        classification = row.get("transition") or "unknown"
        if counts[i][j][1] and counts[i][j][1] != classification:
            counts[i][j][1] = "mixed destinations"
        else:
            counts[i][j][1] = classification

    def target_label(value: str) -> str:
        if value == "left_population":
            return "LEFT POPULATION"
        if value == "other_regions":
            return "OTHER REGIONS"
        return region_label(value)

    figure = go.Figure(
        go.Heatmap(
            x=[target_label(value) for value in targets],
            y=[region_label(value) for value in sources],
            z=z,
            customdata=counts,
            colorscale=theme.DENSITY_SCALE,
            colorbar={"title": {"text": "% of exits", "font": {"size": 10}}, "thickness": 11, "outlinewidth": 0},
            hovertemplate=(
                "From %{y}<br>To %{x}<br>%{customdata[0]:,} exits — "
                "%{z:.1f}% of source exits<br>classified: %{customdata[1]}<extra></extra>"
            ),
            xgap=2,
            ygap=2,
        )
    )
    figure.update_layout(margin={"l": 190, "r": 20, "t": 20, "b": 150})
    figure.update_xaxes(tickangle=-40, title_text="destination", showgrid=False)
    figure.update_yaxes(autorange="reversed", title_text="source", showgrid=False)
    return figure


def population_timeline_figure(flow: dict, limit: int = 8):
    import plotly.graph_objects as go

    timeline = flow.get("timeline", {})
    timestamps = timeline.get("timestamps", [])
    if len(timestamps) < 2:
        return None
    series = timeline.get("series", {})
    ranked = sorted(series.items(), key=lambda item: -sum(item[1]))[:limit]
    figure = go.Figure()
    for position, (region, values) in enumerate(ranked):
        figure.add_trace(
            go.Scatter(
                x=timestamps,
                y=values,
                name=region_label(region),
                mode="lines",
                stackgroup="population",
                line={"width": 0.8},
                hovertemplate="%{y:,} tokens<extra>" + region_label(region) + "</extra>",
            )
        )
    figure.update_layout(margin={"l": 70, "r": 20, "t": 44, "b": 40}, hovermode="x unified")
    figure.update_yaxes(title_text="tokens in region")
    return figure


def dwell_figure(flow: dict, limit: int = 12):
    import plotly.graph_objects as go

    rows = [row for row in flow["regions"] if row.get("median_dwell_upper_minutes") is not None]
    rows.sort(key=lambda row: -(row.get("dwell_samples") or 0))
    rows = rows[:limit]
    if not rows:
        return None
    rows.reverse()
    lower = [row.get("median_dwell_lower_minutes") or 0 for row in rows]
    upper = [row["median_dwell_upper_minutes"] for row in rows]
    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=lower,
            y=[region_label(row["region"]) for row in rows],
            orientation="h",
            name="certain",
            marker_color=theme.BLUE,
            hovertemplate="%{y}<br>at least %{x:.0f} min<extra></extra>",
        )
    )
    figure.add_trace(
        go.Bar(
            x=[max(high - low, 0) for high, low in zip(upper, lower)],
            y=[region_label(row["region"]) for row in rows],
            orientation="h",
            name="uncertain (between two polls)",
            marker_color="rgba(76,141,246,0.35)",
            customdata=[
                [row["dwell_samples"], row["median_dwell_upper_minutes"], row.get("dwell_censored_samples", 0)]
                for row in rows
            ],
            hovertemplate=(
                "%{y}<br>median dwell %{customdata[1]:.0f} min upper bound<br>"
                "%{customdata[0]:,} exact spells · %{customdata[2]:,} censored and excluded<extra></extra>"
            ),
        )
    )
    figure.update_layout(barmode="stack", margin={"l": 200, "r": 20, "t": 44, "b": 44})
    figure.update_xaxes(title_text="median dwell time (minutes, interval-censored)")
    return figure


def drift_figure(flow: dict, limit: int = 12):
    import plotly.graph_objects as go

    rows = [row for row in flow["regions"] if (row.get("moves_out") or 0) >= 5]
    rows.sort(key=lambda row: -(row.get("moves_out") or 0))
    rows = rows[:limit]
    if not rows:
        return None
    rows.reverse()
    labels = [region_label(row["region"]) for row in rows]
    figure = go.Figure()
    for name, color in (
        ("deteriorated", theme.ROSE),
        ("mixed", "#C58AA5"),
        ("same", theme.BLUE),
        ("improved", theme.TEAL),
        ("unknown", "#3A4557"),
    ):
        values = [(row["transition_pct"].get(name) or 0) for row in rows]
        if not any(values):
            continue
        figure.add_trace(
            go.Bar(
                x=values,
                y=labels,
                orientation="h",
                name=name,
                marker_color=color,
                customdata=[row["transition_counts"].get(name, 0) for row in rows],
                hovertemplate="%{y}<br>" + name + ": %{x:.1f}% (%{customdata:,} moves)<extra></extra>",
            )
        )
    figure.update_layout(
        barmode="stack",
        margin={"l": 200, "r": 20, "t": 44, "b": 44},
        legend={"traceorder": "normal"},
    )
    figure.update_xaxes(title_text="share of exits (%)", range=[0, 100])
    return figure


def cohort_outcome_figure(cohort: dict, outcome_keys: list[str]):
    import plotly.graph_objects as go

    rows = [row for row in cohort["outcomes"] if row["n"]]
    if not rows:
        return None
    labels = [f"+{row['horizon_minutes']}m" if row["horizon_minutes"] < 60 else f"+{row['horizon_minutes'] // 60}h" for row in rows]
    figure = go.Figure()
    for key in outcome_keys:
        figure.add_trace(
            go.Bar(
                x=[(row["pct"].get(key) or 0) for row in rows],
                y=labels,
                orientation="h",
                name=key,
                marker_color=theme.OUTCOME_COLORS.get(key, theme.MUTED),
                customdata=[row.get(key, 0) for row in rows],
                hovertemplate="%{y} · " + key + ": %{x:.1f}% (%{customdata:,})<extra></extra>",
            )
        )
    figure.update_layout(
        barmode="stack",
        margin={"l": 60, "r": 20, "t": 44, "b": 44},
        legend={"traceorder": "normal"},
    )
    figure.update_xaxes(title_text="share of matured cohort members (%)", range=[0, 100])
    figure.update_yaxes(autorange="reversed")
    return figure


def cohort_survival_figure(cohort: dict):
    import plotly.graph_objects as go

    rows = [row for row in cohort["survival"] if row["n"]]
    if not rows:
        return None
    figure = go.Figure(
        go.Scatter(
            x=[row["horizon_minutes"] for row in rows],
            y=[row["still_inside_pct"] for row in rows],
            mode="lines+markers",
            line={"color": theme.AMBER, "width": 2},
            marker={"size": 7},
            customdata=[row["n"] for row in rows],
            hovertemplate="+%{x} min<br>%{y:.1f}% still in entry region<br>n=%{customdata:,}<extra></extra>",
        )
    )
    figure.update_layout(margin={"l": 60, "r": 20, "t": 30, "b": 44})
    figure.update_xaxes(title_text="minutes after entry", type="log")
    figure.update_yaxes(title_text="still in entry region (%)", range=[0, 100])
    return figure


def activity_by_age_figure(snapshot: dict, rows: list[list]):
    import plotly.graph_objects as go

    age_order, age_labels = _dimension(snapshot, "age")
    activity_order = [key for key, _label in ACTIVITY_BUCKETS]
    counts = cross_tally(rows, "age_bucket", "activity_bucket")
    z = [
        [counts.get((age, activity), 0) for age in age_order]
        for activity in activity_order
    ]
    totals = [sum(counts.get((age, activity), 0) for activity in activity_order) for age in age_order]
    shares = [
        [
            (counts.get((age, activity), 0) / totals[position] * 100) if totals[position] else 0
            for position, age in enumerate(age_order)
        ]
        for activity in activity_order
    ]
    figure = go.Figure(
        go.Heatmap(
            x=[age_labels[key] for key in age_order],
            y=[dict(ACTIVITY_BUCKETS)[key] for key in activity_order],
            z=shares,
            customdata=z,
            colorscale=theme.SHARE_SCALE,
            colorbar={"title": {"text": "% of age", "font": {"size": 10}}, "thickness": 11, "outlinewidth": 0},
            hovertemplate="%{x} · %{y}<br>%{z:.1f}% of that age cohort<br>%{customdata:,} tokens<extra></extra>",
            xgap=2,
            ygap=2,
        )
    )
    figure.update_layout(margin={"l": 130, "r": 20, "t": 20, "b": 50})
    figure.update_xaxes(title_text="token age", showgrid=False)
    figure.update_yaxes(showgrid=False)
    return figure


def stacked_share_figure(snapshot: dict, rows: list[list], group_column: str, dimension: str, group_labels: dict[str, str] | None = None, limit: int = 10):
    import plotly.graph_objects as go

    stack_order, stack_labels = _dimension(snapshot, dimension)
    stack_column = {
        "activity": "activity_bucket",
        "age": "age_bucket",
        "holders": "holder_bucket",
        "mcap": "mcap_bucket",
        "liquidity": "liquidity_bucket",
    }[dimension]
    counts = cross_tally(rows, group_column, stack_column)
    group_totals: Counter = Counter()
    for (group, _stack), count in counts.items():
        group_totals[group] += count
    groups = [group for group, _count in group_totals.most_common(limit)]
    groups.reverse()
    labels = [(group_labels or {}).get(group, group) for group in groups]

    figure = go.Figure()
    for stack_key in stack_order:
        values = [
            counts.get((group, stack_key), 0) / group_totals[group] * 100 if group_totals[group] else 0
            for group in groups
        ]
        if not any(values):
            continue
        color = theme.ACTIVITY_COLORS.get(stack_key) if dimension == "activity" else None
        figure.add_trace(
            go.Bar(
                x=values,
                y=labels,
                orientation="h",
                name=stack_labels[stack_key],
                marker_color=color,
                customdata=[counts.get((group, stack_key), 0) for group in groups],
                hovertemplate="%{y}<br>" + stack_labels[stack_key] + ": %{x:.1f}% (%{customdata:,})<extra></extra>",
            )
        )
    figure.update_layout(barmode="stack", margin={"l": 150, "r": 20, "t": 44, "b": 44})
    figure.update_xaxes(title_text="share of group (%)", range=[0, 100])
    return figure


def launchpad_position_figure(snapshot: dict, rows: list[list], limit: int = 10):
    import plotly.graph_objects as go

    x_order, x_labels = _dimension(snapshot, "mcap")
    counts = cross_tally(rows, "launchpad", "mcap_bucket")
    totals: Counter = Counter()
    for (launchpad, _bucket), count in counts.items():
        totals[launchpad] += count
    launchpads = [name for name, _count in totals.most_common(limit)]
    z = [
        [
            counts.get((launchpad, bucket), 0) / totals[launchpad] * 100 if totals[launchpad] else 0
            for bucket in x_order
        ]
        for launchpad in launchpads
    ]
    raw = [[counts.get((launchpad, bucket), 0) for bucket in x_order] for launchpad in launchpads]
    figure = go.Figure(
        go.Heatmap(
            x=[x_labels[key] for key in x_order],
            y=[f"{name}  ({abbr(totals[name])})" for name in launchpads],
            z=z,
            customdata=raw,
            colorscale=theme.SHARE_SCALE,
            colorbar={"title": {"text": "% of launchpad", "font": {"size": 10}}, "thickness": 11, "outlinewidth": 0},
            hovertemplate="%{y}<br>%{x}: %{z:.1f}% (%{customdata:,} tokens)<extra></extra>",
            xgap=2,
            ygap=2,
        )
    )
    figure.update_layout(margin={"l": 170, "r": 20, "t": 20, "b": 60})
    figure.update_xaxes(tickangle=-25, showgrid=False)
    figure.update_yaxes(autorange="reversed", showgrid=False)
    return figure


def launchpad_rates_figure(rows: list[list], limit: int = 10):
    import plotly.graph_objects as go

    totals: Counter = Counter()
    graduated: Counter = Counter()
    dormant: Counter = Counter()
    retire: Counter = Counter()
    for row in rows:
        launchpad = row[IDX["launchpad"]]
        count = row[COUNT]
        totals[launchpad] += count
        if row[IDX["graduation"]] == "graduated":
            graduated[launchpad] += count
        if row[IDX["activity_bucket"]] == "dormant":
            dormant[launchpad] += count
        if row[IDX["policy_status"]] == "would_retire":
            retire[launchpad] += count

    launchpads = [name for name, _count in totals.most_common(limit)]
    launchpads.reverse()
    figure = go.Figure()
    for name, counter, color in (
        ("graduated", graduated, theme.VIOLET),
        ("dormant", dormant, theme.ROSE),
        ("would retire", retire, theme.AMBER),
    ):
        figure.add_trace(
            go.Bar(
                x=[counter[launchpad] / totals[launchpad] * 100 if totals[launchpad] else 0 for launchpad in launchpads],
                y=launchpads,
                orientation="h",
                name=name,
                marker_color=color,
                hovertemplate="%{y}<br>" + name + ": %{x:.1f}%<extra></extra>",
            )
        )
    figure.update_layout(barmode="group", margin={"l": 150, "r": 20, "t": 44, "b": 44})
    figure.update_xaxes(title_text="share of that launchpad's tracked tokens (%)")
    return figure


def policy_by_age_figure(snapshot: dict, rows: list[list]):
    import plotly.graph_objects as go

    age_order, age_labels = _dimension(snapshot, "age")
    counts = cross_tally(rows, "age_bucket", "policy_status")
    totals = {age: sum(counts.get((age, status), 0) for status in ("none", "probation", "would_retire")) for age in age_order}
    figure = go.Figure()
    for status, color in (("would_retire", theme.AMBER), ("probation", theme.BLUE)):
        figure.add_trace(
            go.Bar(
                x=[age_labels[age] for age in age_order],
                y=[counts.get((age, status), 0) for age in age_order],
                name=status,
                marker_color=color,
                customdata=[
                    counts.get((age, status), 0) / totals[age] * 100 if totals[age] else 0
                    for age in age_order
                ],
                hovertemplate="%{x} · " + status + ": %{y:,} (%{customdata:.1f}% of cohort)<extra></extra>",
            )
        )
    figure.update_layout(barmode="stack", margin={"l": 70, "r": 20, "t": 44, "b": 44})
    figure.update_yaxes(title_text="tokens in policy state")
    return figure


# --------------------------------------------------------------------------
# views
# --------------------------------------------------------------------------

def _region_readout(snapshot: dict, rows: list[list], region: str | None):
    from dash import html

    if not region:
        return card(
            "Region detail",
            html.Div(
                "Click a cell in the state space to pin a region. The pin stays "
                "active in every other view.",
                className="readout",
            ),
        )

    selected = filtered_rows(snapshot, {"region": region}, ignore=set())
    pinned_rows = [
        row
        for row in rows
        if region_id(row[IDX["mcap_bucket"]], row[IDX["liquidity_bucket"]]) == region
    ]
    count = total_of(pinned_rows)
    _age_order, age_labels = _dimension(snapshot, "age")
    _holder_order, holder_labels = _dimension(snapshot, "holders")
    activity_labels = dict(ACTIVITY_BUCKETS)

    return card(
        f"Pinned region · {region_label(region)}",
        html.Div(
            [
                html.Span(f"{fmt(count)} tokens under the current filters "),
                html.B(f"({pct(count, total_of(selected) or 1)} of the region)"),
            ],
            className="readout",
        ),
        html.Div(
            [
                html.Div(
                    [
                        html.P("Launchpad", className="card-title"),
                        bar_list(tally(pinned_rows, "launchpad").most_common(), theme.BLUE),
                    ]
                ),
                html.Div(
                    [
                        html.P("Age", className="card-title"),
                        bar_list(
                            [(age_labels.get(key, key), value) for key, value in tally(pinned_rows, "age_bucket").most_common()],
                            theme.VIOLET,
                        ),
                    ]
                ),
                html.Div(
                    [
                        html.P("Holders", className="card-title"),
                        bar_list(
                            [(holder_labels.get(key, key), value) for key, value in tally(pinned_rows, "holder_bucket").most_common()],
                            theme.TEAL,
                        ),
                    ]
                ),
                html.Div(
                    [
                        html.P("Activity", className="card-title"),
                        bar_list(
                            [(activity_labels.get(key, key), value) for key, value in tally(pinned_rows, "activity_bucket").most_common()],
                            theme.AMBER,
                        ),
                    ]
                ),
            ],
            className="grid cols-4",
            style={"marginTop": "10px"},
        ),
    )


def view_state(data: dict, filters: dict, mode: str):
    from dash import html

    snapshot = data["snapshot"]
    rows = filtered_rows(snapshot, filters)
    base_rows = filtered_rows(snapshot, filters, ignore={"policy"})
    tracked = snapshot["totals"]["tracked"]
    visible = total_of(rows)
    unknown = sum(
        row[COUNT]
        for row in rows
        if row[IDX["mcap_bucket"]] == "missing" or row[IDX["liquidity_bucket"]] == "missing"
    )
    retire = total_of([row for row in base_rows if row[IDX["policy_status"]] == "would_retire"])
    dead = total_of([row for row in rows if row[IDX["activity_bucket"]] == "dormant"])

    return [
        html.Div(
            [
                kpi("Tracked", fmt(tracked), "mints in the snapshot"),
                kpi("In filter", fmt(visible), f"{pct(visible, tracked)} of tracked", "k-teal"),
                kpi("Unknown mcap or liquidity", fmt(unknown), f"{pct(unknown, visible or 1)} of filtered — never counted as zero"),
                kpi("Would retire", fmt(retire), f"{pct(retire, total_of(base_rows) or 1)} of filtered", "k-amber"),
            ],
            className="grid cols-4",
            style={"marginBottom": "14px"},
        ),
        card(
            "Market cap × liquidity",
            graph(state_space_figure(snapshot, rows, mode, base_rows), height=620, element_id="state-space"),
            note=(
                "Colour scaling is logarithmic by default so the mass point does not erase everything else; "
                "cell labels and hover always show real token counts. Unknown is shown as its own row and column."
            ),
            flush=True,
        ),
        html.Div(style={"height": "14px"}),
        _region_readout(snapshot, rows, filters.get("region")),
        html.Div(style={"height": "14px"}),
        html.Div(
            [
                card(
                    "Activity by age",
                    graph(activity_by_age_figure(snapshot, rows), height=330),
                    note="Same filter, different question: how fast does this selection stop trading?",
                    flush=True,
                ),
                card(
                    "Holder regions",
                    graph(
                        stacked_share_figure(
                            snapshot,
                            rows,
                            "mcap_bucket",
                            "holders",
                            group_labels=MCAP_LABELS,
                            limit=8,
                        ),
                        height=330,
                    ),
                    note="Holder distribution inside each market-cap band.",
                    flush=True,
                ),
            ],
            className="grid cols-2",
        ),
    ]


def view_flow(data: dict, filters: dict):
    from dash import html

    flow = data.get("flow")
    if not flow:
        return [
            empty_state(
                "No flow data yet.",
                "Phase 2 needs at least two runs. Start the monitor with ",
                html.Code("python diagnose_inactivity.py --monitor"),
                " and come back in an hour — region_flow.json is written on every cycle.",
            )
        ]

    coverage = flow.get("coverage", {})
    totals = flow.get("totals", {})
    banner = [filters_not_applied("region", "launchpad")]
    if coverage.get("legacy_events_ignored"):
        banner.append(
            empty_state(
                "Legacy events skipped.",
                f"{coverage['legacy_events_ignored']:,} rows were written by the previous "
                "event logger and are ignored — that format double-counted returns and "
                "carried no source attributes.",
            )
        )
        banner.append(html.Div(style={"height": "14px"}))
    if not coverage.get("sufficient_for_transitions"):
        banner.append(
            empty_state(
                "Thin history — read these numbers as a sanity check, not as evidence.",
                f"{coverage.get('monitor_runs', 0)} monitor runs, "
                f"{coverage.get('moves_in_window', 0):,} region changes across "
                f"{coverage.get('mints_with_incident_moves', 0):,} distinct mints in the last "
                f"{flow.get('window_hours')} h.",
            )
        )
        banner.append(html.Div(style={"height": "14px"}))

    classes = totals.get("transitions", {})
    improved = classes.get("improved", 0)
    deteriorated = classes.get("deteriorated", 0)
    mixed = classes.get("mixed", 0)
    children = banner + [
        html.Div(
            [
                kpi("Observation", f"{coverage.get('observation_hours') or 0:.1f} h", f"{coverage.get('monitor_runs', 0)} monitor runs"),
                kpi("Region changes", fmt(totals.get("moves")), f"last {flow.get('window_hours')} h"),
                kpi(
                    "Median dwell",
                    f"{totals.get('median_dwell_upper_minutes') or 0:.0f} min",
                    f"{fmt(totals.get('dwell_samples'))} exact · {fmt(totals.get('dwell_censored_samples'))} censored",
                ),
                kpi(
                    "Drift",
                    f"{improved / (improved + deteriorated) * 100:.0f}% up" if (improved + deteriorated) else "—",
                    f"{fmt(improved)} improved · {fmt(mixed)} mixed · {fmt(deteriorated)} deteriorated",
                    "k-teal" if improved >= deteriorated else "k-rose",
                ),
            ],
            className="grid cols-4",
            style={"marginBottom": "14px"},
        )
    ]

    matrix = transition_matrix_figure(flow)
    if matrix is not None:
        children.append(
            card(
                "Transition matrix",
                graph(matrix, height=560),
                note="Row = source region, column = observed destination. LEFT POPULATION is an explicit destination, so source-exit shares keep the correct denominator; OTHER REGIONS aggregates destinations hidden only for readability. Graduation is not a destination because it changes an attribute, not the economic region.",
                flush=True,
            )
        )
        children.append(html.Div(style={"height": "14px"}))

    timeline = population_timeline_figure(flow)
    if timeline is not None:
        children.append(
            card(
                "Population through time",
                graph(timeline, height=380),
                note="Stacked occupancy of the busiest regions per monitor run.",
                flush=True,
            )
        )
        children.append(html.Div(style={"height": "14px"}))

    dwell = dwell_figure(flow)
    drift = drift_figure(flow)
    pair = []
    if dwell is not None:
        pair.append(
            card(
                "Dwell time",
                graph(dwell, height=420),
                note="A change is only observed at the next poll, so the true dwell lies between the two bars. Spells interrupted by an observation gap are excluded, not estimated.",
                flush=True,
            )
        )
    if drift is not None:
        pair.append(
            card(
                "Direction of exits",
                graph(drift, height=420),
                note="Market cap and liquidity are compared separately: improved means neither got worse and at least one got better. Mixed is the interesting case — one up, one down.",
                flush=True,
            )
        )
    if pair:
        children.append(html.Div(pair, className="grid cols-2"))
    return children


def view_cohorts(data: dict, filters: dict, selected: str | None):
    from dash import dcc, html

    outcomes = data.get("cohorts")
    if not outcomes:
        return [
            empty_state(
                "No cohort evidence yet.",
                "Phase 3 replays the Phase-2 event log, so it needs that log to exist first. Run ",
                html.Code("python diagnose_inactivity.py --monitor"),
                " for a few hours.",
            )
        ]

    cohorts = outcomes["cohorts"]
    keys = [cohort["key"] for cohort in cohorts]
    current = selected if selected in keys else keys[0]
    cohort = next(item for item in cohorts if item["key"] == current)
    matured = max((row["n"] for row in cohort["outcomes"]), default=0)

    children = [
        filters_not_applied(),
        html.Div(
            [
                dcc.Dropdown(
                    id="cohort-select",
                    options=[{"label": item["label"], "value": item["key"]} for item in cohorts],
                    value=current,
                    clearable=False,
                    style={"maxWidth": "460px"},
                )
            ],
            style={"marginBottom": "14px"},
        ),
        html.Div(
            [
                kpi(
                    "Incident mints",
                    fmt(cohort["unique_mints"]),
                    f"{fmt(cohort['episodes_total'])} incident episodes",
                ),
                kpi(
                    "Baseline observed",
                    fmt(cohort.get("baseline_unique_mints", 0)),
                    "prevalent first observations — excluded from outcome rates",
                ),
                kpi("Matured", fmt(matured), "first incident entries with continuous horizon coverage", "k-teal" if matured else ""),
                kpi(
                    "Still inside at +1h",
                    next(
                        (f"{row['still_inside_pct']:.0f}%" for row in cohort["survival"] if row["horizon_minutes"] == 60 and row["still_inside_pct"] is not None),
                        "—",
                    ),
                    "share that has not moved region",
                    "k-amber",
                ),
            ],
            className="grid cols-4",
            style={"marginBottom": "14px"},
        ),
        card("Definition", html.Div(cohort["description"], className="readout")),
        html.Div(style={"height": "14px"}),
    ]

    outcome_figure = cohort_outcome_figure(cohort, outcomes["outcome_keys"])
    if outcome_figure is None:
        children.append(
            empty_state(
                "No horizon has matured yet for this cohort.",
                "The first entries need to be older than the shortest horizon (+30 min).",
            )
        )
        return children

    children.append(
        card(
            "Outcome by horizon",
            graph(outcome_figure, height=380),
            note="Counted once per mint from the first incident entry only. Prevalent baseline observations and censored re-entries are excluded. Each horizon is scored only when its concrete observation interval is continuous; interval-censored graduation crossing a boundary is shown as graduation_uncertain.",
            flush=True,
        )
    )
    children.append(html.Div(style={"height": "14px"}))

    survival = cohort_survival_figure(cohort)
    destinations = cohort["top_destinations"]
    episode_matured = max((row["n"] for row in cohort["episode_outcomes"]), default=0)
    pair = []
    if survival is not None:
        pair.append(card("Escape curve", graph(survival, height=360), note="Share of members that have not left the entry region yet.", flush=True))
    pair.append(
        card(
            "Where they go next",
            bar_list([(row["label"], row["count"]) for row in destinations], theme.BLUE, limit=10),
            note="First region entered after leaving.",
        )
    )
    children.append(html.Div(pair, className="grid cols-2"))
    if episode_matured and episode_matured != matured:
        first_improved = next((row["pct"].get("improved") for row in cohort["outcomes"] if row["n"]), None)
        episode_improved = next((row["pct"].get("improved") for row in cohort["episode_outcomes"] if row["n"]), None)
        children.append(html.Div(style={"height": "14px"}))
        children.append(
            card(
                "Counting check",
                html.Div(
                    [
                        html.Span("At the shortest matured horizon: "),
                        html.B(f"{first_improved:.1f}% improved" if first_improved is not None else "—"),
                        html.Span(" counted once per mint, "),
                        html.B(f"{episode_improved:.1f}%" if episode_improved is not None else "—"),
                        html.Span(
                            f" counted per episode ({fmt(episode_matured)} episodes vs {fmt(matured)} mints). "
                            "A large gap means a few tokens oscillate in and out and would otherwise dominate."
                        ),
                    ],
                    className="readout",
                ),
            )
        )
    return children


def view_activity(data: dict, filters: dict):
    from dash import html

    snapshot = data["snapshot"]
    rows = filtered_rows(snapshot, filters)
    counts = tally(rows, "activity_bucket")
    visible = total_of(rows) or 1
    labels = dict(ACTIVITY_BUCKETS)

    return [
        html.Div(
            [
                kpi("Hot + active", fmt(counts["hot"] + counts["active"]), pct(counts["hot"] + counts["active"], visible) + " of filtered", "k-teal"),
                kpi("Low", fmt(counts["low"]), pct(counts["low"], visible) + " of filtered"),
                kpi("Idle", fmt(counts["idle"]), "no trades in the last hour"),
                kpi("Dormant", fmt(counts["dormant"]), "no trades for 1h and stale 30m+", "k-rose"),
            ],
            className="grid cols-4",
            style={"marginBottom": "14px"},
        ),
        card(
            "Activity by age",
            graph(activity_by_age_figure(snapshot, rows), height=340),
            note="Colour is the share within each age cohort, so young and old cohorts stay comparable even though they differ in size.",
            flush=True,
        ),
        html.Div(style={"height": "14px"}),
        html.Div(
            [
                card(
                    "Activity by market-cap region",
                    graph(stacked_share_figure(snapshot, rows, "mcap_bucket", "activity", group_labels=MCAP_LABELS, limit=8), height=400),
                    note="Does a higher valuation actually come with trading?",
                    flush=True,
                ),
                card(
                    "Activity by liquidity region",
                    graph(stacked_share_figure(snapshot, rows, "liquidity_bucket", "activity", group_labels=LIQUIDITY_LABELS, limit=8), height=400),
                    note="Liquidity without trades is the pattern worth naming.",
                    flush=True,
                ),
            ],
            className="grid cols-2",
        ),
        html.Div(style={"height": "14px"}),
        card(
            "Reading",
            html.Div(
                [
                    html.Span("Activity is derived from stats1h buys and sells plus the unchanged interval: "),
                    html.B("dormant"),
                    html.Span(" = no trades for an hour and no field change for 30 minutes. "),
                    html.Span(
                        "Deliberately not called dead: it is an observation, not a proven end state. "
                        "Phase 3 has to show what actually follows it."
                    ),
                ],
                className="readout",
            ),
        ),
    ]


def view_origin(data: dict, filters: dict):
    from dash import html

    snapshot = data["snapshot"]
    rows = filtered_rows(snapshot, filters)
    totals = tally(rows, "launchpad")
    graduated = total_of([row for row in rows if row[IDX["graduation"]] == "graduated"])
    visible = total_of(rows) or 1
    flow = data.get("flow") or {}
    by_launchpad = flow.get("by_launchpad", [])

    children = [
        html.Div(
            [
                kpi("Launchpads", fmt(len(totals)), "distinct origins in filter"),
                kpi("Largest origin", (totals.most_common(1)[0][0] if totals else "—"), pct(totals.most_common(1)[0][1], visible) + " of filtered" if totals else ""),
                kpi("Graduated", fmt(graduated), pct(graduated, visible) + " of filtered", "k-violet"),
                kpi("Unknown origin", fmt(totals.get("unknown", 0)), pct(totals.get("unknown", 0), visible) + " of filtered"),
            ],
            className="grid cols-4",
            style={"marginBottom": "14px"},
        ),
        card(
            "Where each launchpad's population sits",
            graph(launchpad_position_figure(snapshot, rows), height=420),
            note="Rows are normalised: each launchpad is compared by shape, not by size.",
            flush=True,
        ),
        html.Div(style={"height": "14px"}),
        card(
            "Graduation, dormancy and retirement rate",
            graph(launchpad_rates_figure(rows), height=400),
            note="Three outcome rates per origin, on the same scale.",
            flush=True,
        ),
    ]

    if by_launchpad:
        children.append(html.Div(style={"height": "14px"}))
        children.append(
            card(
                "Movement by origin (last window)",
                bar_list(
                    [(row["launchpad"], int(row.get("moves", 0))) for row in by_launchpad],
                    theme.BLUE,
                    limit=10,
                ),
                note="Region changes observed per launchpad since the monitor started.",
            )
        )

    children.append(html.Div(style={"height": "14px"}))
    children.append(
        card(
            "Not available yet",
            html.Div(
                "Developer priors (Phase 5, second half) need the creator wallet on the "
                "feature row. The collector does not deliver it today, so it is left out "
                "rather than approximated.",
                className="readout",
            ),
        )
    )
    return children


def view_policy(data: dict, filters: dict):
    from dash import dash_table, html

    snapshot = data["snapshot"]
    report = data.get("report") or {}
    rows = filtered_rows(snapshot, filters, ignore={"policy"})
    retire_rows = [row for row in rows if row[IDX["policy_status"]] == "would_retire"]
    demote_rows = [row for row in rows if row[IDX["policy_status"]] == "would_demote"]
    probation_rows = [row for row in rows if row[IDX["policy_status"]] == "probation"]
    visible = total_of(rows) or 1
    retire = total_of(retire_rows)

    simulation = (report.get("policy_simulation") or {}).get("rules", [])
    overlay = ((report.get("population_distribution") or {}).get("policy_overlay") or {})
    rule_rows = []
    overlay_by_rule = {row["rule_id"]: row["would_retire_count"] for row in overlay.get("rules", [])}
    state_by_rule = {
        row.get("rule_id"): row
        for row in ((report.get("filter_evidence") or {}).get("rules") or [])
    }
    for rule in simulation:
        state_row = state_by_rule.get(rule.get("rule_id")) or {}
        rule_rows.append(
            {
                "rule": rule.get("rule_id"),
                "matches": rule.get("current_match_count"),
                "would_retire": state_row.get(
                    "applied_count",
                    overlay_by_rule.get(rule.get("rule_id"), 0),
                ),
            }
        )

    children = [
        html.Div(
            [
                kpi("Would retire", fmt(retire), pct(retire, visible) + " of filtered", "k-amber"),
                kpi("Would demote", fmt(total_of(demote_rows)), "P2 or P3 recommendation"),
                kpi("Probation", fmt(total_of(probation_rows)), "waiting for persistence"),
                kpi(
                    "Candidates < 3h old",
                    fmt(total_of([row for row in retire_rows if row[IDX["age_bucket"]] in {"under_30m", "30_60m", "1_3h"}])),
                    "young candidates deserve scrutiny",
                    "k-rose",
                ),
            ],
            className="grid cols-4",
            style={"marginBottom": "14px"},
        ),
        card(
            "Candidates by age",
            graph(policy_by_age_figure(snapshot, rows), height=340),
            note="If candidates cluster in young cohorts, the rule is probably too fast.",
            flush=True,
        ),
    ]

    if rule_rows:
        children.append(html.Div(style={"height": "14px"}))
        children.append(
            card(
                "Rules in the current simulation",
                dash_table.DataTable(
                    columns=[
                        {"name": "Rule", "id": "rule"},
                        {"name": "Matching now", "id": "matches", "type": "numeric"},
                        {"name": "Applied", "id": "would_retire", "type": "numeric"},
                    ],
                    data=rule_rows,
                    style_as_list_view=True,
                    style_header={
                        "backgroundColor": "transparent",
                        "color": theme.MUTED,
                        "fontFamily": theme.FONT_UI,
                        "fontSize": "11px",
                        "textTransform": "uppercase",
                        "letterSpacing": "0.1em",
                        "border": "none",
                        "borderBottom": f"1px solid {theme.LINE}",
                    },
                    style_cell={
                        "backgroundColor": "transparent",
                        "color": theme.TEXT,
                        "fontFamily": theme.FONT_MONO,
                        "fontSize": "12px",
                        "textAlign": "left",
                        "padding": "8px 6px",
                        "border": "none",
                        "borderBottom": f"1px solid rgba(36,47,65,0.5)",
                    },
                ),
                note="Read from investigation_report.json — no rule is evaluated in the dashboard itself.",
            )
        )

    policy_outcomes = data.get("policy_outcomes") or {}
    if policy_outcomes.get("rules"):
        children.append(html.Div(style={"height": "14px"}))
        global_outcomes = policy_outcomes.get("global") or {}
        children.append(
            html.Div(
                [
                    kpi(
                        "Unique action union",
                        fmt(global_outcomes.get("applied_unique_union")),
                        "demote or retire",
                        "k-amber",
                    ),
                    kpi(
                        "Retire union",
                        fmt(global_outcomes.get("would_retire_unique_union")),
                        "unique retirement candidates",
                    ),
                    kpi(
                        "Healthy outcome runs",
                        fmt((policy_outcomes.get("coverage") or {}).get("healthy_monitor_runs")),
                        "used for maturity / gap checks",
                    ),
                    kpi(
                        "Outcome artifact",
                        "Maturity-safe",
                        "rates exclude immature and gap-crossing cases",
                        "k-teal",
                    ),
                ],
                className="grid cols-4",
                style={"marginBottom": "14px"},
            )
        )

        horizon_labels = {5: "5m", 15: "15m", 30: "30m", 60: "1h", 360: "6h", 1440: "24h"}
        outcome_rows = []
        horizons_seen = set()
        for rule in policy_outcomes["rules"]:
            row = {
                "rule": rule.get("rule_id"),
                "action": rule.get("action"),
                "unique": rule.get("applied_unique_mints"),
                "episodes": rule.get("applied_episodes"),
            }
            for horizon in rule.get("horizons", []):
                minutes = int(horizon.get("horizon_minutes") or 0)
                label = horizon_labels.get(minutes, f"{minutes}m")
                horizons_seen.add(label)
                rate = horizon.get("recovery_rate_pct")
                matured_count = horizon.get("matured") or 0
                row[label] = "—" if rate is None else f"{rate:.2f}% ({matured_count:,})"
                relevant_rate = horizon.get("reached_50k_rate_pct")
                row[f"{label}_50k"] = "—" if relevant_rate is None else f"{relevant_rate:.2f}%"
            outcome_rows.append(row)

        ordered_horizons = [label for label in ("5m", "15m", "30m", "1h", "6h", "24h") if label in horizons_seen]
        children.append(
            card(
                "Rule outcomes — first applied action per mint",
                dash_table.DataTable(
                    columns=[
                        {"name": "Rule", "id": "rule"},
                        {"name": "Action", "id": "action"},
                        {"name": "Unique mints", "id": "unique"},
                        {"name": "Episodes", "id": "episodes"},
                    ] + [item for label in ordered_horizons for item in (
                        {"name": f"Recovered {label}", "id": label},
                        {"name": f">=50k {label}", "id": f"{label}_50k"},
                    )],
                    data=outcome_rows,
                    style_as_list_view=True,
                    style_header={
                        "backgroundColor": "transparent",
                        "color": theme.MUTED,
                        "fontFamily": theme.FONT_UI,
                        "fontSize": "11px",
                        "textTransform": "uppercase",
                        "letterSpacing": "0.08em",
                        "border": "none",
                        "borderBottom": f"1px solid {theme.LINE}",
                    },
                    style_cell={
                        "backgroundColor": "transparent",
                        "color": theme.TEXT,
                        "fontFamily": theme.FONT_MONO,
                        "fontSize": "12px",
                        "textAlign": "left",
                        "padding": "8px 6px",
                        "border": "none",
                        "borderBottom": "1px solid rgba(36,47,65,0.5)",
                    },
                ),
                note="Recovery rate denominator contains only unique candidates whose concrete horizon was mature and continuously observed. The number in parentheses is that matured denominator; observation gaps and not-yet-mature candidates are excluded.",
            )
        )

    cohorts = data.get("cohorts")
    if cohorts and cohorts.get("coverage", {}).get("has_matured_outcomes"):
        recoveries = [
            {
                "cohort": cohort["label"],
                "improved": next((row["pct"].get("improved") for row in cohort["outcomes"] if row["n"]), None),
                "graduated": next((row["pct"].get("graduated") for row in cohort["outcomes"] if row["n"]), None),
            }
            for cohort in cohorts["cohorts"]
        ]
        recovered = [row for row in recoveries if (row["improved"] or 0) > 0]
        if recovered:
            children.append(html.Div(style={"height": "14px"}))
            children.append(
                card(
                    "Recovery signal from Phase 3",
                    bar_list([(row["cohort"], round(row["improved"] or 0)) for row in recovered], theme.TEAL, limit=8),
                    note="Share of each cohort that improved at the shortest matured horizon, counted once per mint. This is a population signal, not a rule validation — per-rule RECOVERED/STAYED_DEAD outcomes still have to come from decision_events.jsonl.",
                )
            )

    return children


def view_filter_evidence(data: dict, filters: dict):
    """Operational Phase 6: concrete allocations, rules and token evidence."""
    from dash import dash_table, html

    evidence = ((data.get("report") or {}).get("filter_evidence") or {})
    allocation = evidence.get("allocation") or {}
    allocation_pct = evidence.get("allocation_pct") or {}
    cadences = evidence.get("priority_cadences_seconds") or {}
    total = evidence.get("total_active") or sum(allocation.values())

    children = [
        filters_not_applied(),
        html.Div(
            [
                kpi("P1", fmt(allocation.get("p1", 0)), f"{allocation_pct.get('p1', 0):.1f}% · every {cadences.get('p1', 60)}s"),
                kpi("P2", fmt(allocation.get("p2", 0)), f"{allocation_pct.get('p2', 0):.1f}% · every {cadences.get('p2', 300)}s"),
                kpi("P3", fmt(allocation.get("p3", 0)), f"{allocation_pct.get('p3', 0):.1f}% · every {cadences.get('p3', 3600)}s", "k-amber"),
                kpi("Retired", fmt(allocation.get("retire", 0)), f"{allocation_pct.get('retire', 0):.1f}% · no individual polling", "k-rose"),
            ],
            className="grid cols-4",
            style={"marginBottom": "14px"},
        ),
        card(
            "What removes polling load",
            bar_list(
                [(row.get("rule_id", "unknown"), int(row.get("count") or 0)) for row in evidence.get("reason_counts", [])],
                theme.ROSE,
                limit=12,
            ),
            note=f"Shadow recommendations over {fmt(total)} active tokens. No database flag is changed.",
        ),
        html.Div(style={"height": "14px"}),
    ]

    rules = []
    for row in evidence.get("rules", []):
        rules.append({
            "rule": row.get("rule_id"),
            "action": row.get("action"),
            "confirmation": row.get("confirmation"),
            "matches": row.get("current_match_count"),
            "probation": row.get("probation_count"),
            "applied": row.get("applied_count"),
            "polls": row.get("min_poll_confirmations"),
            "minutes": row.get("persistence_minutes"),
        })
    if rules:
        children.append(card(
            "Rule decision matrix",
            dash_table.DataTable(
                columns=[
                    {"name": "Rule", "id": "rule"}, {"name": "Action", "id": "action"},
                    {"name": "Confirmation", "id": "confirmation"}, {"name": "Matches", "id": "matches"},
                    {"name": "Probation", "id": "probation"}, {"name": "Applied", "id": "applied"},
                    {"name": "Polls", "id": "polls"}, {"name": "Persist min", "id": "minutes"},
                ],
                data=rules,
                style_as_list_view=True,
                style_header={"backgroundColor": "transparent", "color": theme.MUTED, "border": "none", "borderBottom": f"1px solid {theme.LINE}"},
                style_cell={"backgroundColor": "transparent", "color": theme.TEXT, "fontFamily": theme.FONT_MONO, "fontSize": "12px", "textAlign": "left", "padding": "8px 6px", "border": "none", "borderBottom": "1px solid rgba(36,47,65,0.5)"},
            ),
            note="Poll-confirmed means last_polled_at must advance for that mint; a second payload snapshot is not required.",
        ))

    samples = []
    for row in evidence.get("candidate_samples", []):
        ev = row.get("evidence") or {}
        sample_rules = row.get("rules") or (
            [row.get("rule_id")] if row.get("rule_id") else []
        )
        samples.append({
            "mint": row.get("mint"), "token": row.get("symbol") or ev.get("symbol") or row.get("name") or ev.get("name"),
            "priority": row.get("recommended_priority") or row.get("action"),
            "rules": ", ".join(sample_rules),
            "age_min": ev.get("age_minutes"), "mcap": ev.get("mcap"), "peak_mcap": ev.get("peak_mcap"),
            "liquidity": ev.get("liquidity"), "holders": ev.get("holders"),
            "5m_buys": ev.get("stats5m_num_buys"), "gmgn": "yes" if ev.get("gmgn_available") else "no",
            "gmgn_rug": ev.get("gmgn_rug_ratio"),
        })
    if samples:
        children.extend([
            html.Div(style={"height": "14px"}),
            card(
                "Concrete token evidence",
                dash_table.DataTable(
                    columns=[{"name": key.replace("_", " ").title(), "id": key} for key in samples[0]],
                    data=samples,
                    page_size=15,
                    style_table={"overflowX": "auto"},
                    style_header={"backgroundColor": "transparent", "color": theme.MUTED, "border": "none", "borderBottom": f"1px solid {theme.LINE}"},
                    style_cell={"backgroundColor": "transparent", "color": theme.TEXT, "fontFamily": theme.FONT_MONO, "fontSize": "11px", "textAlign": "left", "maxWidth": "240px", "overflow": "hidden", "textOverflow": "ellipsis", "padding": "7px 5px", "border": "none"},
                ),
                note="Compact evidence only. The diagnostics does not export full per-token histories, so 23,000 tokens do not become a multi-gigabyte JSON file.",
            ),
        ])
    return children


# --------------------------------------------------------------------------
# app
# --------------------------------------------------------------------------

def create_app(snapshot_path: Path = REGION_SNAPSHOT_PATH):
    try:
        from dash import ALL, Dash, Input, Output, State, callback, ctx, dcc, html
    except ImportError as exc:  # pragma: no cover - import guard
        raise SystemExit(
            "Dashboard-Abhängigkeiten fehlen. Installiere: python -m pip install dash plotly"
        ) from exc

    theme.register_template()
    data = load_artifacts(snapshot_path)
    snapshot = data["snapshot"]

    app = Dash(__name__, suppress_callback_exceptions=True, title="Jupiter state space")
    app.index_string = theme.index_html()

    def dimension_options(dimension: str) -> list[dict]:
        return [
            {"label": row["label"], "value": row["key"]}
            for row in snapshot["dimensions"][dimension]
        ]

    def launchpad_options() -> list[dict]:
        return [
            {"label": f"{name} · {abbr(count)}", "value": name}
            for name, count in sorted(
                snapshot.get("breakdowns", {}).get("launchpad", {}).items(),
                key=lambda row: (-row[1], row[0]),
            )
        ]

    def field(label: str, component):
        return html.Div([html.Label(label), component], className="field")

    rail = html.Div(
        [
            html.Div(
                [
                    html.Div("Jupiter", className="brand-mark"),
                    html.Div("token state space", className="brand-sub"),
                ],
                className="brand",
            ),
            html.Div(
                [html.P("Views", className="eyebrow")]
                + [
                    html.Button(
                        [html.Span(name), html.Span(f"P{phase}", className="phase")],
                        id={"type": "nav", "view": key},
                        className="nav-item",
                        n_clicks=0,
                        title=hint,
                    )
                    for key, phase, name, hint in VIEWS
                ],
                className="rail-group",
            ),
            html.Div(
                [
                    html.P("Filter", className="eyebrow"),
                    field("Launchpad", dcc.Dropdown(id="f-launchpad", options=launchpad_options(), multi=True, placeholder="all")),
                    field(
                        "Graduation",
                        dcc.Dropdown(
                            id="f-graduation",
                            options=[
                                {"label": "All", "value": "all"},
                                {"label": "Not graduated", "value": "not_graduated"},
                                {"label": "Graduated", "value": "graduated"},
                            ],
                            value="all",
                            clearable=False,
                        ),
                    ),
                    field("Age", dcc.Dropdown(id="f-age", options=dimension_options("age"), multi=True, placeholder="all")),
                    field("Holders", dcc.Dropdown(id="f-holders", options=dimension_options("holders"), multi=True, placeholder="all")),
                    field("Activity", dcc.Dropdown(id="f-activity", options=dimension_options("activity"), multi=True, placeholder="all")),
                    field("Market cap", dcc.Dropdown(id="f-mcap", options=dimension_options("mcap"), multi=True, placeholder="all")),
                    field("Liquidity", dcc.Dropdown(id="f-liquidity", options=dimension_options("liquidity"), multi=True, placeholder="all")),
                    field(
                        "Policy state",
                        dcc.Dropdown(
                            id="f-policy",
                            options=[{"label": "All", "value": "all"}] + dimension_options("policy"),
                            value="all",
                            clearable=False,
                        ),
                    ),
                ],
                className="rail-group",
            ),
            html.Div(
                [
                    html.P("Snapshot", className="eyebrow"),
                    html.Button("Reload artifacts", id="reload", className="action", n_clicks=0, style={"width": "100%", "marginBottom": "8px"}),
                    html.Button("Export filtered CSV", id="export", className="action", n_clicks=0, style={"width": "100%"}),
                    dcc.Download(id="download"),
                ],
                className="rail-group",
            ),
        ],
        className="rail",
    )

    main = html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.H1(id="view-title"),
                            html.P(id="view-lede", className="lede"),
                        ]
                    ),
                    html.Div(id="stamp", className="stamp"),
                ],
                className="head",
            ),
            html.Div(
                [
                    html.Button(
                        preset["label"],
                        id={"type": "preset", "key": preset["key"]},
                        className="chip",
                        n_clicks=0,
                    )
                    for preset in PRESETS
                ]
                + [
                    html.Button(
                        "",
                        id="unpin",
                        className="chip is-on",
                        n_clicks=0,
                        title="Unpin this region",
                        style={"display": "none"},
                    ),
                    html.Div(style={"flex": "1 1 auto"}),
                ]
                + [
                    html.Button(
                        label,
                        id={"type": "mode", "key": key},
                        className="chip",
                        n_clicks=0,
                        style={"display": "none"},
                    )
                    for key, label in MODES
                ],
                className="chips",
            ),
            html.Div(id="view-body"),
        ],
        className="main",
    )

    app.layout = html.Div(
        [
            dcc.Store(id="store-data", data=data),
            dcc.Store(id="store-view", data="state"),
            dcc.Store(id="store-region", data=None),
            dcc.Store(id="store-mode", data="log"),
            dcc.Store(id="store-cohort", data=None),
            rail,
            main,
        ],
        className="shell",
    )

    # -- navigation --------------------------------------------------------
    @callback(
        Output("store-view", "data"),
        Input({"type": "nav", "view": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def switch_view(_clicks):
        triggered = ctx.triggered_id
        if not triggered:
            return "state"
        return triggered["view"]

    @callback(
        Output({"type": "nav", "view": ALL}, "className"),
        Input("store-view", "data"),
    )
    def highlight_nav(view):
        return [
            "nav-item is-active" if key == view else "nav-item"
            for key, _phase, _name, _hint in VIEWS
        ]

    @callback(
        Output("view-title", "children"),
        Output("view-lede", "children"),
        Input("store-view", "data"),
    )
    def view_header(view):
        for key, phase, name, hint in VIEWS:
            if key == view:
                return name, f"Phase {phase} — {hint}."
        return "State space", ""

    # -- filters -----------------------------------------------------------
    @callback(
        Output("f-launchpad", "value"),
        Output("f-graduation", "value"),
        Output("f-age", "value"),
        Output("f-holders", "value"),
        Output("f-activity", "value"),
        Output("f-mcap", "value"),
        Output("f-liquidity", "value"),
        Output("f-policy", "value"),
        Output("store-region", "data", allow_duplicate=True),
        Input({"type": "preset", "key": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def apply_preset(_clicks):
        triggered = ctx.triggered_id
        preset = next((item for item in PRESETS if item["key"] == triggered["key"]), None)
        values = (preset or {}).get("filters", {})
        return (
            values.get("launchpad"),
            values.get("graduation", "all"),
            values.get("age"),
            values.get("holders"),
            values.get("activity"),
            values.get("mcap"),
            values.get("liquidity"),
            values.get("policy", "all"),
            None,
        )

    @callback(
        Output({"type": "preset", "key": ALL}, "className"),
        Input("f-launchpad", "value"),
        Input("f-graduation", "value"),
        Input("f-age", "value"),
        Input("f-holders", "value"),
        Input("f-activity", "value"),
        Input("f-mcap", "value"),
        Input("f-liquidity", "value"),
        Input("f-policy", "value"),
    )
    def highlight_presets(launchpad, graduation, age, holders, activity, mcap, liquidity, policy):
        current = {
            "launchpad": launchpad,
            "graduation": graduation,
            "age": age,
            "holders": holders,
            "activity": activity,
            "mcap": mcap,
            "liquidity": liquidity,
            "policy": policy,
        }

        def matches(preset):
            wanted = preset["filters"]
            for key in FILTER_FIELDS:
                value = current.get(key)
                if key in {"graduation", "policy"}:
                    if (value or "all") != wanted.get(key, "all"):
                        return False
                elif sorted(value or []) != sorted(wanted.get(key) or []):
                    return False
            return True

        return ["chip is-on" if matches(preset) else "chip" for preset in PRESETS]

    @callback(
        Output({"type": "mode", "key": ALL}, "className"),
        Output({"type": "mode", "key": ALL}, "style"),
        Input("store-mode", "data"),
        Input("store-view", "data"),
    )
    def highlight_modes(mode, view):
        visible = {} if view == "state" else {"display": "none"}
        return (
            ["chip is-on" if key == mode else "chip" for key, _label in MODES],
            [visible for _key, _label in MODES],
        )

    @callback(
        Output("unpin", "children"),
        Output("unpin", "style"),
        Input("store-region", "data"),
    )
    def show_pin(region):
        if not region:
            return "", {"display": "none"}
        return f"◈ {region_label(region)}  ✕", {}

    @callback(
        Output("store-mode", "data"),
        Input({"type": "mode", "key": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def set_mode(_clicks):
        triggered = ctx.triggered_id
        return triggered["key"] if isinstance(triggered, dict) else "log"

    @callback(
        Output("store-region", "data", allow_duplicate=True),
        Input("unpin", "n_clicks"),
        prevent_initial_call=True,
    )
    def unpin_region(_clicks):
        return None

    @callback(
        Output("store-region", "data", allow_duplicate=True),
        Input("state-space", "clickData"),
        State("store-region", "data"),
        prevent_initial_call=True,
    )
    def pin_region(click_data, current):
        if not click_data or not click_data.get("points"):
            return current
        point = click_data["points"][0]
        mcap_key = next((key for key, label in MCAP_LABELS.items() if label == point.get("x")), None)
        liq_key = next((key for key, label in LIQUIDITY_LABELS.items() if label == point.get("y")), None)
        if point.get("x") == "Unknown":
            mcap_key = "missing"
        if point.get("y") == "Unknown":
            liq_key = "missing"
        if mcap_key is None or liq_key is None:
            return current
        pinned = region_id(mcap_key, liq_key)
        return None if pinned == current else pinned

    @callback(
        Output("store-cohort", "data"),
        Input("cohort-select", "value"),
        prevent_initial_call=True,
    )
    def set_cohort(value):
        return value

    # -- body --------------------------------------------------------------
    @callback(
        Output("view-body", "children"),
        Output("stamp", "children"),
        Input("store-view", "data"),
        Input("store-data", "data"),
        Input("store-region", "data"),
        Input("store-mode", "data"),
        Input("store-cohort", "data"),
        Input("f-launchpad", "value"),
        Input("f-graduation", "value"),
        Input("f-age", "value"),
        Input("f-holders", "value"),
        Input("f-activity", "value"),
        Input("f-mcap", "value"),
        Input("f-liquidity", "value"),
        Input("f-policy", "value"),
    )
    def render(view, artifacts, region, mode, cohort, launchpad, graduation, age, holders, activity, mcap, liquidity, policy):
        filters = {
            "launchpad": launchpad,
            "graduation": graduation,
            "age": age,
            "holders": holders,
            "activity": activity,
            "mcap": mcap,
            "liquidity": liquidity,
            "policy": policy,
            "region": region,
        }
        flow = artifacts.get("flow") or {}
        stamp = [
            html.Div(artifacts["snapshot"].get("generated_at", "unknown")),
            html.Div(
                f"flow {flow.get('generated_at', '—')[:19]}" if flow else "flow — not collected yet",
                style={"opacity": 0.6},
            ),
        ]
        if view == "flow":
            body = view_flow(artifacts, filters)
        elif view == "cohorts":
            body = view_cohorts(artifacts, filters, cohort)
        elif view == "activity":
            body = view_activity(artifacts, filters)
        elif view == "origin":
            body = view_origin(artifacts, filters)
        elif view == "filter":
            body = view_filter_evidence(artifacts, filters)
        elif view == "policy":
            body = view_policy(artifacts, filters)
        else:
            body = view_state(artifacts, filters, mode)
        warning = snapshot_health_banner(artifacts)
        if warning is not None:
            body = [warning] + list(body)
        return body, stamp

    # -- artifacts ---------------------------------------------------------
    @callback(
        Output("store-data", "data"),
        Input("reload", "n_clicks"),
        prevent_initial_call=True,
    )
    def reload_artifacts(_clicks):
        return load_artifacts(snapshot_path)

    @callback(
        Output("download", "data"),
        Input("export", "n_clicks"),
        State("store-data", "data"),
        State("store-region", "data"),
        State("f-launchpad", "value"),
        State("f-graduation", "value"),
        State("f-age", "value"),
        State("f-holders", "value"),
        State("f-activity", "value"),
        State("f-mcap", "value"),
        State("f-liquidity", "value"),
        State("f-policy", "value"),
        prevent_initial_call=True,
    )
    def export_csv(_clicks, artifacts, region, launchpad, graduation, age, holders, activity, mcap, liquidity, policy):
        filters = {
            "launchpad": launchpad,
            "graduation": graduation,
            "age": age,
            "holders": holders,
            "activity": activity,
            "mcap": mcap,
            "liquidity": liquidity,
            "policy": policy,
            "region": region,
        }
        rows = filtered_rows(artifacts["snapshot"], filters)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(CELL_SCHEMA)
        writer.writerows(rows)
        return {
            "content": output.getvalue(),
            "filename": "jupiter_region_snapshot_filtered.csv",
            "type": "text/csv",
        }

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local dashboard for the Jupiter semantic state space")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
