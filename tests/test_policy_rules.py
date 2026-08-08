from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from diagnostics.constants import DEFAULT_POLICY_CONFIG
from diagnostics.policy import advance_policy_state, evaluate_rule, rule_key


def rule(rule_id: str) -> dict:
    return deepcopy(next(row for row in DEFAULT_POLICY_CONFIG["rules"] if row["id"] == rule_id))


def feature(**changes) -> dict:
    now = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    row = {
        "mint": "test-mint", "name": "Test", "symbol": "TST",
        "launchpad": "pump", "is_graduated": False,
        "age_minutes": 6.0, "unchanged_minutes": 5.0,
        "poll_age_seconds": 10.0, "last_polled_at": now,
        "latest_observed_at": now, "has_mcap": True, "mcap": 2200.0,
        "peak_mcap": 4500.0, "mcap_drop_pct": 51.1,
        "has_liquidity": True, "liquidity": 2500.0,
        "peak_liquidity": 4000.0, "liquidity_drop_pct": 37.5,
        "has_holder_count": True, "holders": 2, "peak_holders": 3,
        "holder_retention_pct": 66.7, "has_stats5m": False,
        "stats5m_num_buys": None, "stats5m_num_sells": None,
        "stats5m_buy_volume": None, "stats5m_sell_volume": None,
        "activity_extinguished": False, "snapshot_count": 3,
        "gmgn_available": False,
    }
    row.update(changes)
    return row


class RuleTests(unittest.TestCase):
    def test_failed_at_birth_needs_no_activity_window(self):
        self.assertTrue(evaluate_rule(rule("failed_at_birth_floor"), feature(age_minutes=1.0)))

    def test_missing_stats_are_unknown_until_activity_was_seen(self):
        candidate = feature(age_minutes=3.0, holders=3)
        self.assertFalse(evaluate_rule(rule("early_floor_uncertain_p2"), candidate))
        candidate["activity_extinguished"] = True
        self.assertTrue(evaluate_rule(rule("early_floor_uncertain_p2"), candidate))

    def test_removed_liquidity_is_immediate_terminal_evidence(self):
        candidate = feature(
            age_minutes=200, mcap=None, has_mcap=False, liquidity=0.0,
            peak_liquidity=50000.0, liquidity_drop_pct=100.0,
        )
        self.assertTrue(evaluate_rule(rule("liquidity_removed_hard"), candidate))

    def test_return_from_real_peak_to_floor(self):
        candidate = feature(
            age_minutes=15, mcap=2300, peak_mcap=22300,
            mcap_drop_pct=89.7, liquidity=4700, holders=13,
            peak_holders=177, holder_retention_pct=7.35,
            has_stats5m=True, stats5m_num_buys=0,
            stats5m_num_sells=0, stats5m_buy_volume=0.0,
            stats5m_sell_volume=0.0,
        )
        self.assertTrue(evaluate_rule(rule("pre_migration_return_to_floor"), candidate))

    def test_poll_confirmation_uses_per_mint_last_polled_at(self):
        selected = rule("micro_pool_exhausted")
        selected["persistence_minutes"] = 0
        config = deepcopy(DEFAULT_POLICY_CONFIG)
        config["rules"] = [selected]
        state = {"schema_version": 2, "last_healthy_run_at": None, "tokens": {}}
        start = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
        candidate = feature(
            age_minutes=10, liquidity=50, holders=2,
            has_stats5m=True, stats5m_num_buys=0,
            stats5m_num_sells=0, stats5m_buy_volume=0.0,
            stats5m_sell_volume=0.0, last_polled_at=start,
        )

        advance_policy_state(state, config, [candidate], start, 60, True)
        key = rule_key(selected)
        self.assertEqual(state["tokens"]["test-mint"]["rules"][key]["poll_confirmations"], 1)
        self.assertEqual(state["tokens"]["test-mint"]["rules"][key]["status"], "PROBATION")

        # A monitor cycle without a new successful mint poll confirms nothing.
        advance_policy_state(state, config, [candidate], start + timedelta(minutes=1), 60, True)
        self.assertEqual(state["tokens"]["test-mint"]["rules"][key]["poll_confirmations"], 1)
        self.assertEqual(state["tokens"]["test-mint"]["rules"][key]["status"], "PROBATION")

        # Same payload is fine: only last_polled_at has to advance.
        candidate["last_polled_at"] = start + timedelta(minutes=2)
        events, _ = advance_policy_state(
            state, config, [candidate], start + timedelta(minutes=2), 60, True
        )
        self.assertEqual(state["tokens"]["test-mint"]["rules"][key]["status"], "APPLIED")
        self.assertTrue(any(row["event"] == "WOULD_RETIRE" for row in events))


if __name__ == "__main__":
    unittest.main()
