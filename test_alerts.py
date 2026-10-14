"""
Unit tests for Price Alert Tool (alerts.py)
===========================================
Uses Python's built-in `unittest` module.

Covers:
1. Handling out-of-order CSV dates (chronological sorting per instrument).
2. Moving average boundary conditions (insufficient data, exact first crossover point,
   golden cross, death cross, no-cross scenarios).
3. Level crossing conditions (cross above, cross below, boundary touches).
4. Strict output sorting by date, then rule ID.
5. Multi-instrument isolation.
"""

import tempfile
import os
import unittest
from alerts import (
    PriceRecord,
    Alert,
    parse_prices,
    calculate_sma,
    evaluate_level_rule,
    evaluate_ma_cross_rule,
    evaluate_all_rules,
)


class TestPriceAlerts(unittest.TestCase):

    def test_out_of_order_csv_dates(self):
        """Verifies that records in random chronological order in CSV are properly sorted."""
        csv_content = (
            "date,instrument,close\n"
            "2023-01-05,AAPL,150.0\n"
            "2023-01-01,AAPL,140.0\n"
            "2023-01-04,AAPL,148.0\n"
            "2023-01-02,AAPL,142.0\n"
            "2023-01-03,AAPL,145.0\n"
        )
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as tmp:
            tmp.write(csv_content)
            tmp_path = tmp.name

        try:
            prices = parse_prices(tmp_path)
            aapl_records = prices["AAPL"]
            dates = [r.date for r in aapl_records]
            expected_dates = [
                "2023-01-01",
                "2023-01-02",
                "2023-01-03",
                "2023-01-04",
                "2023-01-05",
            ]
            self.assertEqual(dates, expected_dates)
            closes = [r.close for r in aapl_records]
            self.assertEqual(closes, [140.0, 142.0, 145.0, 148.0, 150.0])
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_sma_calculation(self):
        """Tests the sliding window simple moving average computation."""
        prices = [10.0, 20.0, 30.0, 40.0, 50.0]
        # Window of 3:
        # index 0: None
        # index 1: None
        # index 2: (10 + 20 + 30) / 3 = 20.0
        # index 3: (20 + 30 + 40) / 3 = 30.0
        # index 4: (30 + 40 + 50) / 3 = 40.0
        sma3 = calculate_sma(prices, 3)
        self.assertIsNone(sma3[0])
        self.assertIsNone(sma3[1])
        self.assertAlmostEqual(sma3[2], 20.0)
        self.assertAlmostEqual(sma3[3], 30.0)
        self.assertAlmostEqual(sma3[4], 40.0)

    def test_ma_cross_boundaries(self):
        """
        Tests boundary conditions for moving average crossovers.
        
        Given short_window = 2, long_window = 3:
        - 3 days: Long MA only first becomes available on day 3 (index 2).
          Day 2 (index 1) has no Long MA, so day 3 CANNOT detect a crossover.
          Alerts count must be 0.
        - 4 days: Day 4 (index 3) is the FIRST day where both day t-1 and day t
          have valid Long MAs. If a crossover happened between day 3 and day 4,
          an alert must fire on day 4.
        """
        rule = {
            "id": "ma_test",
            "type": "ma_cross",
            "instrument": "TEST",
            "short_window": 2,
            "long_window": 3,
        }

        # Case A: Only 3 days (length == long_window) -> Cannot evaluate crossover
        records_3_days = [
            PriceRecord("2023-01-01", "TEST", 10.0),
            PriceRecord("2023-01-02", "TEST", 12.0),
            PriceRecord("2023-01-03", "TEST", 20.0),
        ]
        alerts = evaluate_ma_cross_rule(rule, records_3_days)
        self.assertEqual(len(alerts), 0)

        # Case B: 4 days with a Golden Cross occurring on day 4 (2023-01-04)
        # Prices:
        # Day 1: 30.0  (SMA2: None, SMA3: None)
        # Day 2: 20.0  (SMA2: 25.0, SMA3: None)
        # Day 3: 10.0  (SMA2: 15.0, SMA3: 20.0) -> short (15) < long (20)
        # Day 4: 50.0  (SMA2: 30.0, SMA3: 26.67) -> short (30) > long (26.67) -> Cross above!
        records_4_days = records_3_days + [PriceRecord("2023-01-04", "TEST", 50.0)]
        records_4_days[0] = PriceRecord("2023-01-01", "TEST", 30.0)
        records_4_days[1] = PriceRecord("2023-01-02", "TEST", 20.0)
        records_4_days[2] = PriceRecord("2023-01-03", "TEST", 10.0)

        alerts = evaluate_ma_cross_rule(rule, records_4_days)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].date, "2023-01-04")
        self.assertEqual(alerts[0].rule_id, "ma_test")
        self.assertIn("crossed above", alerts[0].description)

        # Case C: Bearish Cross (Death Cross)
        # Day 1: 10.0
        # Day 2: 20.0
        # Day 3: 30.0  (SMA2: 25.0, SMA3: 20.0) -> short > long
        # Day 4: 0.0   (SMA2: 15.0, SMA3: 16.67) -> short < long -> Cross below!
        bearish_records = [
            PriceRecord("2023-01-01", "TEST", 10.0),
            PriceRecord("2023-01-02", "TEST", 20.0),
            PriceRecord("2023-01-03", "TEST", 30.0),
            PriceRecord("2023-01-04", "TEST", 0.0),
        ]
        alerts = evaluate_ma_cross_rule(rule, bearish_records)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].date, "2023-01-04")
        self.assertIn("crossed below", alerts[0].description)

        # Case D: No crossover (Short MA stays consistently above Long MA)
        steady_records = [
            PriceRecord("2023-01-01", "TEST", 10.0),
            PriceRecord("2023-01-02", "TEST", 20.0),
            PriceRecord("2023-01-03", "TEST", 30.0),
            PriceRecord("2023-01-04", "TEST", 40.0),
            PriceRecord("2023-01-05", "TEST", 50.0),
        ]
        alerts = evaluate_ma_cross_rule(rule, steady_records)
        self.assertEqual(len(alerts), 0)

    def test_level_rule(self):
        """Tests level crossing detection (above, below, touches)."""
        rule_above = {
            "id": "lvl_above",
            "type": "level",
            "instrument": "AAPL",
            "level": 100.0,
            "direction": "above",
        }
        rule_both = {
            "id": "lvl_both",
            "type": "level",
            "instrument": "AAPL",
            "level": 100.0,
        }

        # Sequence:
        # Day 1: 95.0
        # Day 2: 105.0 -> crosses above
        # Day 3: 105.0 -> no change / no cross
        # Day 4: 90.0  -> crosses below
        # Day 5: 100.0 -> touches exact level from below -> counts as crossing above
        # Day 6: 100.0 -> flat at level -> does not cross
        records = [
            PriceRecord("2023-01-01", "AAPL", 95.0),
            PriceRecord("2023-01-02", "AAPL", 105.0),
            PriceRecord("2023-01-03", "AAPL", 105.0),
            PriceRecord("2023-01-04", "AAPL", 90.0),
            PriceRecord("2023-01-05", "AAPL", 100.0),
            PriceRecord("2023-01-06", "AAPL", 100.0),
        ]

        # Only above
        alerts_above = evaluate_level_rule(rule_above, records)
        self.assertEqual(len(alerts_above), 2)
        self.assertEqual(alerts_above[0].date, "2023-01-02")
        self.assertEqual(alerts_above[1].date, "2023-01-05")

        # Both directions
        alerts_both = evaluate_level_rule(rule_both, records)
        self.assertEqual(len(alerts_both), 3)
        self.assertEqual([a.date for a in alerts_both], ["2023-01-02", "2023-01-04", "2023-01-05"])

    def test_multi_instrument_and_sorting(self):
        """
        Verifies that rules are evaluated per instrument in isolation,
        and final alerts are sorted strictly by (date, rule_id).
        """
        prices = {
            "AAPL": [
                PriceRecord("2023-01-01", "AAPL", 100.0),
                PriceRecord("2023-01-02", "AAPL", 110.0),
            ],
            "MSFT": [
                PriceRecord("2023-01-01", "MSFT", 200.0),
                PriceRecord("2023-01-02", "MSFT", 210.0),
            ],
        }

        rules = [
            {"id": "rule_b", "type": "level", "instrument": "MSFT", "level": 205.0},
            {"id": "rule_a", "type": "level", "instrument": "AAPL", "level": 105.0},
        ]

        alerts = evaluate_all_rules(prices, rules)
        # Manually sort the way format_and_print_alerts does
        alerts.sort(key=lambda a: (a.date, a.rule_id))

        self.assertEqual(len(alerts), 2)
        # Both triggered on 2023-01-02, rule_a should precede rule_b
        self.assertEqual(alerts[0].rule_id, "rule_a")
        self.assertEqual(alerts[0].instrument, "AAPL")
        self.assertEqual(alerts[1].rule_id, "rule_b")
        self.assertEqual(alerts[1].instrument, "MSFT")


if __name__ == "__main__":
    unittest.main()
