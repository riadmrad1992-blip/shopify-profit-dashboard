"""Unit tests for the profit math. Run with:  python -m unittest discover -s tests -v"""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import metrics as m  # noqa: E402
import weekly_email as we  # noqa: E402

COSTS = {
    "products": {"Mug": 7.0, "Candle": 8.0},
    "prices": {"Mug": 22.0, "Candle": 28.0},
    "default_cost_pct": 0.35, "payment_fee_pct": 0.03, "payment_fee_fixed": 0.30,
}
DAY = date(2026, 10, 17)


def order(total, items, day="2026-10-17T12:00:00Z", refunded=0.0):
    return {"name": "#1", "processed_at": day, "total": total, "refunded": refunded,
            "items": [{"title": t, "quantity": q} for t, q in items]}


class CostTests(unittest.TestCase):
    def test_known_products_use_unit_cost(self):
        self.assertAlmostEqual(m.order_cogs(order(50, [("Mug", 1), ("Candle", 1)]), COSTS), 15.0)

    def test_unknown_product_uses_default_pct(self):
        self.assertAlmostEqual(m.order_cogs(order(100, [("Mystery", 1)]), COSTS), 35.0)

    def test_mixed_order_costs_the_unknown_part_by_pct(self):
        # Mug (22) known at 7; remaining 78 of value costed at 35%
        self.assertAlmostEqual(m.order_cogs(order(100, [("Mug", 1), ("Mystery", 1)]), COSTS), 7 + 78 * 0.35)

    def test_payment_fees(self):
        self.assertAlmostEqual(m.payment_fees(order(100, []), COSTS), 3.30)


class DailyTests(unittest.TestCase):
    def test_profit_and_ratios(self):
        rows = m.daily_metrics([order(50, [("Mug", 1), ("Candle", 1)])], {DAY: 10.0}, COSTS, DAY, 1)
        r = rows[0]
        # 50 revenue - 15 cogs - (1.50 + 0.30) fees - 10 ads
        self.assertAlmostEqual(r["profit"], 23.2)
        self.assertEqual(r["roas"], 5.0)
        self.assertEqual(r["cost_per_order"], 10.0)
        self.assertFalse(r["ad_spend_simulated"])

    def test_refunds_reduce_profit_and_set_rate(self):
        r = m.daily_metrics([order(100, [("Mystery", 1)], refunded=20)], {DAY: 0.0}, COSTS, DAY, 1)[0]
        self.assertEqual(r["refund_rate"], 0.2)
        self.assertAlmostEqual(r["net_revenue"], 80.0)

    def test_days_outside_window_are_ignored(self):
        rows = m.daily_metrics([order(100, [], day="2026-09-01T12:00:00Z")], {}, COSTS, DAY, 7)
        self.assertEqual(sum(r["orders"] for r in rows), 0)
        self.assertEqual(len(rows), 7)

    def test_store_timezone_moves_order_to_local_day(self):
        # 22:30 UTC on the 16th is 01:30 on the 17th in Beirut
        rows = m.daily_metrics([order(40, [], day="2026-10-16T22:30:00Z")], {}, COSTS, DAY, 2,
                               "Asia/Beirut", simulate_missing_spend=False)
        self.assertEqual([r["orders"] for r in rows], [0, 1])

    def test_simulated_spend_is_deterministic_and_flagged(self):
        a = m.daily_metrics([order(100, [])], {}, COSTS, DAY, 1)[0]
        b = m.daily_metrics([order(100, [])], {}, COSTS, DAY, 1)[0]
        self.assertEqual(a["ad_spend"], b["ad_spend"])
        self.assertTrue(a["ad_spend_simulated"])
        self.assertTrue(2.0 < a["roas"] < 5.0)


class SummaryTests(unittest.TestCase):
    def test_ratios_come_from_totals_not_averages(self):
        rows = [m.finish_row(DAY, {"orders": 1, "revenue": 100, "refunds": 0, "cogs": 0, "fees": 0}, 10),
                m.finish_row(DAY, {"orders": 1, "revenue": 10, "refunds": 0, "cogs": 0, "fees": 0}, 10)]
        s = m.summarize(rows)
        self.assertEqual(s["roas"], 5.5)  # 110 / 20, not the mean of 10x and 1x

    def test_change_handles_zero_base(self):
        self.assertIsNone(m.change(10, 0))
        self.assertEqual(m.change(15, 10), 0.5)


class EmailTests(unittest.TestCase):
    def test_email_contains_numbers_and_link(self):
        rows = [m.finish_row(DAY, {"orders": 2, "revenue": 200, "refunds": 0, "cogs": 50, "fees": 6}, 40)] * 14
        data = {"shop": "Demo", "currency": "USD", "days": [dict(r, date=f"2026-10-{i + 1:02d}") for i, r in enumerate(rows)],
                "summary": m.compare_periods(rows), "spend_simulated": True}
        subject, text, body = we.build_email(data, "https://example.com/dash/")
        self.assertIn("$1,400 revenue", subject)
        self.assertIn("https://example.com/dash/", body)
        self.assertIn("simulated", body)
        self.assertIn("ROAS: 5.00×", text)


if __name__ == "__main__":
    unittest.main()
