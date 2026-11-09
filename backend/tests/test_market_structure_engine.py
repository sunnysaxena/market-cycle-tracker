import unittest
from datetime import date, timedelta
from decimal import Decimal

from app.engines.market_structure_engine import (
    CALCULATION_VERSION,
    MarketStructureCalculationError,
    calculate_market_structure,
)


def make_rows(
    highs,
    lows,
    closes=None,
    statuses=None,
    *,
    timeframe="1D",
    dates=None,
):
    count = len(highs)

    if closes is None:
        closes = [
            (Decimal(str(h)) + Decimal(str(l))) / Decimal("2")
            for h, l in zip(highs, lows)
        ]

    if statuses is None:
        statuses = (
            ["accepted"] * count
            if timeframe == "1D"
            else ["completed"] * count
        )

    start = date(2025, 1, 1)
    rows = []

    for i in range(count):
        period_start = (
            dates[i]
            if dates is not None
            else (
                start + timedelta(days=i)
                if timeframe == "1D"
                else start + timedelta(days=i * 7)
            )
        )

        period_end = (
            period_start
            if timeframe == "1D"
            else period_start + timedelta(days=6)
        )

        close = Decimal(str(closes[i]))

        row = {
            "period_start": period_start,
            "period_end": period_end,
            "open": close,
            "high": Decimal(str(highs[i])),
            "low": Decimal(str(lows[i])),
            "close": close,
            "source_status": statuses[i],
        }

        if timeframe != "1D":
            row["boundary_alignment_status"] = "aligned"
            row["session_coverage_status"] = "not_checked"

        rows.append(row)

    return rows


