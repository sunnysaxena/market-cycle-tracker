import unittest
from datetime import date
from decimal import Decimal

from app.services.backtest_data_loader import (
    load_daily_backtest_data,
)


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = False
        self.params = None

    def execute(self, statement, params):
        self.executed = True
        self.params = params
        return FakeResult(self.rows)


def make_record(
    candle_date,
    *,
    indicator_batch=5,
    structure_batch=5,
    cycle_batch=5,
):
    return {
        "import_batch_id": 5,
        "instrument_code": "NIFTY50",
        "candle_date": candle_date,
        "open": Decimal("100.00"),
        "high": Decimal("105.00"),
        "low": Decimal("98.00"),
        "close": Decimal("103.00"),
        "volume": 100000,
        "indicator_join_batch_id": indicator_batch,
        "structure_join_batch_id": structure_batch,
        "cycle_join_batch_id": cycle_batch,
        "indicator_calculation_status": "ready",
        "market_structure_state": "MIXED_TRANSITION",
        "cycle_classification": "TRANSITION_UNCERTAIN",
        "ema_20": Decimal("101.50"),
        "rsi_14": Decimal("53.50"),
    }


class TestBacktestDataLoader(unittest.TestCase):

    def test_loads_records_and_removes_internal_join_markers(self):
        rows = [
            make_record(date(2026, 10, 29)),
            make_record(date(2026, 10, 30)),
        ]
        session = FakeSession(rows)

        result = load_daily_backtest_data(
            session,
            import_batch_id=5,
            instrument_code="nifty50",
        )

        self.assertEqual(len(result), 2)
        self.assertTrue(session.executed)

        self.assertEqual(
            session.params,
            {
                "import_batch_id": 5,
                "instrument_code": "NIFTY50",
                "start_date": None,
                "end_date": None,
            },
        )

        self.assertEqual(
            result[0]["candle_date"],
            date(2026, 10, 29),
        )
        self.assertEqual(
            result[1]["candle_date"],
            date(2026, 10, 30),
        )

        self.assertEqual(
            result[0]["indicator_calculation_status"],
            "ready",
        )
        self.assertEqual(
            result[0]["cycle_classification"],
            "TRANSITION_UNCERTAIN",
        )

        internal_markers = {
            "indicator_join_batch_id",
            "structure_join_batch_id",
            "cycle_join_batch_id",
        }

        for record in result:
            self.assertTrue(internal_markers.isdisjoint(record))

    def test_rejects_non_positive_import_batch_id(self):
        for batch_id in (0, -1):
            with self.subTest(batch_id=batch_id):
                session = FakeSession()

                with self.assertRaises(ValueError):
                    load_daily_backtest_data(
                        session,
                        import_batch_id=batch_id,
                        instrument_code="NIFTY50",
                    )

                self.assertFalse(session.executed)

    def test_rejects_unsupported_instrument(self):
        session = FakeSession()

        with self.assertRaises(ValueError):
            load_daily_backtest_data(
                session,
                import_batch_id=5,
                instrument_code="INDIA_VIX",
            )

        self.assertFalse(session.executed)

    def test_normalizes_instrument_code(self):
        session = FakeSession([
            make_record(date(2026, 10, 30))
        ])

        load_daily_backtest_data(
            session,
            import_batch_id=5,
            instrument_code="  nifty50  ",
        )

        self.assertEqual(
            session.params["instrument_code"],
            "NIFTY50",
        )

    def test_rejects_invalid_date_range(self):
        session = FakeSession()

        with self.assertRaises(ValueError):
            load_daily_backtest_data(
                session,
                import_batch_id=5,
                instrument_code="NIFTY50",
                start_date=date(2026, 10, 30),
                end_date=date(2026, 10, 1),
            )

        self.assertFalse(session.executed)

    def test_rejects_duplicate_candle_dates(self):
        duplicate_date = date(2026, 10, 30)

        session = FakeSession([
            make_record(duplicate_date),
            make_record(duplicate_date),
        ])

        with self.assertRaisesRegex(
            RuntimeError,
            "Duplicate daily candle dates",
        ):
            load_daily_backtest_data(
                session,
                import_batch_id=5,
                instrument_code="NIFTY50",
            )

    def test_rejects_missing_indicator_context(self):
        session = FakeSession([
            make_record(
                date(2026, 10, 30),
                indicator_batch=None,
            )
        ])

        with self.assertRaisesRegex(
            RuntimeError,
            "technical indicators",
        ):
            load_daily_backtest_data(
                session,
                import_batch_id=5,
                instrument_code="NIFTY50",
            )

    def test_rejects_missing_market_structure_context(self):
        session = FakeSession([
            make_record(
                date(2026, 10, 30),
                structure_batch=None,
            )
        ])

        with self.assertRaisesRegex(
            RuntimeError,
            "market structure",
        ):
            load_daily_backtest_data(
                session,
                import_batch_id=5,
                instrument_code="NIFTY50",
            )

    def test_rejects_missing_market_cycle_context(self):
        session = FakeSession([
            make_record(
                date(2026, 10, 30),
                cycle_batch=None,
            )
        ])

        with self.assertRaisesRegex(
            RuntimeError,
            "market cycle classifications",
        ):
            load_daily_backtest_data(
                session,
                import_batch_id=5,
                instrument_code="NIFTY50",
            )

    def test_returns_empty_list_when_no_candles_match(self):
        session = FakeSession([])

        result = load_daily_backtest_data(
            session,
            import_batch_id=5,
            instrument_code="NIFTY50",
        )

        self.assertEqual(result, [])
        self.assertTrue(session.executed)


if __name__ == "__main__":
    unittest.main()
