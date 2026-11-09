
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import (
    BatchMetadata,
    DataAvailability,
    PaginationMetadata,
)


IndicatorTimeframe = Literal["1D", "1W", "1M", "1Y"]


class IndicatorSource(BaseModel):
    """Source candle metadata used for indicator calculation."""

    table: str
    status: str
    boundary_alignment_status: str | None
    session_coverage_status: str | None


class IndicatorOHLC(BaseModel):
    """Source OHLC values used for indicator calculation."""

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


class MovingAverageIndicators(BaseModel):
    ema_9: Decimal | None
    ema_20: Decimal | None
    ema_50: Decimal | None
    ema_100: Decimal | None
    ema_200: Decimal | None
    sma_222: Decimal | None


class MomentumIndicators(BaseModel):
    rsi_14: Decimal | None


class TrendIndicators(BaseModel):
    adx_14: Decimal | None
    plus_di_14: Decimal | None
    minus_di_14: Decimal | None


class MACDIndicators(BaseModel):
    line_12_26: Decimal | None
    signal_9: Decimal | None
    histogram: Decimal | None


class VolatilityIndicators(BaseModel):
    atr_14: Decimal | None
    chop_14: Decimal | None
    bollinger_bandwidth_20_2: Decimal | None
    bollinger_upper_20_2: Decimal | None
    bollinger_middle_20_2: Decimal | None
    bollinger_lower_20_2: Decimal | None


class IndicatorCalculationMetadata(BaseModel):
    status: Literal["warming_up", "partial", "ready"]
    version: str
    generated_at_utc: datetime


class TechnicalIndicatorRecord(BaseModel):
    period_start: date
    period_end: date

    source: IndicatorSource
    ohlc: IndicatorOHLC

    moving_averages: MovingAverageIndicators
    momentum: MomentumIndicators
    trend: TrendIndicators
    macd: MACDIndicators
    volatility: VolatilityIndicators

    calculation: IndicatorCalculationMetadata


class TechnicalIndicatorResponse(BaseModel):
    instrument_code: str
    timeframe: IndicatorTimeframe

    batch: BatchMetadata
    records: list[TechnicalIndicatorRecord]

    pagination: PaginationMetadata
    availability: DataAvailability
