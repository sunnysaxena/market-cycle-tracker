from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.common import (
    BatchMetadata,
    DataAvailability,
    PaginationMetadata,
)


class OHLCFields(BaseModel):
    """Common OHLC price fields with decimal precision preserved."""

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


class DailyHistoryRecord(OHLCFields):
    """Daily historical OHLCV record."""

    model_config = ConfigDict(from_attributes=True)

    candle_date: date
    volume: int | None
    volume_status: str
    quality_status: str
    issue_codes: list[Any]


class AggregatedHistoryRecord(OHLCFields):
    """Weekly, monthly or yearly aggregated OHLCV record."""

    model_config = ConfigDict(from_attributes=True)

    timeframe: Literal["1W", "1M", "1Y"]
    period_start: date
    period_end: date
    first_session_date: date
    last_session_date: date

    volume: int | None
    volume_status: str
    session_count: int

    period_status: str
    boundary_alignment_status: str
    session_coverage_status: str

    aggregation_version: str
    generated_at_utc: datetime


class MarketHistoryResponse(BaseModel):
    """Historical market data response."""

    instrument_code: str
    timeframe: Literal["1D", "1W", "1M", "1Y"]

    batch: BatchMetadata

    records: list[
        DailyHistoryRecord | AggregatedHistoryRecord
    ]

    pagination: PaginationMetadata
    availability: DataAvailability

    