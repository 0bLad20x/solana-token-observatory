from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from .constants import (
    DEFAULT_POLICY_CONFIG,
    MONITOR_CONTINUITY_FACTOR,
    POLICY_RULES_PATH,
    POLICY_STATE_PATH,
    SAMPLE_LIMIT,
)
from .storage import atomic_write_json

def load_policy_config() -> dict:
    """Laedt die experimentellen Regeln bei jedem Monitor-Lauf neu."""
    if not POLICY_RULES_PATH.exists():
        atomic_write_json(POLICY_RULES_PATH, DEFAULT_POLICY_CONFIG)

    try:
        config = json.loads(POLICY_RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Policy-Konfiguration unlesbar: {POLICY_RULES_PATH}: {exc}"
        ) from exc

    if config.get("schema_version") != 1:
        raise RuntimeError("policy_rules.json: schema_version muss 1 sein")
    if not isinstance(config.get("collector_health"), dict):
        raise RuntimeError("policy_rules.json: collector_health fehlt")
    if not isinstance(config.get("rules"), list):
        raise RuntimeError("policy_rules.json: rules muss eine Liste sein")

    seen_ids: set[str] = set()
    for rule in config["rules"]:
        if not isinstance(rule, dict):
            raise RuntimeError("policy_rules.json: jede Rule muss ein Objekt sein")
        for required in ("id", "version", "type", "thresholds"):
            if required not in rule:
                raise RuntimeError(f"policy_rules.json: Rule ohne {required}")
        rule_id = str(rule["id"])
        if rule_id in seen_ids:
            raise RuntimeError(f"policy_rules.json: doppelte Rule-ID: {rule_id}")
        seen_ids.add(rule_id)

    return config


def policy_config_hash(config: dict) -> str:
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def rule_key(rule: dict) -> str:
    encoded = json.dumps(rule, sort_keys=True, separators=(",", ":")).encode("utf-8")
    fingerprint = hashlib.sha256(encoded).hexdigest()[:10]
    return f"{rule['id']}@v{rule['version']}:{fingerprint}"


