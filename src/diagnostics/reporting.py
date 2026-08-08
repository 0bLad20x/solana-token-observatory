from __future__ import annotations

import time
from datetime import datetime, timezone

import psycopg

from config import Settings

from .analysis import (
    _joint_row,
    bot_ratio_clusters,
    compact_population_run_summary,
    data_quality_metrics,
    graduation_gap_vs_crash,
    graduation_state_leading_indicator,
    holder_stagnation,
    liquidity_bucket_vs_price_change,
    liquidity_peak_crash,
    mcap_null_correlation,
    mcap_null_never_had_stuck_samples,
    mcap_null_pattern_analysis,
    mcap_peak_crash,
    newly_stale_3_24h_samples,
    null_launchpad_by_age,
    null_launchpad_pool_signature,
    overlap_analysis,
    peak_timing_metrics,
    population_distribution_metrics,
    run_categories,
    stale_bucket_breakdown,
    stats1h_activity_vs_unchanged_validation,
    trajectory_metrics,
    validate_internal_consistency,
    young_token_change_artifact,
)
from .constants import OUTPUT_PATH, POPULATION_DISTRIBUTION_SVG_PATH
from .data import (
    build_gmgn_cache,
    build_history_cache,
    build_latest_cache,
    collect_collector_health,
    fetch_policy_features,
    get_context,
    measured,
)
from .policy import current_policy_simulation
from .storage import atomic_write_json
from .visualization import write_population_distribution_svg

