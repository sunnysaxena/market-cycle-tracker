
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import (
    BatchMetadata,
    DataAvailability,
    PaginationMetadata,
)


CandlestickTimeframe = Literal["1D", "1W", "1M", "1Y"]


class CandlestickOHLC(BaseModel):
    """OHLC values for one historical candle."""

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


class CandlestickRecord(BaseModel):
    """One dated candle with its original full-history index."""

    candle_index: int
    period_start: date | datetime
    period_end: date | datetime

    ohlc: CandlestickOHLC
    patterns: list[str]


class TwoCandlePatternRecord(BaseModel):
    """A two-candle pattern with original history indices."""

    pattern: str
    start_index: int
    end_index: int


class MultiCandlePatternRecord(BaseModel):
    """A multi-candle pattern with original history indices."""

    pattern: str
    candle_count: int
    start_index: int
    end_index: int


class CandlestickCalculationMetadata(BaseModel):
    """Calculation versions used by the analysis engines."""

    single_candle_version: str
    two_candle_version: str
    multi_candle_version: str


class CandlestickPatternResponse(BaseModel):
    """Complete API response for candlestick pattern analysis."""

    instrument_code: str
    timeframe: CandlestickTimeframe

    source_table: Literal["daily_ohlcv", "aggregated_ohlcv"]

    batch: BatchMetadata

    first_period_start: date | datetime | None
    last_period_end: date | datetime | None

    candles: list[CandlestickRecord]

    two_candle_patterns: list[TwoCandlePatternRecord]
    multi_candle_patterns: list[MultiCandlePatternRecord]

    calculation: CandlestickCalculationMetadata

    pagination: PaginationMetadata
    availability: DataAvailability
