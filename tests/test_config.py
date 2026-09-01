from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import Settings


class SettingsTests(unittest.TestCase):
    def test_comma_separated_search_keys_match_env_example(self):
        env = {
            "DATABASE_URL": "postgresql://postgres:password@127.0.0.1:5432/test",
            "JUPITER_SEARCH_API_KEYS": "key1, key2",
            "JUPITER_RECENT_API_KEY": "recent-key",
            "PUMPPORTAL_API_KEY": "pump-key",
        }

        with patch.dict(os.environ, env, clear=True), patch("config.load_dotenv"):
            settings = Settings.from_env()

        self.assertEqual(settings.jupiter_search_api_keys, ["key1", "key2"])


if __name__ == "__main__":
    unittest.main()