def build_report(
    settings: Settings,
    policy_config: dict,
) -> tuple[dict, list[dict]]:
    timings: dict[str, float] = {}
    total_started = time.perf_counter()

    with psycopg.connect(settings.database_url) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")

        with measured(timings, "build_latest_cache_ms"):
            build_latest_cache(connection)

        with measured(timings, "build_history_cache_ms"):
            build_history_cache(connection, timings)

        with measured(timings, "build_gmgn_cache_ms"):
            build_gmgn_cache(connection)

        with measured(timings, "context_ms"):
            context = get_context(connection)

        with measured(timings, "collector_health_ms"):
            collector_health = collect_collector_health(connection, policy_config)

        with measured(timings, "categories_ms"):
            results = run_categories(connection)

        with measured(timings, "mcap_peak_crash_ms"):
            results.append(mcap_peak_crash(connection))

        with measured(timings, "liquidity_peak_crash_ms"):
            results.append(liquidity_peak_crash(connection))

        with measured(timings, "holder_stagnation_ms"):
            results.append(holder_stagnation(connection))

        with measured(timings, "latest_cross_analysis_ms"):
            overlap = overlap_analysis(connection)
            young_artifact = young_token_change_artifact(connection)
            mcap_corr = mcap_null_correlation(connection)
            liq_price_curve = liquidity_bucket_vs_price_change(connection)
            null_lp_by_age = null_launchpad_by_age(connection)
            null_lp_signature = null_launchpad_pool_signature(connection)
            grad_gap_crash = graduation_gap_vs_crash(connection)
            stale_breakdown = stale_bucket_breakdown(connection)
            newly_stale_samples = newly_stale_3_24h_samples(connection)
            ratio_clusters = bot_ratio_clusters(connection)
            stats1h_validation = stats1h_activity_vs_unchanged_validation(connection)

        with measured(timings, "graduation_leading_indicator_ms"):
            grad_leading_indicator = graduation_state_leading_indicator(connection)

        with measured(timings, "mcap_null_analysis_ms"):
            mcap_null_pattern = mcap_null_pattern_analysis(connection)
            mcap_null_stuck_samples = mcap_null_never_had_stuck_samples(connection)

        with measured(timings, "decision_metrics_ms"):
            quality = data_quality_metrics(connection)
            trajectory = trajectory_metrics(connection)
            peak_timing = peak_timing_metrics(connection)
            population_distribution = population_distribution_metrics(connection)
            policy_features = fetch_policy_features(connection)
            policy_simulation = current_policy_simulation(
                policy_config,
                policy_features,
            )

        with measured(timings, "validation_ms"):
            technical_validation = validate_internal_consistency(
                connection,
                context,
                results,
                overlap,
                stale_breakdown,
                stats1h_validation,
            )

    timings["total_ms"] = round(
        (time.perf_counter() - total_started) * 1000,
        2,
    )

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "context": context,
        "collector_health": collector_health,
        "decision_metrics": {
            "data_quality": quality,
            "trajectory": trajectory,
            "peak_timing": peak_timing,
        },
        "population_distribution": population_distribution,
        "policy_simulation": policy_simulation,
        "filter_evidence": {
            "mode": "instantaneous_shadow_matches",
            "total_active": len(policy_features),
            "allocation": policy_simulation["instantaneous_match_allocation"],
            "allocation_pct": {
                key: round(value / len(policy_features) * 100, 3)
                if policy_features else 0.0
                for key, value in policy_simulation["instantaneous_match_allocation"].items()
            },
            "priority_cadences_seconds": policy_config.get(
                "priority_cadences_seconds", {}
            ),
            "reason_counts": [
                {"rule_id": row["rule_id"], "count": row["current_match_count"]}
                for row in policy_simulation["rules"]
            ],
            "rules": policy_simulation["rules"],
            "candidate_samples": [
                sample | {"rule_id": row["rule_id"], "action": row["action"]}
                for row in policy_simulation["rules"]
                for sample in row.get("samples", [])
            ][:25],
        },
        "categories": results,
        "cross_analysis": {
            "liquidity_vs_price_crash_overlap": overlap,
            "young_token_change_field_artifact": young_artifact,
            "mcap_null_correlation_with_liquidity": mcap_corr,
            "liquidity_bucket_vs_price_change_curve": liq_price_curve,
            "null_launchpad_by_age": null_lp_by_age,
            "null_launchpad_pool_signature": null_lp_signature,
            "met_dbc_graduation_gap_vs_crash": grad_gap_crash,
            "met_dbc_graduation_leading_indicator": grad_leading_indicator,
            "stale_bucket_breakdown": stale_breakdown,
            "newly_stale_3_24h_samples": newly_stale_samples,
            "mcap_null_pattern_analysis": mcap_null_pattern,
            "mcap_null_never_had_stuck_samples": mcap_null_stuck_samples,
            "bot_ratio_clusters": ratio_clusters,
            "stats1h_activity_vs_unchanged_validation": stats1h_validation,
        },
        "technical_validation": technical_validation,
        "performance": timings,
    }
    return output, policy_features


def write_report(output: dict) -> None:
    atomic_write_json(OUTPUT_PATH, output)
    write_population_distribution_svg(output)


