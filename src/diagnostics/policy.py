from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .constants import (
    DEFAULT_POLICY_CONFIG,
    POLICY_RULES_PATH,
    POLICY_STATE_PATH,
    SAMPLE_LIMIT,
)
from .storage import atomic_write_json


ACTION_PRIORITY = {"p1": 0, "p2": 1, "p3": 2, "retire": 3}


def load_policy_config() -> dict:
    """Load the shadow-filter rules; no rule writes to the database."""
    if not POLICY_RULES_PATH.exists():
        atomic_write_json(POLICY_RULES_PATH, DEFAULT_POLICY_CONFIG)

    try:
        config = json.loads(POLICY_RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Policy-Konfiguration unlesbar: {POLICY_RULES_PATH}: {exc}"
        ) from exc

    if config.get("schema_version") != 2:
        raise RuntimeError(
            "policy_rules.json: schema_version muss 2 sein. "
            "Die neue Datei aus data/policy_rules.json uebernehmen."
        )
    if not isinstance(config.get("collector_health"), dict):
        raise RuntimeError("policy_rules.json: collector_health fehlt")
    if not isinstance(config.get("rules"), list):
        raise RuntimeError("policy_rules.json: rules muss eine Liste sein")

    seen_ids: set[str] = set()
    for rule in config["rules"]:
        if not isinstance(rule, dict):
            raise RuntimeError("policy_rules.json: jede Rule muss ein Objekt sein")
        for required in (
            "id", "version", "type", "action", "confirmation", "thresholds"
        ):
            if required not in rule:
                raise RuntimeError(f"policy_rules.json: Rule ohne {required}")
        if rule["action"] not in {"p2", "p3", "retire"}:
            raise RuntimeError(
                f"policy_rules.json: ungueltige Action {rule['action']}"
            )
        if rule["confirmation"] not in {"immediate", "poll_confirmed"}:
            raise RuntimeError(
                f"policy_rules.json: ungueltige Confirmation {rule['confirmation']}"
            )
        rule_id = str(rule["id"])
        if rule_id in seen_ids:
            raise RuntimeError(f"policy_rules.json: doppelte Rule-ID: {rule_id}")
        seen_ids.add(rule_id)
    return config


def policy_config_hash(config: dict) -> str:
    raw = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def rule_key(rule: dict) -> str:
    raw = json.dumps(rule, sort_keys=True, separators=(",", ":")).encode()
    return f"{rule['id']}@v{rule['version']}:{hashlib.sha256(raw).hexdigest()[:10]}"


