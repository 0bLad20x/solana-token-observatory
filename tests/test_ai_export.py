from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from diagnostics.ai_export import build_ai_analysis_bundle, write_ai_analysis_bundle


NOW = "2026-08-08T10:00:00+00:00"
RULE_KEY = "terminal@v1:abc123"


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class AiExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp.name)

        snapshot = {
            "schema_version": 2,
            "generated_at": NOW,
            "totals": {
                "tracked": 10,
                "known_mcap_liquidity": 8,
                "missing_mcap_or_liquidity": 2,
            },
            "dimensions": {},
            "breakdowns": {
                "launchpad": {"pump.fun": 10},
                "graduation": {"not_graduated": 10},
                "age": {"8_24h": 10},
                "holders": {"0_2": 8, "3_10": 2},
                "activity": {"unknown": 6, "dormant": 4},
                "policy": {"would_retire": 4, "none": 6},
            },
            "cells_schema": [
                "mcap_bucket",
                "liquidity_bucket",
                "holder_bucket",
                "age_bucket",
                "activity_bucket",
                "launchpad",
                "graduation",
                "policy_status",
                "count",
            ],
            "cells": [
                [
                    "2k_5k",
                    "2k_10k",
                    "0_2",
                    "8_24h",
                    "unknown",
                    "pump.fun",
                    "not_graduated",
                    "none",
                    6,
                ],
                [
                    "missing",
                    "under_1",
                    "0_2",
                    "8_24h",
                    "dormant",
                    "pump.fun",
                    "not_graduated",
                    "would_retire",
                    2,
                ],
                [
                    "2k_5k",
                    "2k_10k",
                    "3_10",
                    "8_24h",
                    "dormant",
                    "pump.fun",
                    "not_graduated",
                    "would_retire",
                    2,
                ],
            ],
        }
        report = {
            "generated_at": NOW,
            "context": {"total_tracked_mints": 10},
            "collector_health": {"healthy": True, "status": "healthy"},
            "technical_validation": {"status": "ok"},
            "population_distribution": {"total_active_with_snapshot": 10},
            "policy_simulation": {
                "rule_set_hash": "set-1",
                "mode": "shadow_only_no_database_mutation",
                "priority_cadences_seconds": {"p1": 60, "p2": 300, "p3": 3600},
                "instantaneous_match_allocation": {
                    "p1": 6,
                    "p2": 0,
                    "p3": 0,
                    "retire": 4,
                },
                "coverage": {"features": 10},
                "rules": [
                    {
                        "rule_key": RULE_KEY,
                        "rule_id": "terminal",
                        "current_match_count": 4,
                    }
                ],
            },
            "filter_evidence": {
                "mode": "stateful_shadow_actions",
                "allocation": {"p1": 6, "p2": 0, "p3": 0, "retire": 4},
                "rules": [
                    {
                        "rule_key": RULE_KEY,
                        "rule_id": "terminal",
                        "current_match_count": 4,
                        "probation_count": 0,
                        "applied_count": 4,
                    }
                ],
            },
            "decision_metrics": {},
            "categories": [],
            "cross_analysis": {},
            "performance": {},
        }
        flow = {
            "schema_version": 2,
            "generated_at": NOW,
            "coverage": {"sufficient_for_transitions": False},
            "regions": [
                {
                    "region": "2k_5k~2k_10k",
                    "label": "floor",
                    "baseline": 8,
                    "current": 8,
                    "moves_out": 2,
                    "transition_counts": {"improved": 1, "deteriorated": 1},
                }
            ],
            "transitions": [],
            "by_launchpad": [],
        }
        cohorts = {
            "schema_version": 2,
            "generated_at": NOW,
            "coverage": {"has_matured_outcomes": True},
            "cohorts": [
                {
                    "key": "floor",
                    "label": "floor",
                    "baseline_unique_mints": 8,
                    "unique_mints": 2,
                    "outcomes": [
                        {
                            "horizon_minutes": 30,
                            "n": 2,
                            "pct": {"same": 50.0, "improved": 50.0},
                        }
                    ],
                }
            ],
        }
        outcomes = {
            "schema_version": 2,
            "generated_at": NOW,
            "global": {"applied_unique_union": 999},
            "rules": [
                {
                    "rule_key": RULE_KEY,
                    "rule_id": "terminal",
                    "applied_unique_mints": 4,
                    "horizons": [
                        {
                            "horizon_minutes": 5,
                            "matured": 4,
                            "recovered": 0,
                            "recovery_rate_pct": 0.0,
                        }
                    ],
                },
                {
                    "rule_key": "legacy@v1:old",
                    "rule_id": "legacy",
                    "applied_unique_mints": 995,
                    "horizons": [],
                },
            ],
        }

        write_json(self.data_dir / "region_snapshot.json", snapshot)
        write_json(self.data_dir / "investigation_report.json", report)
        write_json(self.data_dir / "region_flow.json", flow)
        write_json(self.data_dir / "cohort_outcomes.json", cohorts)
        write_json(self.data_dir / "policy_outcomes.json", outcomes)
        write_json(self.data_dir / "policy_rules.json", {"schema_version": 2})

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_bundle_has_seven_phases_and_excludes_legacy_outcomes(self):
        bundle = build_ai_analysis_bundle(
            data_dir=self.data_dir,
            exported_at=datetime(2026, 8, 8, 10, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(len(bundle["phases"]), 7)
        lab = bundle["phases"]["phase_7_policy_lab"]
        self.assertEqual(len(lab["active_rule_outcomes"]), 1)
        self.assertEqual(lab["excluded_legacy_rule_versions"], 1)
        interval = lab["active_rule_outcomes"][0]["horizons"][0][
            "recovery_rate_wilson_95_pct"
        ]
        self.assertEqual(interval["low_pct"], 0.0)
        self.assertGreater(interval["high_pct"], 0.0)
        self.assertEqual(lab["rule_readiness"][0]["status"], "evidence_available")

    def test_denominators_and_polling_projection_are_explicit(self):
        bundle = build_ai_analysis_bundle(data_dir=self.data_dir)

        region = bundle["phases"]["phase_2_region_flow"]["derived"][
            "population_normalized_regions"
        ][0]
        self.assertEqual(region["improved_among_exits_pct"], 50.0)
        self.assertEqual(region["improved_population_share_pct"], 12.5)
        activity = bundle["phases"]["phase_4_activity"]["derived"]["coverage"]
        self.assertEqual(activity["known_pct"], 40.0)
        load = bundle["executive_facts"]["polling_load_projection"]
        self.assertEqual(load["load_reduction_pct"], 40.0)
        self.assertFalse(bundle["interpretation_contract"]["missing_is_zero"])

    def test_writer_creates_one_stable_json(self):
        output = Path(self.temp.name) / "analysis" / "diagnostics_ai_bundle.json"
        write_ai_analysis_bundle(data_dir=self.data_dir, output_path=output)
        first = json.loads(output.read_text(encoding="utf-8"))
        write_ai_analysis_bundle(data_dir=self.data_dir, output_path=output)
        second = json.loads(output.read_text(encoding="utf-8"))

        self.assertTrue(output.exists())
        self.assertEqual(first["schema_version"], second["schema_version"])
        self.assertEqual(first["executive_facts"], second["executive_facts"])
        self.assertEqual(list(output.parent.glob("*.json")), [output])


if __name__ == "__main__":
    unittest.main()
