from sqlalchemy import (
    cast,
    func,
    literal,
    null,
    select,
    union_all,
    String,
    Integer,
)
from sqlalchemy.orm import Session

from app.models.index import Index
from app.models.historical import (
    DailyOHLCV,
    AggregatedOHLCV,
    TechnicalIndicatorValue,
    MarketStructureSnapshot,
    MarketCycleClassification,
)
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
)
from app.schemas.multi_timeframe import (
    MultiTimeframeResponse,
    MultiTimeframeSnapshot,
    MultiTimeframePeriod,
    MultiTimeframeMarketData,
    MultiTimeframeIndicators,
    MultiTimeframeStructure,
    MultiTimeframeCycle,
    MultiTimeframeAvailability,
)
from app.services.api_errors import (
    InstrumentNotFoundError,
    UnsupportedInstrumentCategoryError,
)
from app.services.batch_service import resolve_import_batch


TIMEFRAMES = ("1D", "1W", "1M", "1Y")


def _get_active_instrument(db: Session, instrument_code: str) -> str:
    code = instrument_code.strip().upper()

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

    if index.category != "market_index":
        raise UnsupportedInstrumentCategoryError(
            f"Instrument '{code}' has category '{index.category}'. "
            "Multi-Timeframe Analysis V1 supports market indices only."
        )

    return code


def _build_eligible_sources(
    *,
    batch_id: int,
    instrument_code: str,
):
    daily_sources = select(
        DailyOHLCV.import_batch_id.label("import_batch_id"),
        DailyOHLCV.instrument_code.label("instrument_code"),
        literal("1D").label("timeframe"),
        DailyOHLCV.candle_date.label("period_start"),
        DailyOHLCV.candle_date.label("period_end"),
        DailyOHLCV.open.label("open"),
        DailyOHLCV.high.label("high"),
        DailyOHLCV.low.label("low"),
        DailyOHLCV.close.label("close"),
        DailyOHLCV.volume.label("volume"),
        DailyOHLCV.volume_status.label("volume_status"),
        DailyOHLCV.quality_status.label("source_status"),
        literal("daily_ohlcv").label("source_table"),
        cast(null(), String).label("boundary_alignment_status"),
        cast(null(), String).label("session_coverage_status"),
        cast(null(), Integer).label("session_count"),
    ).where(
        DailyOHLCV.import_batch_id == batch_id,
        DailyOHLCV.instrument_code == instrument_code,
        DailyOHLCV.quality_status == "accepted",
    )

    aggregate_sources = select(
        AggregatedOHLCV.import_batch_id.label("import_batch_id"),
        AggregatedOHLCV.instrument_code.label("instrument_code"),
        AggregatedOHLCV.timeframe.label("timeframe"),
        AggregatedOHLCV.period_start.label("period_start"),
        AggregatedOHLCV.period_end.label("period_end"),
        AggregatedOHLCV.open.label("open"),
        AggregatedOHLCV.high.label("high"),
        AggregatedOHLCV.low.label("low"),
        AggregatedOHLCV.close.label("close"),
        AggregatedOHLCV.volume.label("volume"),
        AggregatedOHLCV.volume_status.label("volume_status"),
        AggregatedOHLCV.period_status.label("source_status"),
        literal("aggregated_ohlcv").label("source_table"),
        AggregatedOHLCV.boundary_alignment_status.label(
            "boundary_alignment_status"
        ),
        AggregatedOHLCV.session_coverage_status.label(
            "session_coverage_status"
        ),
        AggregatedOHLCV.session_count.label("session_count"),
    ).where(
        AggregatedOHLCV.import_batch_id == batch_id,
        AggregatedOHLCV.instrument_code == instrument_code,
        AggregatedOHLCV.timeframe.in_(("1W", "1M", "1Y")),
        AggregatedOHLCV.period_status == "completed",
        AggregatedOHLCV.boundary_alignment_status == "aligned",
    )

    return union_all(
        daily_sources,
        aggregate_sources,
    ).subquery("eligible_market_sources")