def _at_least(value: float | int | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def _at_most(value: float | int | None, threshold: float) -> bool:
    return value is not None and value <= threshold


def _recent_activity_at_most(feature: dict, field: str, threshold: float) -> bool:
    """Missing recent stats are only zero after earlier activity was observed."""
    if feature.get("has_stats5m"):
        return _at_most(feature.get(field), threshold)
    if feature.get("activity_extinguished"):
        return 0 <= threshold
    return False


def _common_thresholds(thresholds: dict, feature: dict) -> bool:
    if not _at_least(
        feature.get("age_minutes"), float(thresholds.get("min_age_minutes", 0))
    ):
        return False
    if "max_age_minutes" in thresholds and not _at_most(
        feature.get("age_minutes"), float(thresholds["max_age_minutes"])
    ):
        return False
    if not _at_least(
        feature.get("unchanged_minutes"),
        float(thresholds.get("min_unchanged_minutes", 0)),
    ):
        return False
    if "max_poll_age_seconds" in thresholds and not _at_most(
        feature.get("poll_age_seconds"),
        float(thresholds["max_poll_age_seconds"]),
    ):
        return False
    return True


def _floor_bounds(thresholds: dict, feature: dict) -> bool:
    mcap = feature.get("mcap")
    liquidity = feature.get("liquidity")
    if "min_current_mcap" in thresholds and not _at_least(
        mcap, float(thresholds["min_current_mcap"])
    ):
        return False
    if "max_current_mcap" in thresholds and not _at_most(
        mcap, float(thresholds["max_current_mcap"])
    ):
        return False
    if "min_current_liquidity" in thresholds and not _at_least(
        liquidity, float(thresholds["min_current_liquidity"])
    ):
        return False
    if "max_current_liquidity" in thresholds and not _at_most(
        liquidity, float(thresholds["max_current_liquidity"])
    ):
        return False
    if "max_holders" in thresholds and not _at_most(
        feature.get("holders"), float(thresholds["max_holders"])
    ):
        return False
    return True


def _activity_bounds(thresholds: dict, feature: dict) -> bool:
    if "max_stats5m_buys" in thresholds and not _recent_activity_at_most(
        feature, "stats5m_num_buys", float(thresholds["max_stats5m_buys"])
    ):
        return False
    if "max_stats5m_buy_volume" in thresholds and not _recent_activity_at_most(
        feature, "stats5m_buy_volume", float(thresholds["max_stats5m_buy_volume"])
    ):
        return False
    return True


def evaluate_rule(rule: dict, feature: dict) -> bool:
    """Evaluate absolute lifecycle evidence; unknown values never become zero."""
    if not rule.get("enabled", True):
        return False
    thresholds = rule["thresholds"]
    if not _common_thresholds(thresholds, feature):
        return False

    rule_type = rule["type"]
    if rule_type == "terminal_liquidity_collapse":
        return (
            feature.get("has_liquidity")
            and _at_least(feature.get("peak_liquidity"), float(thresholds["min_peak_liquidity"]))
            and _at_most(feature.get("liquidity"), float(thresholds["max_current_liquidity"]))
            and _at_least(feature.get("liquidity_drop_pct"), float(thresholds["min_liquidity_drop_pct"]))
            and (
                feature.get("mcap") is None
                or _at_most(feature.get("mcap"), float(thresholds["max_current_mcap_or_null"]))
            )
        )

    if rule_type == "failed_at_birth":
        return (
            not feature.get("is_graduated")
            and _floor_bounds(thresholds, feature)
            and _at_most(feature.get("peak_mcap"), float(thresholds["max_peak_mcap"]))
        )

    if rule_type == "floor_low_signal":
        return (
            not feature.get("is_graduated")
            and _floor_bounds(thresholds, feature)
            and _activity_bounds(thresholds, feature)
        )

    if rule_type == "pre_migration_floor_return":
        holder_condition = _at_most(
            feature.get("holder_retention_pct"),
            float(thresholds["max_holder_retention_pct"]),
        ) or _at_most(
            feature.get("holders"),
            float(thresholds["max_holders_without_retention"]),
        )
        return (
            not feature.get("is_graduated")
            and _floor_bounds(thresholds, feature)
            and _at_least(feature.get("peak_mcap"), float(thresholds["min_peak_mcap"]))
            and _at_least(feature.get("mcap_drop_pct"), float(thresholds["min_mcap_drop_pct"]))
            and holder_condition
            and _activity_bounds(thresholds, feature)
        )

    if rule_type in {"micro_pool_exhausted", "graveyard_stalled"}:
        return (
            not feature.get("is_graduated")
            and _floor_bounds(thresholds, feature)
            and _activity_bounds(thresholds, feature)
        )

    raise RuntimeError(f"Unbekannter Rule-Typ: {rule_type}")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def compact_evidence(feature: dict) -> dict:
    keys = (
        "name", "symbol", "launchpad", "is_graduated", "age_minutes",
        "unchanged_minutes", "poll_age_seconds", "mcap", "peak_mcap",
        "mcap_drop_pct", "liquidity", "peak_liquidity", "liquidity_drop_pct",
        "holders", "peak_holders", "holder_retention_pct", "has_stats5m",
        "stats5m_num_buys", "stats5m_num_sells", "stats5m_buy_volume",
        "stats5m_sell_volume", "activity_extinguished", "snapshot_count",
        "last_polled_at", "latest_observed_at", "audit_is_sus",
        "audit_dev_mints", "audit_dev_migrations", "audit_dev_balance_pct",
        "gmgn_available", "gmgn_observed_at", "gmgn_age_minutes",
        "gmgn_market_cap", "gmgn_liquidity", "gmgn_holder_count",
        "gmgn_rug_ratio", "gmgn_creator_token_status",
        "gmgn_creator_created_count", "gmgn_creator_created_open_ratio",
        "gmgn_is_honeypot", "gmgn_is_wash_trading", "gmgn_has_social",
    )
    result = {key: feature.get(key) for key in keys}
    for key, value in list(result.items()):
        if isinstance(value, float):
            result[key] = round(value, 6)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
    return result


def _strongest_action(actions: list[str]) -> str:
    return max(actions, key=lambda action: ACTION_PRIORITY[action], default="p1")


def current_policy_simulation(config: dict, features: list[dict]) -> dict:
    protected = set(config.get("protected_mints", []))
    rows: list[dict] = []
    matches_by_mint: dict[str, list[str]] = {}
    gmgn_coverage = sum(bool(feature.get("gmgn_available")) for feature in features)

    for rule in config["rules"]:
        if not rule.get("enabled", True):
            continue
        matches = [
            feature for feature in features
            if feature["mint"] not in protected and evaluate_rule(rule, feature)
        ]
        for feature in matches:
            matches_by_mint.setdefault(feature["mint"], []).append(rule["action"])
        rows.append(
            {
                "rule_key": rule_key(rule),
                "rule_id": rule["id"],
                "version": rule["version"],
                "type": rule["type"],
                "action": rule["action"],
                "confirmation": rule["confirmation"],
                "persistence_minutes": rule.get("persistence_minutes", 0),
                "min_poll_confirmations": rule.get("min_poll_confirmations", 1),
                "current_match_count": len(matches),
                "gmgn_available_in_matches": sum(
                    bool(feature.get("gmgn_available")) for feature in matches
                ),
                "samples": [
                    {"mint": feature["mint"], "evidence": compact_evidence(feature)}
                    for feature in matches[:SAMPLE_LIMIT]
                ],
            }
        )

    allocation = {"p1": 0, "p2": 0, "p3": 0, "retire": 0}
    for feature in features:
        action = _strongest_action(matches_by_mint.get(feature["mint"], []))
        allocation[action] += 1
    return {
        "rule_set_hash": policy_config_hash(config),
        "mode": "shadow_only_no_database_mutation",
        "priority_cadences_seconds": config.get("priority_cadences_seconds", {}),
        "protected_mints": sorted(protected),
        "coverage": {
            "features": len(features),
            "gmgn_latest_available": gmgn_coverage,
            "gmgn_coverage_pct": round(gmgn_coverage / len(features) * 100, 3)
            if features else 0.0,
        },
        "instantaneous_match_allocation": allocation,
        "rules": rows,
    }


def load_monitor_state() -> dict:
    if not POLICY_STATE_PATH.exists():
        return {"schema_version": 2, "last_healthy_run_at": None, "tokens": {}}
    try:
        state = json.loads(POLICY_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Monitor-State unlesbar: {POLICY_STATE_PATH}: {exc}") from exc
    if state.get("schema_version") == 1:
        # Old rule state has global-run confirmations and is unsafe to reuse.
        state = {"schema_version": 2, "last_healthy_run_at": None, "tokens": {}}
    if state.get("schema_version") != 2:
        raise RuntimeError("policy_state.json: unbekannte schema_version")
    state.setdefault("last_healthy_run_at", None)
    state.setdefault("tokens", {})
    return state


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return None
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def update_monitor_token_metrics(
    state: dict,
    features: list[dict],
    now: datetime,
    interval_seconds: int,
) -> bool:
    """Maintain diagnostics-only state; continuity never confirms a token rule."""
    last = _parse_iso(state.get("last_healthy_run_at"))
    continuity = last is not None and 0 <= (now - last).total_seconds() <= interval_seconds * 2.5
    for feature in features:
        token = state["tokens"].setdefault(feature["mint"], {"rules": {}})
        token["last_seen_at"] = now.isoformat()
        token["last_polled_at"] = _iso(feature.get("last_polled_at"))
    state["last_healthy_run_at"] = now.isoformat()
    return continuity


def prospective_monitor_metrics(features: list[dict]) -> dict:
    result = {"fresh_poll_under_60s": 0, "poll_1_5m": 0, "poll_over_5m": 0, "never_polled": 0}
    for feature in features:
        age = feature.get("poll_age_seconds")
        if age is None:
            result["never_polled"] += 1
        elif age <= 60:
            result["fresh_poll_under_60s"] += 1
        elif age <= 300:
            result["poll_1_5m"] += 1
        else:
            result["poll_over_5m"] += 1
    return result


def _event(now, name, feature, rule, rs, **extra) -> dict:
    payload = {
        "timestamp": now.isoformat(), "event": name, "mint": feature["mint"],
        "rule_key": rule_key(rule), "rule_id": rule["id"],
        "rule_version": rule["version"], "rule_type": rule["type"],
        "action": rule["action"], "recommended_priority": rule["action"],
        "evidence": compact_evidence(feature),
        "first_match_at": rs.get("first_match_at"),
        "applied_at": rs.get("applied_at"),
        # Kept for old outcome readers while schema-2 readers use applied_at.
        "would_retire_at": rs.get("applied_at") if rule["action"] == "retire" else None,
    }
    payload.update(extra)
    return payload


def _apply_event_name(action: str) -> str:
    return "WOULD_RETIRE" if action == "retire" else "WOULD_DEMOTE"


def _poll_advanced(feature: dict, rs: dict) -> bool:
    current = feature.get("last_polled_at")
    if current is None:
        return False
    previous = _parse_iso(rs.get("last_confirmed_poll_at"))
    return previous is None or current > previous


def _outcome_flags(config: dict, feature: dict, baseline: dict) -> dict:
    thresholds = config.get("outcome_thresholds", {})
    mcap = feature.get("mcap")
    liquidity = feature.get("liquidity")
    min_liq = float(thresholds.get("min_recovery_liquidity", 1000))
    weak = _at_least(mcap, float(thresholds.get("weak_escape_mcap", 10000)))
    relevant = _at_least(mcap, float(thresholds.get("relevant_escape_mcap", 50000)))
    success = _at_least(mcap, float(thresholds.get("success_mcap", 200000)))
    newly_graduated = not baseline.get("is_graduated") and bool(feature.get("is_graduated"))
    meaningful = bool(
        _at_least(liquidity, min_liq) and (relevant or newly_graduated)
    )
    return {
        "reached_10k": weak,
        "reached_50k": relevant,
        "reached_200k": success,
        "graduated_after_action": newly_graduated,
        "meaningful_recovery": meaningful,
    }


def advance_policy_state(
    state: dict,
    config: dict,
    features: list[dict],
    now: datetime,
    interval_seconds: int,
    continuity: bool,
) -> tuple[list[dict], list[dict]]:
    """Advance shadow decisions. No SQL UPDATE and no persistent DB table."""
    del interval_seconds, continuity  # confirmation is deliberately per mint/poll
    protected = set(config.get("protected_mints", []))
    feature_by_mint = {row["mint"]: row for row in features}
    events: list[dict] = []
    summaries: list[dict] = []
    rules = [rule for rule in config["rules"] if rule.get("enabled", True)]
    horizons = sorted(set(int(v) for v in config.get("outcome_horizons_minutes", [5, 15, 30, 60, 360, 1440])))
    max_horizon = max(horizons, default=1440)

    for rule in rules:
        key = rule_key(rule)
        matched_count = 0
        for mint, feature in feature_by_mint.items():
            if mint in protected:
                continue
            token = state["tokens"].setdefault(mint, {"rules": {}})
            rules_state = token.setdefault("rules", {})
            rs = rules_state.get(key)
            matches = evaluate_rule(rule, feature)
            matched_count += int(matches)

            if rs and rs.get("status") == "APPLIED":
                applied_at = _parse_iso(rs.get("applied_at")) or now
                elapsed = max((now - applied_at).total_seconds() / 60, 0.0)
                flags = _outcome_flags(config, feature, rs.get("baseline", {}))
                milestones = rs.setdefault("milestones", {})
                for flag in ("reached_10k", "reached_50k", "reached_200k", "graduated_after_action"):
                    if flags[flag] and not milestones.get(flag):
                        milestones[flag] = now.isoformat()
                        events.append(_event(now, "OUTCOME_MILESTONE", feature, rule, rs, milestone=flag, minutes_after_action=round(elapsed, 2)))
                if flags["meaningful_recovery"] and not rs.get("recovered_at"):
                    rs["recovered_at"] = now.isoformat()
                    events.append(_event(now, "RECOVERED", feature, rule, rs, minutes_after_action=round(elapsed, 2)))
                checked = set(rs.setdefault("checked_horizons", []))
                for horizon in horizons:
                    if elapsed >= horizon and horizon not in checked:
                        events.append(_event(now, "OUTCOME_CHECK", feature, rule, rs, horizon_minutes=horizon, recovered=bool(rs.get("recovered_at")), **flags))
                        checked.add(horizon)
                rs["checked_horizons"] = sorted(checked)
                if elapsed >= max_horizon:
                    if not rs.get("recovered_at"):
                        events.append(_event(now, "STAYED_DEAD", feature, rule, rs, horizon_minutes=max_horizon))
                    del rules_state[key]
                continue

            if not matches:
                if rs:
                    events.append(_event(now, "RULE_CLEARED", feature, rule, rs))
                    del rules_state[key]
                continue

            if rs is None:
                rs = {
                    "status": "PROBATION",
                    "first_match_at": now.isoformat(),
                    "last_match_at": now.isoformat(),
                    "poll_confirmations": 0,
                    "last_confirmed_poll_at": None,
                    "applied_at": None,
                    "baseline": None,
                    "checked_horizons": [],
                    "milestones": {},
                }
                rules_state[key] = rs
                events.append(_event(now, "ENTER_PROBATION", feature, rule, rs))

            if _poll_advanced(feature, rs):
                rs["poll_confirmations"] = int(rs.get("poll_confirmations", 0)) + 1
                rs["last_confirmed_poll_at"] = _iso(feature.get("last_polled_at"))
            rs["last_match_at"] = now.isoformat()
            first = _parse_iso(rs.get("first_match_at")) or now
            persistence = max((now - first).total_seconds() / 60, 0.0)
            enough_polls = int(rs.get("poll_confirmations", 0)) >= int(rule.get("min_poll_confirmations", 1))
            enough_time = persistence >= float(rule.get("persistence_minutes", 0))
            immediate = rule.get("confirmation") == "immediate"
            if enough_time and (immediate or enough_polls):
                rs["status"] = "APPLIED"
                rs["applied_at"] = now.isoformat()
                rs["baseline"] = compact_evidence(feature)
                events.append(_event(now, _apply_event_name(rule["action"]), feature, rule, rs, persistence_minutes=round(persistence, 2), poll_confirmations=rs["poll_confirmations"]))

        counts = {"PROBATION": 0, "APPLIED": 0}
        for mint, token in state["tokens"].items():
            if mint in protected:
                continue
            rs = token.get("rules", {}).get(key)
            if rs and rs.get("status") in counts:
                counts[rs["status"]] += 1
        summaries.append({
            "rule_key": key, "rule_id": rule["id"], "version": rule["version"],
            "action": rule["action"], "confirmation": rule["confirmation"],
            "current_match_count": matched_count,
            "probation_count": counts["PROBATION"],
            "applied_count": counts["APPLIED"],
            "would_retire_count": counts["APPLIED"] if rule["action"] == "retire" else 0,
        })

    active_keys = {rule_key(rule) for rule in rules}
    for token in state["tokens"].values():
        for key in list(token.get("rules", {})):
            if key not in active_keys and token["rules"][key].get("status") == "PROBATION":
                del token["rules"][key]
    return events, summaries


def annotate_policy_status(state: dict, config: dict, features: list[dict]) -> None:
    protected = set(config.get("protected_mints", []))
    rules_by_key = {rule_key(rule): rule for rule in config["rules"] if rule.get("enabled", True)}
    for feature in features:
        actions: list[str] = []
        probation = False
        token = state.get("tokens", {}).get(feature["mint"], {})
        if feature["mint"] not in protected:
            for key, rs in token.get("rules", {}).items():
                rule = rules_by_key.get(key)
                if not rule:
                    continue
                if rs.get("status") == "APPLIED":
                    actions.append(rule["action"])
                elif rs.get("status") == "PROBATION":
                    probation = True
        priority = _strongest_action(actions)
        feature["recommended_priority"] = priority
        feature["policy_status"] = (
            "would_retire" if priority == "retire"
            else "would_demote" if priority in {"p2", "p3"}
            else "probation" if probation else "none"
        )


def build_filter_evidence(state: dict, config: dict, features: list[dict], summaries: list[dict]) -> dict:
    allocation = {"p1": 0, "p2": 0, "p3": 0, "retire": 0}
    reasons: dict[str, int] = {}
    samples: list[dict] = []
    rules_by_key = {rule_key(rule): rule for rule in config["rules"] if rule.get("enabled", True)}
    for feature in features:
        allocation[feature.get("recommended_priority", "p1")] += 1
        token = state.get("tokens", {}).get(feature["mint"], {})
        applied = []
        for key, rs in token.get("rules", {}).items():
            rule = rules_by_key.get(key)
            if rule and rs.get("status") == "APPLIED":
                reasons[rule["id"]] = reasons.get(rule["id"], 0) + 1
                applied.append(rule["id"])
        if applied and len(samples) < 25:
            samples.append({
                "mint": feature["mint"], "name": feature.get("name"),
                "symbol": feature.get("symbol"),
                "recommended_priority": feature.get("recommended_priority"),
                "rules": applied, "evidence": compact_evidence(feature),
            })
    total = len(features)
    return {
        "mode": "shadow_only_no_database_mutation",
        "total_active": total,
        "allocation": allocation,
        "allocation_pct": {key: round(value / total * 100, 3) if total else 0.0 for key, value in allocation.items()},
        "priority_cadences_seconds": config.get("priority_cadences_seconds", {}),
        "reason_counts": [{"rule_id": key, "count": value} for key, value in sorted(reasons.items(), key=lambda row: (-row[1], row[0]))],
        "rules": summaries,
        "candidate_samples": samples,
    }


def current_policy_population_overlay(state: dict, features: list[dict], config: dict, distribution: dict) -> dict:
    del distribution
    annotate_policy_status(state, config, features)
    allocation = {"p1": 0, "p2": 0, "p3": 0, "retire": 0}
    probation = 0
    for feature in features:
        allocation[feature.get("recommended_priority", "p1")] += 1
        probation += int(feature.get("policy_status") == "probation")
    total = len(features)
    return {
        "would_retire_unique": allocation["retire"],
        "would_retire_pct_all": round(allocation["retire"] / total * 100, 3) if total else 0.0,
        "probation_unique": probation,
        "probation_pct_all": round(probation / total * 100, 3) if total else 0.0,
        "priority_allocation": allocation,
        "priority_allocation_pct": {key: round(value / total * 100, 3) if total else 0.0 for key, value in allocation.items()},
        "would_retire_with_joint_values": 0,
        "would_retire_density_cells": [],
        "rules": [],
    }
