import unittest

from rules import build_strikes, calculate_credit_metrics, nearest_grid


class SandwichRuleTests(unittest.TestCase):
    def test_strikes_round_to_nearest_five_grid(self):
        self.assertEqual(nearest_grid(7701.34), 7700)
        self.assertEqual(build_strikes(7701.34), build_strikes(7700))
        self.assertEqual(build_strikes(7701.34).long_put, 7690)
        self.assertEqual(build_strikes(7701.34).short_put, 7695)
        self.assertEqual(build_strikes(7701.34).short_call, 7705)
        self.assertEqual(build_strikes(7701.34).long_call, 7710)

    def test_one_hundred_percent_threshold_is_credit_at_least_half_width(self):
        metrics = calculate_credit_metrics(2.0, 2.0, 0.72, 0.73)
        self.assertAlmostEqual(metrics.credit, 2.55)
        self.assertAlmostEqual(metrics.defined_risk, 2.45)
        self.assertGreaterEqual(metrics.reward_risk_ratio, 1.0)
        self.assertAlmostEqual(metrics.max_loss_dollars, 245.0)

    def test_invalid_credit_is_rejected(self):
        self.assertIsNone(calculate_credit_metrics(0.1, 0.1, 1.0, 1.0))


if __name__ == "__main__":
    unittest.main()