def _at_least(value: float | int | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def _at_most(value: float | int | None, threshold: float) -> bool:
    return value is not None and value <= threshold


def evaluate_rule(rule: dict, feature: dict) -> bool:
    """Konservative Regelbewertung: fehlende Werte werden nicht als Null erfunden."""
    if not rule.get("enabled", True):
        return False

    thresholds = rule["thresholds"]
    rule_type = rule["type"]

    min_age = float(thresholds.get("min_age_minutes", 0))
    min_unchanged = float(thresholds.get("min_unchanged_minutes", 0))
    if bool(thresholds.get("strict_min_age", False)):
        if feature["age_minutes"] is None or feature["age_minutes"] <= min_age:
            return False
    elif not _at_least(feature["age_minutes"], min_age):
        return False
    if not _at_least(feature["unchanged_minutes"], min_unchanged):
        return False

    if rule_type == "terminal_liquidity_collapse":
        return (
            feature["has_liquidity"]
            and _at_least(
                feature["peak_liquidity"],
                float(thresholds["min_peak_liquidity"]),
            )
            and _at_most(
                feature["liquidity"],
                float(thresholds["max_current_liquidity"]),
            )
            and _at_least(
                feature["liquidity_drop_pct"],
                float(thresholds["min_liquidity_drop_pct"]),
            )
            and (
                feature["mcap"] is None
                or _at_most(
                    feature["mcap"],
                    float(thresholds["max_current_mcap_or_null"]),
                )
            )
        )

    if rule_type == "terminal_liquidity_collapse_mcap_missing":
        return (
            feature["has_liquidity"]
            and _at_least(
                feature["peak_liquidity"],
                float(thresholds["min_peak_liquidity"]),
            )
            and _at_most(
                feature["liquidity"],
                float(thresholds["max_current_liquidity"]),
            )
            and _at_least(
                feature["liquidity_drop_pct"],
                float(thresholds["min_liquidity_drop_pct"]),
            )
            and feature["mcap"] is None
        )

    if rule_type == "terminal_market_collapse":
        return (
            feature["has_mcap"]
            and feature["mcap"] is not None
            and feature["has_liquidity"]
            and feature["liquidity"] is not None
            and _at_least(feature["peak_mcap"], float(thresholds["min_peak_mcap"]))
            and _at_most(feature["mcap"], float(thresholds["max_current_mcap"]))
            and _at_least(
                feature["mcap_drop_pct"],
                float(thresholds["min_mcap_drop_pct"]),
            )
            and _at_most(
                feature["liquidity"],
                float(thresholds["max_current_liquidity"]),
            )
        )

    if rule_type == "legacy_low_liquidity":
        return (
            feature["has_liquidity"]
            and feature["liquidity"] is not None
            and feature["liquidity"]
            < float(thresholds["max_current_liquidity"])
        )

    if rule_type == "legacy_pre_migration_stale":
        return (
            not feature["is_graduated"]
            and feature["peak_mcap"] is not None
            and feature["peak_mcap"] < float(thresholds["max_peak_mcap"])
        )

    if rule_type == "abandoned_micro_token":
        if not (
            feature["has_holder_count"]
            and feature["holders"] is not None
            and feature["has_liquidity"]
            and feature["liquidity"] is not None
        ):
            return False

        if bool(thresholds.get("require_zero_stats1h_activity", False)):
            # Missing stats1h is unknown, not "zero activity".
            if not feature["has_stats1h"] or feature["stats1h_activity"] != 0:
                return False

        return (
            _at_most(feature["holders"], float(thresholds["max_holders"]))
            and _at_most(
                feature["liquidity"],
                float(thresholds["max_current_liquidity"]),
            )
            and (
                feature["mcap"] is None
                or _at_most(
                    feature["mcap"],
                    float(thresholds["max_current_mcap_or_null"]),
                )
            )
        )

    raise RuntimeError(f"Unbekannter Rule-Typ: {rule_type}")


def compact_evidence(feature: dict) -> dict:
    keys = (
        "name",
        "symbol",
        "launchpad",
        "is_graduated",
        "graduation_age_minutes",
        "age_minutes",
        "unchanged_minutes",
        "mcap",
        "peak_mcap",
        "mcap_drop_pct",
        "liquidity",
        "peak_liquidity",
        "liquidity_drop_pct",
        "holders",
        "peak_holders",
        "holder_retention_pct",
        "stats1h_activity",
        "snapshot_count",
    )
    result = {key: feature.get(key) for key in keys}
    for key, value in list(result.items()):
        if isinstance(value, float):
            result[key] = round(value, 6)
    return result


def current_policy_simulation(config: dict, features: list[dict]) -> dict:
    rows: list[dict] = []
    protected_mints = set(config.get("protected_mints", []))
    for rule in config["rules"]:
        if not rule.get("enabled", True):
            continue
        matches = [
            feature
            for feature in features
            if feature["mint"] not in protected_mints
            and evaluate_rule(rule, feature)
        ]
        rows.append(
            {
                "rule_key": rule_key(rule),
                "rule_id": rule["id"],
                "version": rule["version"],
                "type": rule["type"],
                "source_rule": rule.get("source_rule"),
                "decision_mode": rule.get("decision_mode", "persistent"),
                "persistence_minutes": rule.get("persistence_minutes", 0),
                "min_consecutive_matches": rule.get("min_consecutive_matches", 1),
                "current_match_count": len(matches),
                "samples": [
                    {
                        "mint": feature["mint"],
                        "evidence": compact_evidence(feature),
                    }
                    for feature in matches[:SAMPLE_LIMIT]
                ],
            }
        )

    return {
        "rule_set_hash": policy_config_hash(config),
        "protected_mints": sorted(protected_mints),
        "legacy_rust_v6": config.get("legacy_rust_v6"),
        "rules": rows,
    }


def load_monitor_state() -> dict:
    if not POLICY_STATE_PATH.exists():
        return {
            "schema_version": 1,
            "last_healthy_run_at": None,
            "tokens": {},
        }

    try:
        state = json.loads(POLICY_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Monitor-State unlesbar: {POLICY_STATE_PATH}: {exc}"
        ) from exc

    if state.get("schema_version") != 1:
        raise RuntimeError("policy_state.json: unbekannte schema_version")
    state.setdefault("last_healthy_run_at", None)
    state.setdefault("tokens", {})
    return state


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _meaningfully_equal(metric: str, previous: Any, current: Any) -> bool:
    if previous is None or current is None:
        return previous is current
    if metric == "holders":
        return previous == current

    previous = float(previous)
    current = float(current)
    scale = max(abs(previous), abs(current), 1.0)
    # Mcap/Liquiditaet: minimale API-/Float-Bewegungen sollen keine echte
    # Zustandsaenderung vortaeuschen.
    return abs(previous - current) <= max(1.0, scale * 0.01)


def update_monitor_token_metrics(
    state: dict,
    features: list[dict],
    now: datetime,
    interval_seconds: int,
) -> bool:
    last_healthy = _parse_iso(state.get("last_healthy_run_at"))
    continuity = (
        last_healthy is not None
        and 0 <= (now - last_healthy).total_seconds()
        <= interval_seconds * MONITOR_CONTINUITY_FACTOR
    )

    tokens = state["tokens"]
    present_mints: set[str] = set()

    for feature in features:
        mint = feature["mint"]
        present_mints.add(mint)
        token = tokens.setdefault(mint, {"metrics": {}, "rules": {}})
        metrics = token.setdefault("metrics", {})

        for metric in ("holders", "mcap", "liquidity"):
            current = feature.get(metric)
            previous = metrics.get(metric)
            if (
                continuity
                and previous
                and _meaningfully_equal(metric, previous.get("value"), current)
            ):
                since = previous.get("since") or now.isoformat()
            else:
                since = now.isoformat()

            metrics[metric] = {"value": current, "since": since}
            since_dt = _parse_iso(since) or now
            feature[f"{metric}_stable_minutes"] = max(
                (now - since_dt).total_seconds() / 60,
                0.0,
            )

        token["last_seen_at"] = now.isoformat()

    # Token, die aus der aktuellen aktiven Population verschwunden sind,
    # werden nicht sofort geloescht: bestehende WOULD_RETIRE-Kohorten muessen
    # fuer spaetere Nachvollziehbarkeit erhalten bleiben.
    state["last_healthy_run_at"] = now.isoformat()
    return continuity


def prospective_monitor_metrics(features: list[dict]) -> dict:
    def buckets(metric: str) -> dict:
        result = {"<15min": 0, "15-60min": 0, "1-3h": 0, ">=3h": 0}
        for feature in features:
            value = feature.get(metric)
            if value is None:
                continue
            if value < 15:
                result["<15min"] += 1
            elif value < 60:
                result["15-60min"] += 1
            elif value < 180:
                result["1-3h"] += 1
            else:
                result[">=3h"] += 1
        return result

    return {
        "holder_stable_minutes": buckets("holders_stable_minutes"),
        "mcap_stable_minutes": buckets("mcap_stable_minutes"),
        "liquidity_stable_minutes": buckets("liquidity_stable_minutes"),
    }


def evaluate_recovery(rule: dict, feature: dict, baseline: dict) -> bool:
    """Positive Recovery, nicht blosses Nicht-mehr-Erfuellen einer Rule."""
    rule_type = rule["type"]

    current_liq = feature.get("liquidity")
    current_mcap = feature.get("mcap")
    current_holders = feature.get("holders")
    activity = feature.get("stats1h_activity") or 0

    if rule_type in {
        "terminal_liquidity_collapse",
        "terminal_liquidity_collapse_mcap_missing",
    }:
        peak_liq = baseline.get("peak_liquidity") or 0
        meaningful_liq = max(1000.0, float(peak_liq) * 0.01)
        return (
            current_liq is not None
            and current_liq >= meaningful_liq
        ) or (
            current_liq is not None
            and current_liq >= 100
            and current_mcap is not None
            and current_mcap >= 10000
        )

    if rule_type == "terminal_market_collapse":
        peak_mcap = baseline.get("peak_mcap") or 0
        meaningful_mcap = max(10000.0, float(peak_mcap) * 0.05)
        return (
            current_mcap is not None
            and current_mcap >= meaningful_mcap
            and current_liq is not None
            and current_liq >= 1000
        )

    if rule_type == "legacy_low_liquidity":
        threshold = float(rule["thresholds"]["max_current_liquidity"])
        return current_liq is not None and current_liq >= threshold

    if rule_type == "legacy_pre_migration_stale":
        threshold = float(rule["thresholds"]["max_peak_mcap"])
        return bool(feature.get("is_graduated")) or (
            feature.get("peak_mcap") is not None
            and float(feature["peak_mcap"]) >= threshold
        )

    if rule_type == "abandoned_micro_token":
        baseline_holders = baseline.get("holders") or 0
        return (
            current_liq is not None
            and current_liq >= 1000
        ) or (
            current_mcap is not None
            and current_mcap >= 10000
            and current_liq is not None
            and current_liq >= 100
        ) or (
            current_holders is not None
            and current_holders >= max(10, baseline_holders + 10)
            and activity > 0
        )

    return False


def _event(
    now: datetime,
    event_name: str,
    feature: dict,
    rule: dict,
    rule_state: dict,
    **extra: Any,
) -> dict:
    payload = {
        "timestamp": now.isoformat(),
        "event": event_name,
        "mint": feature["mint"],
        "rule_key": rule_key(rule),
        "rule_id": rule["id"],
        "rule_version": rule["version"],
        "rule_type": rule["type"],
        "source_rule": rule.get("source_rule"),
        "decision_mode": rule.get("decision_mode", "persistent"),
        "evidence": compact_evidence(feature),
        "first_match_at": rule_state.get("first_match_at"),
        "would_retire_at": rule_state.get("would_retire_at"),
    }
    payload.update(extra)
    return payload


def advance_policy_state(
    state: dict,
    config: dict,
    features: list[dict],
    now: datetime,
    interval_seconds: int,
    continuity: bool,
) -> tuple[list[dict], list[dict]]:
    """State-Machine fuer simulierte Entscheidungen; keine DB-Schreiboperation."""
    feature_by_mint = {feature["mint"]: feature for feature in features}
    tokens = state["tokens"]
    events: list[dict] = []
    summaries: list[dict] = []

    enabled_rules = [
        rule for rule in config["rules"] if rule.get("enabled", True)
    ]
    protected_mints = set(config.get("protected_mints", []))
    horizons = sorted(
        {int(value) for value in config.get("outcome_horizons_minutes", [30, 60, 360, 1440])}
    )
    max_horizon = max(horizons) if horizons else 1440

    for rule in enabled_rules:
        key = rule_key(rule)
        matched_count = 0

        for mint, feature in feature_by_mint.items():
            if mint in protected_mints:
                continue
            token = tokens.setdefault(mint, {"metrics": {}, "rules": {}})
            rules_state = token.setdefault("rules", {})
            rs = rules_state.get(key)
            matches = evaluate_rule(rule, feature)
            if matches:
                matched_count += 1

            # Noch keine laufende Rule-Kohorte.
            if rs is None:
                if matches:
                    immediate = rule.get("decision_mode") == "immediate"
                    rs = {
                        "status": "WOULD_RETIRE" if immediate else "PROBATION",
                        "first_match_at": now.isoformat(),
                        "last_match_at": now.isoformat(),
                        "consecutive_matches": 1,
                        "would_retire_at": now.isoformat() if immediate else None,
                        "baseline": compact_evidence(feature),
                        "checked_horizons": [],
                    }
                    rules_state[key] = rs
                    if immediate:
                        events.append(
                            _event(
                                now,
                                "WOULD_RETIRE",
                                feature,
                                rule,
                                rs,
                                persistence_minutes=0.0,
                                consecutive_matches=1,
                            )
                        )
                    else:
                        events.append(
                            _event(now, "ENTER_PROBATION", feature, rule, rs)
                        )
                continue

            # Bereits als WOULD_RETIRE markiert: weiterhin auf Recovery pruefen,
            # unabhaengig davon, ob die urspruengliche Rule aktuell noch gilt.
            if rs["status"] == "WOULD_RETIRE":
                if evaluate_recovery(rule, feature, rs.get("baseline", {})):
                    events.append(
                        _event(
                            now,
                            "RECOVERED",
                            feature,
                            rule,
                            rs,
                            minutes_after_would_retire=round(
                                (
                                    now
                                    - (_parse_iso(rs["would_retire_at"]) or now)
                                ).total_seconds()
                                / 60,
                                2,
                            ),
                        )
                    )
                    del rules_state[key]
                    continue

                would_at = _parse_iso(rs.get("would_retire_at"))
                elapsed_minutes = (
                    max((now - would_at).total_seconds() / 60, 0.0)
                    if would_at is not None
                    else 0.0
                )
                checked = set(rs.setdefault("checked_horizons", []))
                for horizon in horizons:
                    if elapsed_minutes >= horizon and horizon not in checked:
                        events.append(
                            _event(
                                now,
                                "OUTCOME_CHECK",
                                feature,
                                rule,
                                rs,
                                horizon_minutes=horizon,
                                recovered=False,
                            )
                        )
                        checked.add(horizon)
                rs["checked_horizons"] = sorted(checked)

                if elapsed_minutes >= max_horizon:
                    events.append(
                        _event(
                            now,
                            "STAYED_DEAD",
                            feature,
                            rule,
                            rs,
                            horizon_minutes=max_horizon,
                        )
                    )
                    del rules_state[key]
                continue

            # PROBATION.
            if not matches:
                events.append(
                    _event(now, "RULE_CLEARED", feature, rule, rs)
                )
                del rules_state[key]
                continue

            if continuity:
                rs["consecutive_matches"] = int(
                    rs.get("consecutive_matches", 0)
                ) + 1
            else:
                # Eine Beobachtungsluecke darf keine kuenstliche Persistenz
                # erzeugen.
                rs["first_match_at"] = now.isoformat()
                rs["consecutive_matches"] = 1

            rs["last_match_at"] = now.isoformat()
            first_match_at = _parse_iso(rs.get("first_match_at")) or now
            persistence_minutes = max(
                (now - first_match_at).total_seconds() / 60,
                0.0,
            )

            needed_minutes = float(rule.get("persistence_minutes", 0))
            needed_matches = int(rule.get("min_consecutive_matches", 1))
            if (
                persistence_minutes >= needed_minutes
                and rs["consecutive_matches"] >= needed_matches
            ):
                rs["status"] = "WOULD_RETIRE"
                rs["would_retire_at"] = now.isoformat()
                rs["baseline"] = compact_evidence(feature)
                rs["checked_horizons"] = []
                events.append(
                    _event(
                        now,
                        "WOULD_RETIRE",
                        feature,
                        rule,
                        rs,
                        persistence_minutes=round(persistence_minutes, 2),
                        consecutive_matches=rs["consecutive_matches"],
                    )
                )

        probation_count = 0
        would_retire_count = 0
        for token_mint, token in tokens.items():
            if token_mint in protected_mints:
                continue
            rs = token.get("rules", {}).get(key)
            if not rs:
                continue
            if rs.get("status") == "PROBATION":
                probation_count += 1
            elif rs.get("status") == "WOULD_RETIRE":
                would_retire_count += 1

        summaries.append(
            {
                "rule_key": key,
                "rule_id": rule["id"],
                "version": rule["version"],
                "current_match_count": matched_count,
                "probation_count": probation_count,
                "would_retire_count": would_retire_count,
            }
        )

    # Alte Rule-Fingerprints bleiben nur erhalten, wenn sie bereits eine
    # WOULD_RETIRE-Kohorte beobachten. PROBATION alter Konfigurationen wird
    # bei Regel-Aenderung verworfen.
    active_keys = {rule_key(rule) for rule in enabled_rules}
    for token in tokens.values():
        for key in list(token.get("rules", {})):
            if key not in active_keys:
                if token["rules"][key].get("status") == "PROBATION":
                    del token["rules"][key]

    return events, summaries


def annotate_policy_status(state: dict, config: dict, features: list[dict]) -> None:
    """Write the current policy state of each mint onto its feature row.

    The region snapshot picks this up, which is what lets the dashboard show
    retirement pressure per semantic region. Nothing is decided here.
    """
    protected_mints = set(config.get("protected_mints", []))
    active_keys = {
        rule_key(rule)
        for rule in config.get("rules", [])
        if rule.get("enabled", True)
    }
    tokens = state.get("tokens", {})

    for feature in features:
        mint = feature["mint"]
        status = "none"
        token = tokens.get(mint)
        if token and mint not in protected_mints:
            statuses = {
                rs.get("status")
                for key, rs in token.get("rules", {}).items()
                if key in active_keys
            }
            if "WOULD_RETIRE" in statuses:
                status = "would_retire"
            elif "PROBATION" in statuses:
                status = "probation"
        feature["policy_status"] = status


def current_policy_population_overlay(
    state: dict,
    features: list[dict],
    config: dict,
    distribution: dict,
) -> dict:
    """Current unique policy-state overlay for the SVG; no DB mutation."""
    feature_by_mint = {feature["mint"]: feature for feature in features}
    protected_mints = set(config.get("protected_mints", []))
    active_rule_ids = {
        rule_key(rule): rule["id"]
        for rule in config.get("rules", [])
        if rule.get("enabled", True)
    }

    would_retire_mints: set[str] = set()
    probation_mints: set[str] = set()
    by_rule: dict[str, int] = {rule_id: 0 for rule_id in active_rule_ids.values()}

    for mint, token in state.get("tokens", {}).items():
        if mint in protected_mints or mint not in feature_by_mint:
            continue
        for key, rs in token.get("rules", {}).items():
            rule_id = active_rule_ids.get(key)
            if not rule_id:
                continue
            status = rs.get("status")
            if status == "WOULD_RETIRE":
                would_retire_mints.add(mint)
                by_rule[rule_id] = by_rule.get(rule_id, 0) + 1
            elif status == "PROBATION":
                probation_mints.add(mint)

    density = distribution.get("joint_density", {})
    retire_cells: dict[tuple[int, int], int] = {}
    with_joint = 0
    x_lo = density.get("x_log_min")
    x_hi = density.get("x_log_max")
    y_lo = density.get("y_log_min")
    y_hi = density.get("y_log_max")
    x_bins = int(density.get("x_bins") or 0)
    y_bins = int(density.get("y_bins") or 0)

    if None not in (x_lo, x_hi, y_lo, y_hi) and x_bins and y_bins:
        for mint in would_retire_mints:
            feature = feature_by_mint[mint]
            mcap = feature.get("mcap")
            liquidity = feature.get("liquidity")
            if mcap is None or liquidity is None or mcap <= 0 or liquidity <= 0:
                continue
            x_log, y_log = math.log10(float(mcap)), math.log10(float(liquidity))
            if not (x_lo <= x_log <= x_hi and y_lo <= y_log <= y_hi):
                continue
            ix = min(x_bins - 1, max(0, int((x_log - x_lo) / (x_hi - x_lo) * x_bins)))
            iy = min(y_bins - 1, max(0, int((y_log - y_lo) / (y_hi - y_lo) * y_bins)))
            retire_cells[(ix, iy)] = retire_cells.get((ix, iy), 0) + 1
            with_joint += 1

    total = int(distribution.get("total_active_with_snapshot", 0))
    return {
        "would_retire_unique": len(would_retire_mints),
        "would_retire_pct_all": round(len(would_retire_mints) / total * 100, 3) if total else 0.0,
        "probation_unique": len(probation_mints),
        "probation_pct_all": round(len(probation_mints) / total * 100, 3) if total else 0.0,
        "would_retire_with_joint_values": with_joint,
        "would_retire_density_cells": [
            {"ix": ix, "iy": iy, "count": count}
            for (ix, iy), count in sorted(retire_cells.items())
        ],
        "rules": [
            {"rule_id": rule_id, "would_retire_count": count}
            for rule_id, count in sorted(by_rule.items(), key=lambda item: (-item[1], item[0]))
        ],
    }
