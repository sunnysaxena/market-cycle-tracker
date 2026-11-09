from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import (
    BatchMetadata,
    DataAvailability,
    PaginationMetadata,
)


CycleTimeframe = Literal["1D", "1W", "1M", "1Y"]

CycleClassification = Literal[
    "ACCUMULATION",
    "MARKUP",
    "DISTRIBUTION",
    "MARKDOWN",
    "SIDEWAYS_CONSOLIDATION",
    "TRANSITION_UNCERTAIN",
    "INSUFFICIENT_DATA",
]

ClassificationBasis = Literal[
    "INSUFFICIENT_INPUT",
    "PRICE_TREND_RULES",
    "PRICE_ACTION_HEURISTIC",
    "RANGE_AND_VOLATILITY_RULES",
    "MIXED_OR_INCOMPLETE_RULES",
]


class MarketCycleRecord(BaseModel):
    """One stored market-cycle classification."""

    model_config = ConfigDict(from_attributes=True)

    period_start: date
    period_end: date

    cycle_classification: CycleClassification
    rule_score: int = Field(ge=0, le=100)

    bandwidth_percentile: Decimal | None

    classification_basis: ClassificationBasis

    evidence: list[str]
    missing_inputs: list[str]

    config_json: dict[str, Any]

    calculation_version: str
    generated_at_utc: datetime


class MarketCycleResponse(BaseModel):
    """Paginated market-cycle classification response."""

    instrument_code: str
    timeframe: CycleTimeframe

    batch: BatchMetadata

    records: list[MarketCycleRecord]

    pagination: PaginationMetadata
    availability: DataAvailability