def get_multi_timeframe_analysis(
    db: Session,
    *,
    instrument_code: str,
    import_batch_id: int | None = None,
) -> MultiTimeframeResponse:
    """
    Retrieve the latest eligible market snapshot for each timeframe.

    This service is read-only. It does not calculate, update,
    or regenerate historical market data or analytical records.
    """

    code = _get_active_instrument(db, instrument_code)

    batch = resolve_import_batch(
        db,
        import_batch_id=import_batch_id,
    )

    eligible_sources = _build_eligible_sources(
        batch_id=batch.id,
        instrument_code=code,
    )

    ranked_sources = (
        select(
            eligible_sources,
            func.row_number()
            .over(
                partition_by=eligible_sources.c.timeframe,
                order_by=eligible_sources.c.period_start.desc(),
            )
            .label("row_number"),
        )
        .subquery("ranked_market_sources")
    )

    join_conditions = (
        (TechnicalIndicatorValue.import_batch_id == ranked_sources.c.import_batch_id)
        & (TechnicalIndicatorValue.instrument_code == ranked_sources.c.instrument_code)
        & (TechnicalIndicatorValue.timeframe == ranked_sources.c.timeframe)
        & (TechnicalIndicatorValue.period_start == ranked_sources.c.period_start)
    )

    structure_conditions = (
        (MarketStructureSnapshot.import_batch_id == ranked_sources.c.import_batch_id)
        & (MarketStructureSnapshot.instrument_code == ranked_sources.c.instrument_code)
        & (MarketStructureSnapshot.timeframe == ranked_sources.c.timeframe)
        & (MarketStructureSnapshot.period_start == ranked_sources.c.period_start)
    )

    cycle_conditions = (
        (MarketCycleClassification.import_batch_id == ranked_sources.c.import_batch_id)
        & (MarketCycleClassification.instrument_code == ranked_sources.c.instrument_code)
        & (MarketCycleClassification.timeframe == ranked_sources.c.timeframe)
        & (MarketCycleClassification.period_start == ranked_sources.c.period_start)
    )

    statement = (
        select(
            *(ranked_sources.c[column] for column in ranked_sources.c.keys()),
            TechnicalIndicatorValue,
            MarketStructureSnapshot,
            MarketCycleClassification,
        )
        .select_from(ranked_sources)
        .outerjoin(
            TechnicalIndicatorValue,
            join_conditions,
        )
        .outerjoin(
            MarketStructureSnapshot,
            structure_conditions,
        )
        .outerjoin(
            MarketCycleClassification,
            cycle_conditions,
        )
        .where(ranked_sources.c.row_number == 1)
        .order_by(ranked_sources.c.timeframe)
    )

    results = db.execute(statement).all()

    snapshots = {
        timeframe: MultiTimeframeSnapshot(
            availability=MultiTimeframeAvailability(
                status="no_data",
                is_available=False,
                indicator_available=False,
                indicator_status=None,
                structure_available=False,
                cycle_available=False,
                message=f"No eligible {timeframe} market data is available.",
            )
        )
        for timeframe in TIMEFRAMES
    }

    for result in results:
        row_mapping = result._mapping
        source = row_mapping
        indicator = row_mapping[TechnicalIndicatorValue]
        structure = row_mapping[MarketStructureSnapshot]
        cycle = row_mapping[MarketCycleClassification]

        timeframe = source["timeframe"]

        market_data = MultiTimeframeMarketData(
            source_table=source["source_table"],
            source_status=source["source_status"],
            open=source["open"],
            high=source["high"],
            low=source["low"],
            close=source["close"],
            volume=source["volume"],
            volume_status=source["volume_status"],
            boundary_alignment_status=source["boundary_alignment_status"],
            session_coverage_status=source["session_coverage_status"],
            session_count=source["session_count"],
        )

        indicators = None

        if indicator is not None:
            indicators = MultiTimeframeIndicators(
                moving_averages=MovingAverageIndicators(
                    ema_9=indicator.ema_9,
                    ema_20=indicator.ema_20,
                    ema_50=indicator.ema_50,
                    ema_100=indicator.ema_100,
                    ema_200=indicator.ema_200,
                    sma_222=indicator.sma_222,
                ),
                momentum=MomentumIndicators(
                    rsi_14=indicator.rsi_14,
                ),
                trend=TrendIndicators(
                    adx_14=indicator.adx_14,
                    plus_di_14=indicator.plus_di_14,
                    minus_di_14=indicator.minus_di_14,
                ),
                macd=MACDIndicators(
                    line_12_26=indicator.macd_line_12_26,
                    signal_9=indicator.macd_signal_9,
                    histogram=indicator.macd_histogram,
                ),
                volatility=VolatilityIndicators(
                    atr_14=indicator.atr_14,
                    chop_14=indicator.chop_14,
                    bollinger_bandwidth_20_2=indicator.bollinger_bandwidth_20_2,
                    bollinger_upper_20_2=indicator.bollinger_upper_20_2,
                    bollinger_middle_20_2=indicator.bollinger_middle_20_2,
                    bollinger_lower_20_2=indicator.bollinger_lower_20_2,
                ),
                calculation=IndicatorCalculationMetadata(
                    status=indicator.calculation_status,
                    version=indicator.calculation_version,
                    generated_at_utc=indicator.generated_at_utc,
                ),
            )

        structure_record = None

        if structure is not None:
            structure_record = MultiTimeframeStructure(
                source_close=structure.source_close,
                support=SupportLevel(
                    price=structure.support_price,
                    pivot_date=structure.support_pivot_date,
                    confirmation_date=structure.support_confirmation_date,
                    classification=structure.support_classification,
                ),
                resistance=ResistanceLevel(
                    price=structure.resistance_price,
                    pivot_date=structure.resistance_pivot_date,
                    confirmation_date=structure.resistance_confirmation_date,
                    classification=structure.resistance_classification,
                ),
                market_structure_state=structure.market_structure_state,
                breakout_status=structure.breakout_status,
                range_position=structure.range_position,
                left_bars=structure.left_bars,
                right_bars=structure.right_bars,
                equal_tolerance_pct=structure.equal_tolerance_pct,
                calculation_version=structure.calculation_version,
                generated_at_utc=structure.generated_at_utc,
            )

        cycle_record = None

        if cycle is not None:
            cycle_record = MultiTimeframeCycle(
                cycle_classification=cycle.cycle_classification,
                rule_score=cycle.rule_score,
                bandwidth_percentile=cycle.bandwidth_percentile,
                classification_basis=cycle.classification_basis,
                evidence=cycle.evidence,
                missing_inputs=cycle.missing_inputs,
                config_json=cycle.config_json,
                calculation_version=cycle.calculation_version,
                generated_at_utc=cycle.generated_at_utc,
            )

        indicator_status = (
            indicator.calculation_status
            if indicator is not None
            else None
        )

        all_components_available = (
            indicator is not None
            and structure is not None
            and cycle is not None
            and indicator_status == "ready"
        )

        availability_status = (
            "available"
            if all_components_available
            else "partial"
        )

        missing_components = []

        if indicator is None:
            missing_components.append("technical indicators")
        elif indicator_status != "ready":
            missing_components.append(
                f"indicators are {indicator_status}"
            )

        if structure is None:
            missing_components.append("market structure")

        if cycle is None:
            missing_components.append("market cycle")

        availability_message = (
            None
            if not missing_components
            else "Snapshot is incomplete: " + ", ".join(missing_components) + "."
        )

        snapshots[timeframe] = MultiTimeframeSnapshot(
            period=MultiTimeframePeriod(
                timeframe=timeframe,
                period_start=source["period_start"],
                period_end=source["period_end"],
            ),
            market_data=market_data,
            indicators=indicators,
            structure=structure_record,
            cycle=cycle_record,
            availability=MultiTimeframeAvailability(
                status=availability_status,
                is_available=True,
                indicator_available=indicator is not None,
                indicator_status=indicator_status,
                structure_available=structure is not None,
                cycle_available=cycle is not None,
                message=availability_message,
            ),
        )

    return MultiTimeframeResponse(
        instrument_code=code,
        batch=BatchMetadata.model_validate(batch),
        timeframes=snapshots,
    )
