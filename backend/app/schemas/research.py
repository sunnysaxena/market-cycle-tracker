
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import BatchMetadata
from app.schemas.cycles import CycleClassification, CycleTimeframe


ForwardReturnHorizon = Literal[1, 5, 10, 20]


class ForwardReturnHorizonSummary(BaseModel):
    """Historical forward-return statistics for one horizon."""

    horizon_candles: ForwardReturnHorizon

    sample_count: int = Field(ge=0)
    unavailable_count: int = Field(ge=0)

    average_return_pct: float | None = None
    median_return_pct: float | None = None
    positive_return_pct: float | None = Field(
        default=None,
        ge=0,
        le=100,
    )


class PhaseForwardReturnSummary(BaseModel):
    """Forward-return statistics grouped by market-cycle phase."""

    cycle_classification: CycleClassification

    classified_candle_count: int = Field(ge=0)

    excluded_from_return_analysis: bool = False

    horizons: list[ForwardReturnHorizonSummary]


class ResearchForwardReturnsResponse(BaseModel):
    """Historical forward returns grouped by market-cycle classification."""

    instrument_code: str
    timeframe: CycleTimeframe

    batch: BatchMetadata

    start_date: date | None = None
    end_date: date | None = None

    analysis_method: str = "CLOSE_TO_FUTURE_CLOSE"

    phases: list[PhaseForwardReturnSummary]

    total_classifications: int = Field(ge=0)
    eligible_classifications: int = Field(ge=0)

    availability_status: str
    availability_message: str | None = None