def print_full_report(output: dict) -> None:
    context = output["context"]
    results = output["categories"]
    cross = output["cross_analysis"]
    timings = output["performance"]

    print(f"Geschrieben nach: {OUTPUT_PATH}\n")
    print(f"Gesamt getrackte Mints: {context['total_tracked_mints']}\n")
    for row in results:
        pct = (
            row["total_count"] / context["total_tracked_mints"] * 100
            if context["total_tracked_mints"]
            else 0
        )
        print(
            f"  {row['category']:<40} total={row['total_count']:>6} "
            f"({pct:>5.1f}%)"
        )

    print(f"\n  COLLECTOR HEALTH: {output['collector_health']['status']}")
    observed = output["collector_health"]["observed"]
    print(
        f"    recent_poll_fraction={observed['recent_poll_fraction']:.3f}  "
        f"p95_poll_age={observed['p95_poll_age_seconds']}s  "
        f"snapshot_coverage={observed['snapshot_coverage_fraction']:.3f}"
    )

    print("\n  ZUSAETZLICHE DECISION METRICS:")
    quality = output["decision_metrics"]["data_quality"]
    for field, row in quality["fields"].items():
        print(
            f"    field {field:<18} present={row['present']:>6} "
            f"({row['present_pct']:>6.2f}%)"
        )
    trajectory = output["decision_metrics"]["trajectory"]
    print(
        f"    mcap drop >=95%:       "
        f"{trajectory['mcap_drop_from_peak']['>=95pct']}"
    )
    print(
        f"    liquidity drop >=95%:  "
        f"{trajectory['liquidity_drop_from_peak']['>=95pct']}"
    )

    distribution = output["population_distribution"]
    print("\n  POPULATION DISTRIBUTION (strictly below threshold):")
    for metric, wanted in (("mcap", {200, 1_000, 2_000, 5_000, 10_000}), ("liquidity", {1, 100, 1_000, 2_000, 10_000})):
        data = distribution[metric]
        print(f"    {metric}: present={data['present']} missing={data['missing']} median={data['quantiles']['p50']}")
        for row in data["thresholds"]:
            if float(row["threshold"]) in wanted:
                print(f"      < {row['threshold']:>8g}: {row['count_below']:>6} ({row['pct_of_all_active']:>6.2f}% of all)")
    devs = distribution["developers"]
    print(f"    devs: distinct={devs['distinct_devs']} repeated={devs['repeated_devs']} tokens_from_repeated={devs['tokens_from_repeated_devs']}")
    age_segments = distribution.get("age_segments", [])
    if age_segments:
        print("    age cohorts: " + ", ".join(f"{row['label']}={row['total']}" for row in age_segments))
    for mcap_threshold, liq_threshold in [(2_000, 1), (5_000, 100), (10_000, 2_000)]:
        row = _joint_row(distribution, mcap_threshold, liq_threshold)
        if row:
            print(
                f"    MC<{mcap_threshold:g} OR LIQ<{liq_threshold:g}: "
                f"{row['union_low_count']} ({row['union_pct_of_all_active']:.2f}% of all)"
            )
    print(f"    curve: {POPULATION_DISTRIBUTION_SVG_PATH}")

    print("\n  POLICY-SIMULATION (noch keine Deaktivierung):")
    for rule in output["policy_simulation"]["rules"]:
        print(
            f"    {rule['rule_id']:<45} "
            f"action={rule['action']:<6} "
            f"matches={rule['current_match_count']:>6}"
        )

    print("\n  Liquiditaets-Bucket vs. Preisaenderung (Median):")
    for row in cross["liquidity_bucket_vs_price_change_curve"]:
        print(
            f"    {row['liquidity_bucket']:<18} "
            f"n={row['count']:>5}  "
            f"median={row['median_price_change_pct']}"
        )

    print("\n  launchpad=null nach Alter:")
    for row in cross["null_launchpad_by_age"]:
        print(
            f"    {row['age_bucket']:<12} "
            f"total={row['total']:>5}  crashed={row['crashed']:>5}"
        )

    print("\n  met-dbc Graduierungs-Verzoegerung vs. Crash:")
    for row in cross["met_dbc_graduation_gap_vs_crash"]:
        print(
            f"    {row['bucket']:<15} "
            f"total={row['total']:>5}  crashed={row['crashed']:>5}"
        )

    print("\n  no_update>10min Aufschluesselung:")
    for row in cross["stale_bucket_breakdown"]:
        print(f"    {row['bucket']:<10} n={row['count']:>5}")

    print("\n  mcap=null Muster:")
    for row in cross["mcap_null_pattern_analysis"]:
        print(
            f"    {row['pattern']:<22} "
            f"{row['observed_span_bucket']:<10} n={row['count']:>5}"
        )

    print(f"\n  TECHNICAL VALIDATION: {output['technical_validation']['status']}")
    print("\n  PERFORMANCE:")
    for name, duration_ms in timings.items():
        print(f"    {name:<40} {duration_ms:>10.2f} ms")
