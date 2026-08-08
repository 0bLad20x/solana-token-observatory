from __future__ import annotations

import html
import math

from .analysis import _joint_row
from .constants import POPULATION_DISTRIBUTION_SVG_PATH

def _format_money_tick(value: float) -> str:
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:g}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:g}M"
    if value >= 1_000:
        return f"${value / 1_000:g}k"
    if value >= 1:
        return f"${value:g}"
    return f"${value:.2g}"


def _threshold_row(data: dict, threshold: float) -> dict | None:
    for row in data.get("thresholds", []):
        if math.isclose(float(row["threshold"]), float(threshold), rel_tol=0.0, abs_tol=1e-12):
            return row
    return None


def write_population_distribution_svg(output: dict) -> None:
    distribution = output.get("population_distribution")
    if not distribution:
        return

    width, height = 1440, 1320
    margin_left = 90
    plot_width = 900
    side_x = 1030
    side_width = 360
    panel_height = 250
    total = distribution["total_active_with_snapshot"]

    age_styles = [
        ("under_30m", "#555", ""),
        ("30_60m", "#666", "6,3"),
        ("1_3h", "#777", "2,3"),
        ("3_8h", "#888", "9,3,2,3"),
        ("8h_plus", "#999", "12,4"),
    ]
    age_by_key = {row["key"]: row for row in distribution.get("age_segments", [])}

    def panel(metric: str, top: int, title: str, ticks: list[float], hard_thresholds: list[float]) -> str:
        data = distribution[metric]
        curve = data["ecdf"]
        positive_x = [point["value"] for point in curve if point["value"] and point["value"] > 0]
        if not positive_x:
            return ""
        min_x, max_x = min(positive_x), max(positive_x)
        lo, hi = math.log10(min_x), math.log10(max_x)
        if hi <= lo:
            hi = lo + 1.0
        sx = lambda value: margin_left + (math.log10(value) - lo) / (hi - lo) * plot_width
        sy = lambda pct: top + panel_height - pct / 100.0 * panel_height
        parts: list[str] = []

        for pct in [0, 25, 50, 75, 100]:
            y = sy(pct)
            parts.append(
                f'<line x1="{margin_left}" y1="{y:.1f}" x2="{margin_left + plot_width}" y2="{y:.1f}" stroke="#e1e1e1" stroke-width="1" />'
            )
            parts.append(
                f'<text x="{margin_left - 12}" y="{y + 4:.1f}" text-anchor="end" font-size="12">{pct}%</text>'
            )

        for tick in ticks:
            if tick <= 0 or tick < min_x or tick > max_x:
                continue
            x = sx(tick)
            parts.append(
                f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + panel_height}" stroke="#eeeeee" stroke-width="1" />'
            )
            parts.append(
                f'<text x="{x:.1f}" y="{top + panel_height + 22}" text-anchor="middle" font-size="11">{html.escape(_format_money_tick(tick))}</text>'
            )

        # Hard thresholds: marker in the plot, counts stay in the side table.
        for threshold in hard_thresholds:
            if threshold <= 0 or threshold < min_x or threshold > max_x:
                continue
            x = sx(threshold)
            parts.append(
                f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + panel_height}" stroke="#333" stroke-width="1.4" stroke-dasharray="4,4" />'
            )
            parts.append(
                f'<text x="{x + 4:.1f}" y="{top + 13}" font-size="10" font-weight="bold">{html.escape(_format_money_tick(threshold))}</text>'
            )

        # Overall: normalized to known values, while missing is shown explicitly.
        overall_points = " ".join(
            f'{sx(point["value"]):.2f},{sy(point["pct_of_present"]):.2f}'
            for point in curve
            if point["value"] and point["value"] > 0
        )
        parts.append(
            f'<polyline fill="none" stroke="#111" stroke-width="3.2" points="{overall_points}" />'
        )

        # Age cohorts: each cohort normalized to its own known values.
        for age_key, stroke, dash in age_styles:
            age = age_by_key.get(age_key)
            if not age:
                continue
            age_curve = age[metric]["ecdf"]
            age_points = []
            for point in age_curve:
                value = point.get("value")
                if not value or value <= 0 or value < min_x or value > max_x:
                    continue
                age_points.append(f'{sx(value):.2f},{sy(point["pct_of_present"]):.2f}')
            if len(age_points) < 2:
                continue
            dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
            parts.append(
                f'<polyline fill="none" stroke="{stroke}" stroke-width="1.5"{dash_attr} points="{" ".join(age_points)}" />'
            )

        parts.append(
            f'<rect x="{margin_left}" y="{top}" width="{plot_width}" height="{panel_height}" fill="none" stroke="#555" stroke-width="1" />'
        )
        parts.append(
            f'<text x="{margin_left}" y="{top - 32}" font-size="19" font-weight="bold">{html.escape(title)}</text>'
        )
        subtitle = (
            f'Known {data["present"]:,}/{total:,} ({data["coverage_pct"]:.1f}%) | '
            f'UNKNOWN {data["missing"]:,} | median {_format_money_tick(data["quantiles"]["p50"] or 0)} | '
            'y = % within cohort among known values'
        )
        parts.append(
            f'<text x="{margin_left}" y="{top - 12}" font-size="11">{html.escape(subtitle)}</text>'
        )

        # Right-side summary.
        parts.append(
            f'<rect x="{side_x}" y="{top}" width="{side_width}" height="{panel_height}" rx="4" fill="#fafafa" stroke="#bbb" />'
        )
        parts.append(
            f'<text x="{side_x + 14}" y="{top + 22}" font-size="13" font-weight="bold">Hard thresholds</text>'
        )
        y = top + 44
        for threshold in hard_thresholds:
            row = _threshold_row(data, threshold)
            if not row:
                continue
            label = (
                f'< {_format_money_tick(threshold)}: {row["count_below"]:,} '
                f'({row["pct_of_all_active"]:.1f}% all)'
            )
            parts.append(
                f'<text x="{side_x + 14}" y="{y}" font-size="12">{html.escape(label)}</text>'
            )
            y += 19

        y += 6
        parts.append(
            f'<text x="{side_x + 14}" y="{y}" font-size="13" font-weight="bold">Age cohorts</text>'
        )
        y += 20
        for age_key, stroke, dash in age_styles:
            age = age_by_key.get(age_key)
            if not age:
                continue
            dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
            parts.append(
                f'<line x1="{side_x + 14}" y1="{y - 4}" x2="{side_x + 46}" y2="{y - 4}" stroke="{stroke}" stroke-width="2"{dash_attr} />'
            )
            parts.append(
                f'<text x="{side_x + 54}" y="{y}" font-size="11">{html.escape(age["label"])}  n={age["total"]:,}</text>'
            )
            y += 17

        return "\n".join(parts)

    def heatmap(top: int) -> str:
        density = distribution.get("joint_density", {})
        x_lo = density.get("x_log_min")
        x_hi = density.get("x_log_max")
        y_lo = density.get("y_log_min")
        y_hi = density.get("y_log_max")
        if None in (x_lo, x_hi, y_lo, y_hi):
            return ""

        heat_height = 330
        x_bins = int(density["x_bins"])
        y_bins = int(density["y_bins"])
        cell_w = plot_width / x_bins
        cell_h = heat_height / y_bins
        max_count = max(int(density.get("max_cell_count", 0)), 1)
        parts: list[str] = []

        parts.append(
            f'<text x="{margin_left}" y="{top - 32}" font-size="19" font-weight="bold">Market cap × liquidity — log-density</text>'
        )
        parts.append(
            f'<text x="{margin_left}" y="{top - 12}" font-size="11">Each cell contains active tokens with both positive values. Darker = denser. Operational filter evidence is reported separately in Phase 6.</text>'
        )

        retire_cells = {
            (int(row["ix"]), int(row["iy"])): int(row["count"])
            for row in distribution.get("policy_overlay", {}).get("would_retire_density_cells", [])
        }

        for cell in density.get("cells", []):
            ix, iy, count = int(cell["ix"]), int(cell["iy"]), int(cell["count"])
            x = margin_left + ix * cell_w
            y = top + heat_height - (iy + 1) * cell_h
            intensity = math.log1p(count) / math.log1p(max_count)
            shade = int(round(246 - intensity * 190))
            shade = max(45, min(246, shade))
            parts.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{cell_w + 0.15:.2f}" height="{cell_h + 0.15:.2f}" fill="rgb({shade},{shade},{shade})" stroke="#f7f7f7" stroke-width="0.35" />'
            )
            retire_count = retire_cells.get((ix, iy), 0)
            if retire_count:
                parts.append(
                    f'<rect x="{x + 1:.2f}" y="{y + 1:.2f}" width="{max(cell_w - 2, 0):.2f}" height="{max(cell_h - 2, 0):.2f}" fill="none" stroke="#111" stroke-width="2" />'
                )

        sx_log = lambda log_value: margin_left + (log_value - x_lo) / (x_hi - x_lo) * plot_width
        sy_log = lambda log_value: top + heat_height - (log_value - y_lo) / (y_hi - y_lo) * heat_height

        for power in range(math.ceil(x_lo), math.floor(x_hi) + 1):
            value = 10 ** power
            x = sx_log(power)
            parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + heat_height}" stroke="#d5d5d5" stroke-width="0.8" />')
            parts.append(f'<text x="{x:.1f}" y="{top + heat_height + 20}" text-anchor="middle" font-size="10">{html.escape(_format_money_tick(value))}</text>')
        for power in range(math.ceil(y_lo), math.floor(y_hi) + 1):
            value = 10 ** power
            y = sy_log(power)
            parts.append(f'<line x1="{margin_left}" y1="{y:.1f}" x2="{margin_left + plot_width}" y2="{y:.1f}" stroke="#d5d5d5" stroke-width="0.8" />')
            parts.append(f'<text x="{margin_left - 12}" y="{y + 4:.1f}" text-anchor="end" font-size="10">{html.escape(_format_money_tick(value))}</text>')

        # Reference hard boundaries.
        for value in [200, 2_000, 10_000]:
            log_value = math.log10(value)
            if x_lo <= log_value <= x_hi:
                x = sx_log(log_value)
                parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + heat_height}" stroke="#111" stroke-width="1.2" stroke-dasharray="5,4" />')
        for value in [1, 100, 2_000]:
            log_value = math.log10(value)
            if y_lo <= log_value <= y_hi:
                y = sy_log(log_value)
                parts.append(f'<line x1="{margin_left}" y1="{y:.1f}" x2="{margin_left + plot_width}" y2="{y:.1f}" stroke="#111" stroke-width="1.2" stroke-dasharray="5,4" />')

        parts.append(f'<rect x="{margin_left}" y="{top}" width="{plot_width}" height="{heat_height}" fill="none" stroke="#555" />')
        parts.append(f'<text x="{margin_left + plot_width / 2}" y="{top + heat_height + 43}" text-anchor="middle" font-size="12">Market cap (log)</text>')
        parts.append(f'<text x="24" y="{top + heat_height / 2}" text-anchor="middle" font-size="12" transform="rotate(-90 24 {top + heat_height / 2})">Liquidity (log)</text>')

        # Candidate impact box.
        parts.append(f'<rect x="{side_x}" y="{top}" width="{side_width}" height="{heat_height}" rx="4" fill="#fafafa" stroke="#bbb" />')
        parts.append(f'<text x="{side_x + 14}" y="{top + 22}" font-size="13" font-weight="bold">Candidate impact</text>')
        y = top + 46
        overlay = distribution.get("policy_overlay", {})
        if overlay:
            allocation = overlay.get("priority_allocation", {})
            allocation_pct = overlay.get("priority_allocation_pct", {})
            lines = [
                f'P1: {allocation.get("p1", 0):,} ({allocation_pct.get("p1", 0):.1f}%)',
                f'P2: {allocation.get("p2", 0):,} ({allocation_pct.get("p2", 0):.1f}%)',
                f'P3: {allocation.get("p3", 0):,} ({allocation_pct.get("p3", 0):.1f}%)',
                f'RETIRED: {allocation.get("retire", 0):,} ({allocation_pct.get("retire", 0):.1f}%)',
                f'PROBATION: {overlay.get("probation_unique", 0):,}',
            ]
            for line in lines:
                parts.append(f'<text x="{side_x + 14}" y="{y}" font-size="12">{html.escape(line)}</text>')
                y += 19
            y += 7
            parts.append(f'<text x="{side_x + 14}" y="{y}" font-size="10">Rule-level evidence: dashboard Phase 6</text>')
        else:
            parts.append(f'<text x="{side_x + 14}" y="{y}" font-size="12">No monitor state overlay in one-shot mode.</text>')
            y += 24

        y += 10
        parts.append(f'<text x="{side_x + 14}" y="{y}" font-size="13" font-weight="bold">Selected raw unions</text>')
        y += 20
        for mcap_threshold, liq_threshold in [(2_000, 1), (5_000, 100), (10_000, 2_000)]:
            row = _joint_row(distribution, mcap_threshold, liq_threshold)
            if not row:
                continue
            label = (
                f'MC<{_format_money_tick(mcap_threshold)} OR LIQ<{_format_money_tick(liq_threshold)}: '
                f'{row["union_low_count"]:,} ({row["union_pct_of_all_active"]:.1f}%)'
            )
            parts.append(f'<text x="{side_x + 14}" y="{y}" font-size="10">{html.escape(label)}</text>')
            y += 16

        return "\n".join(parts)

    mcap_ticks = [100, 200, 1_000, 2_000, 5_000, 10_000, 100_000, 1_000_000, 10_000_000]
    liq_ticks = [0.01, 0.1, 1, 10, 100, 1_000, 2_000, 10_000, 100_000, 1_000_000]
    generated = output.get("generated_at", "")

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="white"/>
<text x="{margin_left}" y="36" font-size="25" font-weight="bold">Current token population — hard-filter diagnostics</text>
<text x="{margin_left}" y="59" font-size="12">{html.escape(str(generated))} | active snapshots: {total:,} | log x-axes | UNKNOWN is never treated as zero</text>
<text x="{margin_left}" y="79" font-size="11">Age curves compare cohort shapes; threshold tables show absolute operational impact on the full active population.</text>
{panel("mcap", 135, "Market-cap ECDF by token age", mcap_ticks, [200, 2_000, 5_000, 10_000])}
{panel("liquidity", 515, "Liquidity ECDF by token age", liq_ticks, [1, 100, 1_000, 2_000])}
{heatmap(900)}
</svg>'''
    POPULATION_DISTRIBUTION_SVG_PATH.write_text(svg, encoding="utf-8")
