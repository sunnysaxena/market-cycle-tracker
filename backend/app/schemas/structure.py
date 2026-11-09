
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import (
    BatchMetadata,
    DataAvailability,
    PaginationMetadata,
)


StructureTimeframe = Literal["1D", "1W", "1M", "1Y"]

EventType = Literal["SWING_HIGH", "SWING_LOW"]

EventClassification = Literal[
    "SH", "SL", "HH", "HL", "LH", "LL", "EQH", "EQL"
]

SupportClassification = Literal["SL", "HL", "LL", "EQL"]

ResistanceClassification = Literal["SH", "HH", "LH", "EQH"]

MarketStructureState = Literal[
    "BULLISH",
    "BEARISH",
    "MIXED_TRANSITION",
    "INSUFFICIENT_DATA",
]

BreakoutStatus = Literal[
    "NONE",
    "BULLISH_BREAKOUT",
    "BEARISH_BREAKDOWN",
    "BOTH",
]

RangePosition = Literal[
    "INSUFFICIENT_LEVELS",
    "ABOVE_RESISTANCE",
    "BELOW_SUPPORT",
    "WITHIN_SWING_RANGE",
]


class SupportLevel(BaseModel):
    price: Decimal | None
    pivot_date: date | None
    confirmation_date: date | None
    classification: SupportClassification | None


class ResistanceLevel(BaseModel):
    price: Decimal | None
    pivot_date: date | None
    confirmation_date: date | None
    classification: ResistanceClassification | None


class StructureSnapshotRecord(BaseModel):
    period_start: date
    period_end: date
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


class MarketStructureResponse(BaseModel):
    instrument_code: str
    timeframe: StructureTimeframe
    batch: BatchMetadata
    records: list[StructureSnapshotRecord]
    pagination: PaginationMetadata
    availability: DataAvailability


class StructureEventRecord(BaseModel):
    event_type: EventType

    pivot_date: date
    pivot_period_end: date

    confirmation_date: date
    confirmation_period_end: date

    pivot_price: Decimal
    classification: EventClassification

    left_bars: int
    right_bars: int
    equal_tolerance_pct: Decimal

    calculation_version: str
    generated_at_utc: datetime


class MarketStructureEventsResponse(BaseModel):
    instrument_code: str
    timeframe: StructureTimeframe
    batch: BatchMetadata
    records: list[StructureEventRecord]
    pagination: PaginationMetadata
    availability: DataAvailability