class TestMarketStructureEngine(unittest.TestCase):

    def calculate(self, rows, timeframe="1D", **kwargs):
        return calculate_market_structure(
            rows,
            instrument_code="NIFTY50",
            timeframe=timeframe,
            **kwargs,
        )

    def test_engine_version_and_snapshot_count(self):
        result = self.calculate(
            make_rows([10, 11, 12, 11], [5, 6, 7, 8])
        )

        self.assertEqual(
            result["calculation_version"],
            CALCULATION_VERSION,
        )
        self.assertEqual(result["snapshot_count"], 4)
        self.assertEqual(result["eligible_rows"], 4)

    def test_swing_high_confirmation_delay(self):
        rows = make_rows(
            highs=[10, 12, 20, 11, 9, 13, 12],
            lows=[5, 6, 7, 8, 9, 10, 11],
        )

        result = self.calculate(
            rows,
            left_bars=2,
            right_bars=2,
        )

        self.assertEqual(result["event_count"], 1)

        event = result["events"][0]

        self.assertEqual(event["event_type"], "SWING_HIGH")
        self.assertEqual(event["classification"], "SH")
        self.assertEqual(event["pivot_date"], date(2025, 1, 3))
        self.assertEqual(
            event["confirmation_date"],
            date(2025, 1, 5),
        )
        self.assertEqual(event["pivot_price"], Decimal("20"))

        # The pivot must not be visible before confirmation.
        self.assertIsNone(
            result["snapshots"][3]["resistance_price"]
        )

        self.assertEqual(
            result["snapshots"][4]["resistance_price"],
            Decimal("20"),
        )

    def test_swing_low_detection(self):
        rows = make_rows(
            highs=[20, 19, 18, 19, 20],
            lows=[10, 8, 5, 9, 11],
        )

        result = self.calculate(
            rows,
            left_bars=2,
            right_bars=2,
        )

        low_events = [
            event for event in result["events"]
            if event["event_type"] == "SWING_LOW"
        ]

        self.assertEqual(len(low_events), 1)
        self.assertEqual(
            low_events[0]["pivot_price"],
            Decimal("5"),
        )
        self.assertEqual(
            low_events[0]["classification"],
            "SL",
        )
        self.assertEqual(
            low_events[0]["confirmation_date"],
            date(2025, 1, 5),
        )

    def test_equal_high_plateau_uses_rightmost_pivot(self):
        rows = make_rows(
            highs=[8, 10, 15, 15, 9, 8, 7],
            lows=[1, 2, 3, 4, 5, 6, 7],
        )

        result = self.calculate(
            rows,
            left_bars=2,
            right_bars=2,
        )

        high_events = [
            event for event in result["events"]
            if event["event_type"] == "SWING_HIGH"
        ]

        self.assertEqual(len(high_events), 1)
        self.assertEqual(
            high_events[0]["pivot_date"],
            date(2025, 1, 4),
        )

    def test_higher_high_and_higher_low_classification(self):
        rows = make_rows(
            highs=[8, 10, 8, 9, 12, 9, 10, 13, 10],
            lows=[7, 5, 8, 7, 6, 8, 7, 7, 8],
        )

        result = self.calculate(
            rows,
            left_bars=1,
            right_bars=1,
        )

        high_events = [
            event for event in result["events"]
            if event["event_type"] == "SWING_HIGH"
        ]

        low_events = [
            event for event in result["events"]
            if event["event_type"] == "SWING_LOW"
        ]

        self.assertEqual(
            [event["classification"] for event in high_events],
            ["SH", "HH", "HH"],
        )

        self.assertEqual(
            [event["classification"] for event in low_events],
            ["SL", "HL", "HL"],
        )

        self.assertEqual(
            result["snapshots"][-1]["market_structure_state"],
            "BULLISH",
        )

    def test_close_based_bullish_breakout(self):
        rows = make_rows(
            highs=[8, 10, 8, 9, 11, 12],
            lows=[6, 7, 6, 7, 8, 9],
            closes=[7, 9, 7, 8, 10, 11],
        )

        result = self.calculate(
            rows,
            left_bars=1,
            right_bars=1,
        )

        self.assertEqual(
            result["snapshots"][4]["breakout_status"],
            "NONE",
        )

        self.assertEqual(
            result["snapshots"][5]["breakout_status"],
            "BULLISH_BREAKOUT",
        )

    def test_weekly_confirmation_uses_candle_end_date(self):
        dates = [
            date(2025, 1, 6) + timedelta(days=i * 7)
            for i in range(5)
        ]

        rows = make_rows(
            highs=[10, 12, 20, 11, 9],
            lows=[5, 7, 8, 7, 6],
            timeframe="1W",
            dates=dates,
        )

        result = self.calculate(
            rows,
            timeframe="1W",
            left_bars=2,
            right_bars=2,
        )

        high_events = [
            event for event in result["events"]
            if event["event_type"] == "SWING_HIGH"
        ]

        self.assertEqual(len(high_events), 1)

        event = high_events[0]

        self.assertEqual(
            event["pivot_date"],
            dates[2],
        )

        # Confirmation occurs only when the fifth weekly
        # candle has finished.
        expected_confirmation_date = dates[4] + timedelta(days=6)

        self.assertEqual(
            event["confirmation_date"],
            expected_confirmation_date,
        )

        self.assertEqual(
            event["confirmation_period_end"],
            expected_confirmation_date,
        )

    def test_missing_week_resets_analysis_segment(self):
        dates = [
            date(2025, 1, 6),
            date(2025, 1, 13),
            date(2025, 1, 27),
            date(2025, 2, 3),
        ]

        rows = make_rows(
            highs=[10, 15, 20, 10],
            lows=[5, 7, 8, 6],
            timeframe="1W",
            dates=dates,
        )

        result = self.calculate(
            rows,
            timeframe="1W",
            left_bars=1,
            right_bars=1,
        )

        self.assertEqual(result["segment_count"], 2)
        self.assertEqual(result["snapshot_count"], 4)
        self.assertEqual(result["event_count"], 0)

    def test_rejected_daily_candle_resets_segment(self):
        rows = make_rows(
            highs=[10, 12, 20, 11, 9],
            lows=[5, 6, 7, 8, 9],
            statuses=[
                "accepted",
                "accepted",
                "review_required",
                "accepted",
                "accepted",
            ],
        )

        result = self.calculate(
            rows,
            left_bars=1,
            right_bars=1,
        )

        self.assertEqual(result["eligible_rows"], 4)
        self.assertEqual(result["excluded_rows"], 1)
        self.assertEqual(result["segment_count"], 2)
        self.assertEqual(result["event_count"], 0)

    def test_invalid_ohlc_is_rejected(self):
        rows = make_rows(
            highs=[10, 11, 12],
            lows=[5, 6, 7],
        )

        rows[1]["high"] = Decimal("5")

        with self.assertRaises(
            MarketStructureCalculationError
        ):
            self.calculate(rows)

    def test_india_vix_is_rejected(self):
        rows = make_rows(
            highs=[10, 11, 12],
            lows=[5, 6, 7],
        )

        with self.assertRaises(
            MarketStructureCalculationError
        ):
            calculate_market_structure(
                rows,
                instrument_code="INDIA_VIX",
                timeframe="1D",
            )

    def test_invalid_pivot_configuration_is_rejected(self):
        rows = make_rows(
            highs=[10, 11, 12],
            lows=[5, 6, 7],
        )

        with self.assertRaises(
            MarketStructureCalculationError
        ):
            self.calculate(rows, left_bars=0)


if __name__ == "__main__":
    unittest.main()
