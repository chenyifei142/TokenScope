import os
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

os.environ["APPDATA"] = str(Path.cwd() / ".test-appdata")

from api.deepseek import APIError
from data.store import (
    ModelUsage,
    TokenData,
    months_for_activity,
    months_for_week,
    top_model_stats,
)
from decimal import Decimal


def payload(day, amount, model="deepseek-v4-pro"):
    item = {
        "model": model,
        "usage": [{"type": "RESPONSE_TOKEN", "amount": str(amount)}],
    }
    return {"total": [item], "days": [{"date": day, "data": [item]}]}


class StoreTests(unittest.TestCase):
    def setUp(self):
        TokenData._last_snapshot = None
        unsynced = patch("data.store.history.unsynced_months", return_value=[])
        self.unsynced_months = unsynced.start()
        self.addCleanup(unsynced.stop)
        save_usage = patch("data.store.history.save_usage")
        self.save_usage = save_usage.start()
        self.addCleanup(save_usage.stop)
        total_cost = patch("data.store.history.total_cost", return_value=Decimal("1.25"))
        total_cost.start()
        self.addCleanup(total_cost.stop)
        recent_daily = patch("data.store.history.recent_daily", return_value=[])
        recent_daily.start()
        self.addCleanup(recent_daily.stop)

    def test_months_for_cross_month_week(self):
        self.assertEqual(months_for_week(date(2026, 7, 3)), [(6, 2026), (7, 2026)])

    def test_activity_months_cover_full_heatmap_range(self):
        months = months_for_activity(date(2026, 7, 4))
        self.assertEqual(months[0], (7, 2026))
        self.assertEqual(months[-1], (7, 2025))

    @patch("data.store.ds.get_usage_cost")
    @patch("data.store.ds.get_usage_amount")
    @patch("data.store.ds.get_user_summary", return_value={})
    def test_recent_unsynced_months_are_backfilled_in_batches(
        self, _summary, amount, cost
    ):
        self.unsynced_months.return_value = [
            (7, 2026), (6, 2026), (5, 2026), (4, 2026)
        ]
        amount.side_effect = lambda month, year: payload(
            f"{year}-{month:02d}-01", month
        )
        cost.side_effect = lambda month, year: payload(
            f"{year}-{month:02d}-01", ".1"
        )

        TokenData.fetch(date(2026, 7, 15))

        expected = [(7, 2026), (6, 2026), (5, 2026)]
        self.assertEqual([call.args for call in amount.call_args_list], expected)
        self.assertEqual([call.args for call in cost.call_args_list], expected)
        self.assertEqual(
            self.save_usage.call_args.kwargs["synced_months"],
            [(6, 2026), (5, 2026)],
        )

    def test_dynamic_models_merge_remainder(self):
        stats = {
            "a": ModelUsage("a", 30, Decimal(".3")),
            "b": ModelUsage("b", 20, Decimal(".2")),
            "c": ModelUsage("c", 10, Decimal(".1")),
            "d": ModelUsage("d", 5, Decimal(".05")),
        }
        models = top_model_stats(stats)
        self.assertEqual([model.model for model in models], ["a", "b", "其他"])
        self.assertEqual(models[-1].tokens, 15)
        self.assertEqual(models[-1].cost_cny, Decimal(".15"))

    @patch("data.store.ds.get_usage_cost")
    @patch("data.store.ds.get_usage_amount")
    @patch("data.store.ds.get_user_summary")
    def test_cross_month_week_and_decimal_cost(self, summary, amount, cost):
        summary.return_value = {
            "normal_wallets": [{"currency": "CNY", "balance": "12.3", "token_estimation": "9"}],
            "monthly_costs": [{"amount": "1.2"}],
            "monthly_token_usage": "100",
        }
        amount.side_effect = [
            payload("2026-06-30", 10),
            {"total": payload("2026-07-03", 30)["total"], "days": [
                payload("2026-07-01", 20)["days"][0],
                payload("2026-07-03", 30)["days"][0],
            ]},
        ]
        cost.side_effect = [payload("2026-06-30", ".1"), payload("2026-07-03", ".23")]

        data = TokenData.fetch(date(2026, 7, 3))

        self.assertEqual(data.today_tokens, 30)
        self.assertEqual(data.weekly_tokens, 60)
        self.assertAlmostEqual(data.today_cost_cny, .23)
        self.assertAlmostEqual(data.weekly_cost_cny, .33)
        self.assertEqual(data.total_cost_cny, 1.25)
        self.assertEqual(data.status, "ok")
        self.assertEqual([call.args for call in amount.call_args_list], [(6, 2026), (7, 2026)])

    @patch("data.store.ds.get_usage_cost", side_effect=APIError("AUTH_EXPIRED", "cost", "凭证失效"))
    @patch("data.store.ds.get_usage_amount", return_value=payload("2026-07-15", 7))
    @patch("data.store.ds.get_user_summary", return_value={})
    def test_partial_failure_is_visible(self, _summary, _amount, _cost):
        data = TokenData.fetch(date(2026, 7, 15))
        self.assertEqual(data.status, "partial")
        self.assertTrue(data.is_stale)
        self.assertEqual(data.today_tokens, 7)
        self.assertEqual(data.errors[0].code, "AUTH_EXPIRED")

    @patch("data.store.ds.get_usage_cost")
    @patch("data.store.ds.get_usage_amount")
    @patch(
        "data.store.ds.get_user_summary",
        side_effect=APIError("RATE_LIMITED", "summary", "请求过于频繁"),
    )
    def test_rate_limit_stops_remaining_platform_requests(self, _summary, amount, cost):
        data = TokenData.fetch(date(2026, 7, 15))

        self.assertEqual(data.status, "error")
        self.assertEqual(data.errors[0].code, "RATE_LIMITED")
        amount.assert_not_called()
        cost.assert_not_called()

    @patch("data.store.ds.get_usage_cost")
    @patch("data.store.ds.get_usage_amount")
    @patch(
        "data.store.ds.get_user_summary",
        side_effect=APIError("PLATFORM_BLOCKED", "summary", "平台风控拒绝请求"),
    )
    def test_platform_block_stops_remaining_platform_requests(self, _summary, amount, cost):
        data = TokenData.fetch(date(2026, 7, 15))

        self.assertEqual(data.status, "error")
        self.assertEqual(data.errors[0].code, "PLATFORM_BLOCKED")
        amount.assert_not_called()
        cost.assert_not_called()

    @patch("data.store.ds.get_usage_cost")
    @patch("data.store.ds.get_usage_amount")
    @patch("data.store.ds.get_user_summary")
    def test_total_failure_retains_cache(self, summary, amount, cost):
        summary.return_value = {"normal_wallets": [{"currency": "CNY", "balance": "8"}]}
        amount.return_value = payload("2026-07-15", 7)
        cost.return_value = payload("2026-07-15", ".2")
        first = TokenData.fetch(date(2026, 7, 15))
        failure = APIError("NETWORK_TIMEOUT", "test", "连接超时")
        summary.side_effect = amount.side_effect = cost.side_effect = failure

        second = TokenData.fetch(date(2026, 7, 15))

        self.assertEqual(first.balance_cny, second.balance_cny)
        self.assertEqual(second.today_tokens, 7)
        self.assertEqual(second.status, "error")
        self.assertTrue(second.is_stale)

    @patch("data.store.ds.get_usage_cost", return_value={})
    @patch("data.store.ds.get_usage_amount")
    @patch("data.store.ds.get_user_summary", return_value={})
    def test_bad_usage_row_does_not_drop_batch(self, _summary, amount, _cost):
        amount.return_value = {
            "total": [],
            "days": [{"date": "2026-07-15", "data": [
                {"usage": [{"type": "RESPONSE_TOKEN", "amount": "bad"}]},
                {"usage": [{"type": "RESPONSE_TOKEN", "amount": "4"}]},
            ]}],
        }
        data = TokenData.fetch(date(2026, 7, 15))
        self.assertEqual(data.today_tokens, 4)


if __name__ == "__main__":
    unittest.main()
