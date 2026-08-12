from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from observatory.model_policy import ModelPolicy


class ModelPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = ModelPolicy(fast_model="fast-model", strong_model="strong-model")

    def test_current_data_uses_fast_model(self) -> None:
        self.assertEqual(self.policy.tier_for("current_data"), "fast")
        self.assertEqual(self.policy.model_for("current_data"), "fast-model")

    def test_interpretive_scopes_use_strong_model(self) -> None:
        for scope in ("web", "temporal", "rugcheck"):
            with self.subTest(scope=scope):
                self.assertEqual(self.policy.tier_for(scope), "strong")
                self.assertEqual(self.policy.model_for(scope), "strong-model")

    def test_empty_models_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ModelPolicy(fast_model="", strong_model="strong")
        with self.assertRaises(ValueError):
            ModelPolicy(fast_model="fast", strong_model=" ")


if __name__ == "__main__":
    unittest.main()
