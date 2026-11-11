
from datetime import date
from statistics import mean, median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engines.indicator_engine import PRICE_INDEX_CODES
from app.models.index import Index
from app.models.historical import (
    AggregatedOHLCV,
    DailyOHLCV,
    MarketCycleClassification,
)
from app.schemas.cycles import CycleClassification, CycleTimeframe
from app.schemas.research import (
    ForwardReturnHorizonSummary,
    PhaseForwardReturnSummary,
    ResearchForwardReturnsResponse,
)
from app.schemas.common import BatchMetadata
from app.services.api_errors import (
    InstrumentNotFoundError,
    UnsupportedInstrumentCategoryError,
)
from app.services.batch_service import resolve_import_batch


HORIZONS = (1, 5, 10, 20)

PHASES: tuple[CycleClassification, ...] = (
    "ACCUMULATION",
    "MARKUP",
    "DISTRIBUTION",
    "MARKDOWN",
    "SIDEWAYS_CONSOLIDATION",
    "TRANSITION_UNCERTAIN",
    "INSUFFICIENT_DATA",
)


def _validate_dates(
    start_date: date | None,
    end_date: date | None,
) -> None:
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must not be after end_date.")


def _get_active_instrument(
    db: Session,
    instrument: str,
) -> Index:
    code = instrument.strip().upper()

    index = db.scalar(
        select(Index).where(
            Index.code == code,
            Index.is_active.is_(True),
        )
    )

    if index is None:
        raise InstrumentNotFoundError(
            f"Active instrument '{code}' was not found."
        )

    if code not in PRICE_INDEX_CODES:
        raise UnsupportedInstrumentCategoryError(
            f"Instrument '{code}' is not supported for "
            "price-based forward-return analysis."
        )

    return index


def _load_eligible_closes(
    db: Session,
    *,
    import_batch_id: int,
    instrument_code: str,
    timeframe: CycleTimeframe,
) -> list[tuple[date, float]]:
    """Load all eligible closes in chronological order."""

    if timeframe == "1D":
        rows = db.execute(
            select(
                DailyOHLCV.candle_date,
                DailyOHLCV.close,
            )
            .where(
                DailyOHLCV.import_batch_id == import_batch_id,
                DailyOHLCV.instrument_code == instrument_code,
                DailyOHLCV.quality_status == "accepted",
            )
            .order_by(DailyOHLCV.candle_date.asc())
        ).all()
    else:
        rows = db.execute(
            select(
                AggregatedOHLCV.period_start,
                AggregatedOHLCV.close,
            )
            .where(
                AggregatedOHLCV.import_batch_id == import_batch_id,
                AggregatedOHLCV.instrument_code == instrument_code,
                AggregatedOHLCV.timeframe == timeframe,
                AggregatedOHLCV.period_status == "completed",
                AggregatedOHLCV.boundary_alignment_status == "aligned",
            )
            .order_by(AggregatedOHLCV.period_start.asc())
        ).all()

    return [
        (period_start, float(close))
        for period_start, close in rows
        if close is not None and float(close) > 0
    ]


def get_forward_returns_by_phase(
    db: Session,
    *,
    instrument: str,
    timeframe: CycleTimeframe,
    import_batch_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> ResearchForwardReturnsResponse:
    """
    Calculate historical close-to-future-close returns grouped by phase.

    Future observations use subsequent eligible candles from the same
    batch, instrument, and timeframe. Date filters apply only to the
    starting classification candles, not future target candles.
    """

    _validate_dates(start_date, end_date)

    index = _get_active_instrument(db, instrument)
    batch = resolve_import_batch(db, import_batch_id)

    base_filters = [
        MarketCycleClassification.import_batch_id == batch.id,
        MarketCycleClassification.instrument_code == index.code,
        MarketCycleClassification.timeframe == timeframe,
    ]

    base_count = db.scalar(
        select(func.count())
        .select_from(MarketCycleClassification)
        .where(*base_filters)
    ) or 0

    filters = list(base_filters)

    if start_date is not None:
        filters.append(
            MarketCycleClassification.period_start >= start_date
        )

    if end_date is not None:
        filters.append(
            MarketCycleClassification.period_start <= end_date
        )

    classifications = db.scalars(
        select(MarketCycleClassification)
        .where(*filters)
        .order_by(MarketCycleClassification.period_start.asc())
    ).all()

    eligible_closes = _load_eligible_closes(
        db,
        import_batch_id=batch.id,
        instrument_code=index.code,
        timeframe=timeframe,
    )

    close_positions = {
        period_start: position
        for position, (period_start, _) in enumerate(eligible_closes)
    }

    phase_records = {
        phase: {
            "classified_count": 0,
            "returns": {horizon: [] for horizon in HORIZONS},
            "unavailable": {horizon: 0 for horizon in HORIZONS},
        }
        for phase in PHASES
    }

    eligible_classifications = 0

    for classification in classifications:
        phase = classification.cycle_classification
        record = phase_records[phase]
        record["classified_count"] += 1

        # Incomplete classifications remain visible but are excluded.
        if phase == "INSUFFICIENT_DATA":
            continue

        position = close_positions.get(classification.period_start)

        if position is None:
            for horizon in HORIZONS:
                record["unavailable"][horizon] += 1
            continue

        starting_close = eligible_closes[position][1]
        eligible_classifications += 1

        for horizon in HORIZONS:
            future_position = position + horizon

            if future_position >= len(eligible_closes):
                record["unavailable"][horizon] += 1
                continue

            future_close = eligible_closes[future_position][1]

            forward_return = (
                (future_close / starting_close) - 1
            ) * 100

            record["returns"][horizon].append(forward_return)

    phase_summaries = []

    for phase in PHASES:
        record = phase_records[phase]
        excluded = phase == "INSUFFICIENT_DATA"

        horizon_summaries = []

        for horizon in HORIZONS:
            returns = record["returns"][horizon]
            sample_count = len(returns)

            if excluded:
                unavailable_count = 0
            else:
                unavailable_count = record["unavailable"][horizon]

            horizon_summaries.append(
                ForwardReturnHorizonSummary(
                    horizon_candles=horizon,
                    sample_count=sample_count,
                    unavailable_count=unavailable_count,
                    average_return_pct=(
                        round(mean(returns), 6)
                        if sample_count else None
                    ),
                    median_return_pct=(
                        round(median(returns), 6)
                        if sample_count else None
                    ),
                    positive_return_pct=(
                        round(
                            sum(value > 0 for value in returns)
                            / sample_count * 100,
                            4,
                        )
                        if sample_count else None
                    ),
                )
            )

        phase_summaries.append(
            PhaseForwardReturnSummary(
                cycle_classification=phase,
                classified_candle_count=record["classified_count"],
                excluded_from_return_analysis=excluded,
                horizons=horizon_summaries,
            )
        )

    total_classifications = len(classifications)

    if total_classifications > 0:
        availability_status = "available"
        availability_message = None
    elif base_count > 0:
        availability_status = "no_records_in_range"
        availability_message = (
            "No classifications match the requested date range."
        )
    else:
        availability_status = "no_data"
        availability_message = (
            "No market-cycle classifications are available "
            "for this instrument, timeframe, and batch."
        )

    return ResearchForwardReturnsResponse(
        instrument_code=index.code,
        timeframe=timeframe,
        batch=BatchMetadata.model_validate(batch),
        start_date=start_date,
        end_date=end_date,
        phases=phase_summaries,
        total_classifications=total_classifications,
        eligible_classifications=eligible_classifications,
        availability_status=availability_status,
        availability_message=availability_message,
    )
