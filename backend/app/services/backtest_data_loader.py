from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.engines.indicator_engine import PRICE_INDEX_CODES


_DAILY_BACKTEST_QUERY = text(
    """
    SELECT
        d.import_batch_id,
        d.instrument_code,
        d.candle_date,
        d.open,
        d.high,
        d.low,
        d.close,
        d.volume,
        d.volume_status,
        d.quality_status AS price_quality_status,
        d.issue_codes AS price_issue_codes,

        i.import_batch_id AS indicator_join_batch_id,
        i.source_status AS indicator_source_status,
        i.calculation_status AS indicator_calculation_status,
        i.calculation_version AS indicator_calculation_version,

        i.ema_9,
        i.ema_20,
        i.ema_50,
        i.ema_100,
        i.ema_200,
        i.sma_222,
        i.rsi_14,
        i.adx_14,
        i.plus_di_14,
        i.minus_di_14,
        i.macd_line_12_26,
        i.macd_signal_9,
        i.macd_histogram,
        i.atr_14,
        i.bollinger_upper_20_2,
        i.bollinger_middle_20_2,
        i.bollinger_lower_20_2,
        i.chop_14,
        i.bollinger_bandwidth_20_2,

        s.import_batch_id AS structure_join_batch_id,
        s.support_price,
        s.support_pivot_date,
        s.support_confirmation_date,
        s.support_classification,
        s.resistance_price,
        s.resistance_pivot_date,
        s.resistance_confirmation_date,
        s.resistance_classification,
        s.market_structure_state,
        s.breakout_status,
        s.range_position,

        c.import_batch_id AS cycle_join_batch_id,
        c.cycle_classification,
        c.rule_score AS cycle_rule_score,
        c.bandwidth_percentile AS cycle_bandwidth_percentile,
        c.classification_basis AS cycle_classification_basis,
        c.evidence AS cycle_evidence,
        c.missing_inputs AS cycle_missing_inputs,
        c.calculation_version AS cycle_calculation_version

    FROM daily_ohlcv AS d

    LEFT JOIN technical_indicator_values AS i
        ON i.import_batch_id = d.import_batch_id
       AND i.instrument_code = d.instrument_code
       AND i.timeframe = '1D'
       AND i.period_start = d.candle_date

    LEFT JOIN market_structure_snapshots AS s
        ON s.import_batch_id = d.import_batch_id
       AND s.instrument_code = d.instrument_code
       AND s.timeframe = '1D'
       AND s.period_start = d.candle_date

    LEFT JOIN market_cycle_classifications AS c
        ON c.import_batch_id = d.import_batch_id
       AND c.instrument_code = d.instrument_code
       AND c.timeframe = '1D'
       AND c.period_start = d.candle_date

    WHERE d.import_batch_id = :import_batch_id
      AND d.instrument_code = :instrument_code
      AND d.quality_status = 'accepted'
      AND d.candle_date >= COALESCE(
          :start_date, DATE '0001-01-01'
      )
      AND d.candle_date <= COALESCE(
          :end_date, DATE '9999-12-31'
      )

    ORDER BY d.candle_date ASC
    """
)


def load_daily_backtest_data(
    session: Session,
    *,
    import_batch_id: int,
    instrument_code: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    """
    Load accepted daily OHLCV candles with their calculated context.

    Reads:
        - daily_ohlcv
        - technical_indicator_values
        - market_structure_snapshots
        - market_cycle_classifications

    Only the five supported price indices are accepted.
    India VIX is intentionally excluded from this loader.

    All joins use the historical composite business key:
        import_batch_id, instrument_code, timeframe, period_start

    Indicator calculation statuses and market-cycle classifications
    are preserved. Partial, warming-up and insufficient-data records
    are not silently removed.

    The function is read-only. Transaction ownership remains with
    the caller.

    Signals and trade execution are not performed by this loader.
    """

    if import_batch_id <= 0:
        raise ValueError("import_batch_id must be positive.")

    normalized_instrument = instrument_code.strip().upper()

    if normalized_instrument not in PRICE_INDEX_CODES:
        allowed = ", ".join(sorted(PRICE_INDEX_CODES))
        raise ValueError(
            f"Unsupported instrument: {normalized_instrument}. "
            f"Supported instruments: {allowed}"
        )

    if (
        start_date is not None
        and end_date is not None
        and start_date > end_date
    ):
        raise ValueError("start_date cannot be later than end_date.")

    params = {
        "import_batch_id": import_batch_id,
        "instrument_code": normalized_instrument,
        "start_date": start_date,
        "end_date": end_date,
    }

    result = session.execute(
        _DAILY_BACKTEST_QUERY,
        params,
    ).mappings().all()

    records = [dict(row) for row in result]

    # Ensure the loader has not returned duplicate daily candles.
    candle_dates = [row["candle_date"] for row in records]

    if len(candle_dates) != len(set(candle_dates)):
        raise RuntimeError(
            "Duplicate daily candle dates detected in backtest data."
        )

    # Every accepted candle must have its three calculated context rows.
    join_markers = {
        "indicator_join_batch_id": "technical indicators",
        "structure_join_batch_id": "market structure",
        "cycle_join_batch_id": "market cycle classifications",
    }

    missing_context: dict[str, list[date]] = {
        table_name: []
        for table_name in join_markers.values()
    }

    for record in records:
        for marker, table_name in join_markers.items():
            if record[marker] is None:
                missing_context[table_name].append(
                    record["candle_date"]
                )

    incomplete = {
        table_name: dates
        for table_name, dates in missing_context.items()
        if dates
    }

    if incomplete:
        details = "; ".join(
            f"{table}: {len(dates)} missing, "
            f"first dates: {dates[:5]}"
            for table, dates in incomplete.items()
        )

        raise RuntimeError(
            "Incomplete calculated context in backtest dataset. "
            + details
        )

    # Internal join markers are used only for integrity validation.
    for record in records:
        for marker in join_markers:
            record.pop(marker)

    return records


__all__ = ["load_daily_backtest_data"]
