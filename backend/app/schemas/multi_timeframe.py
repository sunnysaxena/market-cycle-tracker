from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.common import BatchMetadata
from app.schemas.indicators import (
    MovingAverageIndicators,
    MomentumIndicators,
    TrendIndicators,
    MACDIndicators,
    VolatilityIndicators,
    IndicatorCalculationMetadata,
)
from app.schemas.structure import (
    SupportLevel,
    ResistanceLevel,
    MarketStructureState,
    BreakoutStatus,
    RangePosition,
)
from app.schemas.cycles import (
    CycleClassification,
    ClassificationBasis,
)


MultiTimeframeKey = Literal["1D", "1W", "1M", "1Y"]


class MultiTimeframePeriod(BaseModel):
    timeframe: MultiTimeframeKey
    period_start: date
    period_end: date


class MultiTimeframeMarketData(BaseModel):
    source_table: Literal["daily_ohlcv", "aggregated_ohlcv"]
    source_status: str

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    volume: Decimal | None
    volume_status: str | None

    boundary_alignment_status: str | None
    session_coverage_status: str | None
    session_count: int | None


class MultiTimeframeIndicators(BaseModel):
    moving_averages: MovingAverageIndicators
    momentum: MomentumIndicators
    trend: TrendIndicators
    macd: MACDIndicators
    volatility: VolatilityIndicators
    calculation: IndicatorCalculationMetadata


class MultiTimeframeStructure(BaseModel):
    source_close: Decimal

    support: SupportLevel
    resistance: ResistanceLevel

    market_structure_state: MarketStructureState
    breakout_status: BreakoutStatus
    range_position: RangePosition

    left_bars: int
    right_bars: int
    equal_tolerance_pct: Decimal

    calculation_version: str
    generated_at_utc: datetime


class MultiTimeframeCycle(BaseModel):
    cycle_classification: CycleClassification
    rule_score: int

    bandwidth_percentile: Decimal | None
    classification_basis: ClassificationBasis

    evidence: list[str]
    missing_inputs: list[str]
    config_json: dict[str, Any]

    calculation_version: str
    generated_at_utc: datetime


class MultiTimeframeAvailability(BaseModel):
    status: Literal["available", "partial", "no_data"]
    is_available: bool

    indicator_available: bool
    indicator_status: Literal[
        "warming_up",
        "partial",
        "ready",
    ] | None

    structure_available: bool
    cycle_available: bool

    message: str | None = None


class MultiTimeframeSnapshot(BaseModel):
    period: MultiTimeframePeriod | None = None

    market_data: MultiTimeframeMarketData | None = None
    indicators: MultiTimeframeIndicators | None = None
    structure: MultiTimeframeStructure | None = None
    cycle: MultiTimeframeCycle | None = None

    availability: MultiTimeframeAvailability


class MultiTimeframeResponse(BaseModel):
    instrument_code: str
    batch: BatchMetadata

    timeframes: dict[
        MultiTimeframeKey,
        MultiTimeframeSnapshot,
    ]

