
from datetime import date, datetime, timezone
from decimal import Decimal
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.exception_handlers import api_service_exception_handler
from app.api.v1.candlesticks import router as candlesticks_router
from app.core.database import get_db
from app.schemas.candlestick import (
    CandlestickCalculationMetadata,
    CandlestickOHLC,
    CandlestickPatternResponse,
    CandlestickRecord,
    DataAvailability,
    MultiCandlePatternRecord,
    TwoCandlePatternRecord,
)
from app.schemas.common import BatchMetadata, PaginationMetadata
from app.services.api_errors import APIServiceError
from app.services.batch_service import BatchNotFoundError


class TestCandlestickAPI(unittest.TestCase):

    def setUp(self):
        self.db = object()

        self.app = FastAPI()
        self.app.include_router(
            candlesticks_router,
            prefix="/api/v1",
        )
        self.app.add_exception_handler(
            APIServiceError,
            api_service_exception_handler,
        )

        def override_get_db():
            yield self.db

        self.app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.app.dependency_overrides.clear()

    @staticmethod
    def make_response(
        timeframe="1D",
        availability_status="available",
    ):
        """Build a valid response matching the production schema."""

        is_available = availability_status == "available"

        candles = []
        two_candle_patterns = []
        multi_candle_patterns = []

        if is_available:
            candles = [
                CandlestickRecord(
                    candle_index=0,
                    period_start=date(2026, 10, 29),
                    period_end=date(2026, 10, 29),
                    ohlc=CandlestickOHLC(
                        open=Decimal("23000"),
                        high=Decimal("23200"),
                        low=Decimal("22900"),
                        close=Decimal("23150"),
                    ),
                    patterns=["BULLISH_MARUBOZU"],
                ),
                CandlestickRecord(
                    candle_index=1,
                    period_start=date(2026, 10, 30),
                    period_end=date(2026, 10, 30),
                    ohlc=CandlestickOHLC(
                        open=Decimal("23150"),
                        high=Decimal("23300"),
                        low=Decimal("23050"),
                        close=Decimal("23250"),
                    ),
                    patterns=["HAMMER"],
                ),
            ]

            two_candle_patterns = [
                TwoCandlePatternRecord(
                    pattern="BULLISH_ENGULFING",
                    start_index=0,
                    end_index=1,
                )
            ]

            multi_candle_patterns = [
                MultiCandlePatternRecord(
                    pattern="THREE_WHITE_SOLDIERS",
                    candle_count=3,
                    start_index=0,
                    end_index=2,
                )
            ]

        source_table = (
            "daily_ohlcv" if timeframe == "1D"
            else "aggregated_ohlcv"
        )

        return CandlestickPatternResponse(
            instrument_code="NIFTY50",
            timeframe=timeframe,
            source_table=source_table,
            batch=BatchMetadata(
                import_batch_id=5,
                status="completed",
                imported_rows=100,
                imported_at_utc=datetime(
                    2026, 11, 1, tzinfo=timezone.utc
                ),
            ),
            first_period_start=(
                date(2026, 10, 29) if is_available else None
            ),
            last_period_end=(
                date(2026, 10, 30) if is_available else None
            ),
            candles=candles,
            two_candle_patterns=two_candle_patterns,
            multi_candle_patterns=multi_candle_patterns,
            calculation=CandlestickCalculationMetadata(
                single_candle_version="single_v1",
                two_candle_version="two_v1",
                multi_candle_version="multi_v1",
            ),
            pagination=PaginationMetadata(
                limit=500,
                offset=0,
                returned_count=len(candles),
                total_records=len(candles),
            ),
            availability=DataAvailability(
                status=availability_status,
                is_available=is_available,
                record_count=len(candles),
                latest_date=(
                    date(2026, 10, 30) if is_available else None
                ),
                message=(
                    "Candlestick data available."
                    if is_available
                    else "No candlestick data is available."
                ),
            ),
        )

    def test_all_supported_timeframes(self):
        """All four supported timeframes should return successful responses."""

        timeframe_sources = {
            "1D": "daily_ohlcv",
            "1W": "aggregated_ohlcv",
            "1M": "aggregated_ohlcv",
            "1Y": "aggregated_ohlcv",
        }

        for timeframe, source_table in timeframe_sources.items():
            with self.subTest(timeframe=timeframe):
                response_data = self.make_response(timeframe)

                with patch(
                    "app.api.v1.candlesticks.get_candlestick_patterns",
                    return_value=response_data,
                ):
                    response = self.client.get(
                        "/api/v1/market/NIFTY50/candlestick-patterns",
                        params={"timeframe": timeframe},
                    )

                self.assertEqual(response.status_code, 200)

                data = response.json()

                self.assertEqual(data["instrument_code"], "NIFTY50")
                self.assertEqual(data["timeframe"], timeframe)
                self.assertEqual(data["source_table"], source_table)

    def test_timeframe_is_required(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/candlestick-patterns"
        )

        self.assertEqual(response.status_code, 422)

    def test_invalid_timeframe_is_rejected(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/candlestick-patterns",
            params={"timeframe": "5M"},
        )

        self.assertEqual(response.status_code, 422)

    def test_import_batch_id_must_be_positive(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/candlestick-patterns",
            params={
                "timeframe": "1D",
                "import_batch_id": 0,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_limit_must_be_within_allowed_range(self):
        invalid_limits = [0, 2001]

        for limit in invalid_limits:
            with self.subTest(limit=limit):
                response = self.client.get(
                    "/api/v1/market/NIFTY50/candlestick-patterns",
                    params={
                        "timeframe": "1D",
                        "limit": limit,
                    },
                )

                self.assertEqual(response.status_code, 422)

    def test_offset_cannot_be_negative(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/candlestick-patterns",
            params={
                "timeframe": "1D",
                "offset": -1,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_invalid_date_format_is_rejected(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/candlestick-patterns",
            params={
                "timeframe": "1D",
                "start_date": "not-a-date",
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_start_date_after_end_date_is_rejected(self):
        response = self.client.get(
            "/api/v1/market/NIFTY50/candlestick-patterns",
            params={
                "timeframe": "1D",
                "start_date": "2026-10-30",
                "end_date": "2026-10-29",
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "start_date must not be after end_date.",
        )

    def test_query_parameters_are_forwarded_to_service(self):
        response_data = self.make_response("1D")

        with patch(
            "app.api.v1.candlesticks.get_candlestick_patterns",
            return_value=response_data,
        ) as service_mock:

            response = self.client.get(
                "/api/v1/market/NIFTY50/candlestick-patterns",
                params={
                    "timeframe": "1D",
                    "import_batch_id": 5,
                    "start_date": "2026-10-29",
                    "end_date": "2026-10-30",
                    "limit": 100,
                    "offset": 10,
                },
            )

        self.assertEqual(response.status_code, 200)

        service_mock.assert_called_once_with(
            self.db,
            instrument_code="NIFTY50",
            timeframe="1D",
            import_batch_id=5,
            start_date=date(2026, 10, 29),
            end_date=date(2026, 10, 30),
            limit=100,
            offset=10,
        )

    def test_default_query_parameters_are_forwarded(self):
        response_data = self.make_response("1D")

        with patch(
            "app.api.v1.candlesticks.get_candlestick_patterns",
            return_value=response_data,
        ) as service_mock:

            response = self.client.get(
                "/api/v1/market/NIFTY50/candlestick-patterns",
                params={"timeframe": "1D"},
            )

        self.assertEqual(response.status_code, 200)

        service_mock.assert_called_once_with(
            self.db,
            instrument_code="NIFTY50",
            timeframe="1D",
            import_batch_id=None,
            start_date=None,
            end_date=None,
            limit=500,
            offset=0,
        )

    def test_response_contains_candlestick_patterns(self):
        response_data = self.make_response("1D")

        with patch(
            "app.api.v1.candlesticks.get_candlestick_patterns",
            return_value=response_data,
        ):
            response = self.client.get(
                "/api/v1/market/NIFTY50/candlestick-patterns",
                params={"timeframe": "1D"},
            )

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertEqual(len(data["candles"]), 2)
        self.assertEqual(
            data["candles"][0]["patterns"],
            ["BULLISH_MARUBOZU"],
        )
        self.assertEqual(
            data["two_candle_patterns"][0]["pattern"],
            "BULLISH_ENGULFING",
        )
        self.assertEqual(
            data["multi_candle_patterns"][0]["pattern"],
            "THREE_WHITE_SOLDIERS",
        )

        self.assertEqual(data["batch"]["import_batch_id"], 5)
        self.assertEqual(
            data["calculation"]["single_candle_version"],
            "single_v1",
        )
        self.assertEqual(data["pagination"]["returned_count"], 2)
        self.assertTrue(data["availability"]["is_available"])

    def test_empty_data_response_is_serialized(self):
        response_data = self.make_response(
            "1D",
            availability_status="no_data",
        )

        with patch(
            "app.api.v1.candlesticks.get_candlestick_patterns",
            return_value=response_data,
        ):
            response = self.client.get(
                "/api/v1/market/NIFTY50/candlestick-patterns",
                params={"timeframe": "1D"},
            )

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertEqual(data["candles"], [])
        self.assertEqual(data["two_candle_patterns"], [])
        self.assertEqual(data["multi_candle_patterns"], [])
        self.assertIsNone(data["first_period_start"])
        self.assertIsNone(data["last_period_end"])
        self.assertEqual(data["availability"]["status"], "no_data")
        self.assertFalse(data["availability"]["is_available"])
        self.assertEqual(data["availability"]["record_count"], 0)

    def test_service_error_uses_standard_error_response(self):
        with patch(
            "app.api.v1.candlesticks.get_candlestick_patterns",
            side_effect=BatchNotFoundError(
                "Historical import batch 999 was not found."
            ),
        ):
            response = self.client.get(
                "/api/v1/market/NIFTY50/candlestick-patterns",
                params={
                    "timeframe": "1D",
                    "import_batch_id": 999,
                },
            )

        self.assertEqual(response.status_code, 404)

        data = response.json()

        self.assertIn("error", data)
        self.assertEqual(
            data["error"]["message"],
            "Historical import batch 999 was not found.",
        )
        self.assertEqual(
            data["error"]["code"],
            "BATCH_NOT_FOUND",
        )


if __name__ == "__main__":
    unittest.main()
