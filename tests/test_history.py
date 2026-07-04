import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

os.environ["APPDATA"] = str(Path.cwd() / ".test-appdata")

from data import history


def payload(day, amount):
    return {"days": [{"date": day, "data": [{
        "model": "deepseek-test",
        "usage": [{"type": "RESPONSE_TOKEN", "amount": str(amount)}],
    }]}]}


class HistoryTests(unittest.TestCase):
    def test_save_and_read_normalized_daily_usage(self):
        Path("C:/tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir="C:/tmp") as directory:
            with patch.object(history, "DB_PATH", Path(directory) / "usage.db"):
                self.assertTrue(history.needs_initial_sync())
                self.assertEqual(
                    history.unsynced_months([(5, 2026), (4, 2026)]),
                    [(5, 2026), (4, 2026)],
                )
                history.save_usage(
                    [payload("2099-01-01", 12)],
                    [payload("2099-01-01", ".125")],
                    synced_months=[(5, 2026)],
                )
                self.assertFalse(history.needs_initial_sync())
                self.assertEqual(
                    history.unsynced_months([(5, 2026), (4, 2026)]),
                    [(4, 2026)],
                )
                history.save_usage([], [], synced_months=[(4, 2026)])
                self.assertEqual(
                    history.unsynced_months([(5, 2026), (4, 2026)]), []
                )
                self.assertEqual(history.total_cost(), Decimal(".125"))
                rows = history.recent_daily(30_000)
        self.assertEqual(rows[0]["tokens"], 12)
        self.assertEqual(str(rows[0]["cost_cny"]), "0.125")


if __name__ == "__main__":
    unittest.main()
