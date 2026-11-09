"""Pure technical-indicator calculations for Market Cycle Tracker.

EMA initialization uses an SMA seed. Calculations use Decimal arithmetic.
Excluded source candles reset the calculation run; they are never bridged.
"""
from __future__ import annotations

from collections import deque
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Any, Iterable, Mapping

EMA_PERIODS = (9, 20, 50, 100, 200)
SMA_PERIOD = 222
SUPPORTED_TIMEFRAMES = ("1D", "1W", "1M", "1Y")
PRICE_INDEX_CODES = ("NIFTY50", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY")
INDIA_VIX_CODE = "INDIA_VIX"
CALCULATION_VERSION = "indicator_v1_sma_seeded"
PRICE_QUANTUM = Decimal("0.00000001")


class IndicatorCalculationError(ValueError):
    """Raised when indicator input data is invalid or unsupported."""


def _as_date(value: Any, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise IndicatorCalculationError(f"Invalid {field_name}: {value!r}") from exc


def _as_decimal(value: Any) -> Decimal:
    if value is None:
        raise IndicatorCalculationError("Candle close cannot be NULL.")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise IndicatorCalculationError(f"Invalid candle close: {value!r}") from exc
    if not result.is_finite():
        raise IndicatorCalculationError(f"Candle close must be finite: {value!r}")
    return result


def _quantize(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)


def _next_month(value: date) -> date:
    return date(value.year + 1, 1, 1) if value.month == 12 else date(value.year, value.month + 1, 1)


def _next_period_start(value: date, timeframe: str) -> date | None:
    if timeframe == "1D":
        # The exchange calendar is not part of this calculation layer.
        # Daily gaps cannot safely be classified as missing trading sessions.
        return None
    if timeframe == "1W":
        return value + timedelta(days=7)
    if timeframe == "1M":
        return _next_month(value)
    if timeframe == "1Y":
        return date(value.year + 1, 1, 1)
    raise IndicatorCalculationError(f"Unsupported timeframe: {timeframe}")


def _is_eligible(row: Mapping[str, Any], timeframe: str) -> bool:
    status = str(row.get("source_status") or "").lower()
    if timeframe == "1D":
        return status == "accepted"
    alignment = str(row.get("boundary_alignment_status") or "").lower()
    return status == "completed" and alignment == "aligned"


class _IndicatorState:
    """State for one uninterrupted run of eligible closes."""

    def __init__(self) -> None:
        self.count = 0
        self.seed_sums = {period: Decimal(0) for period in EMA_PERIODS}
        self.ema_values: dict[int, Decimal | None] = {period: None for period in EMA_PERIODS}
        self.sma_values: deque[Decimal] = deque()
        self.sma_total = Decimal(0)

    def reset(self) -> None:
        self.__init__()

    def update(self, close: Decimal) -> dict[str, Decimal | None]:
        self.count += 1
        values: dict[str, Decimal | None] = {}
        for period in EMA_PERIODS:
            previous = self.ema_values[period]
            if previous is None:
                self.seed_sums[period] += close
                if self.count >= period:
                    previous = self.seed_sums[period] / Decimal(period)
                    self.ema_values[period] = previous
            else:
                alpha = Decimal(2) / Decimal(period + 1)
                previous = close * alpha + previous * (Decimal(1) - alpha)
                self.ema_values[period] = previous
            values[f"ema_{period}"] = previous

        self.sma_values.append(close)
        self.sma_total += close
        if len(self.sma_values) > SMA_PERIOD:
            self.sma_total -= self.sma_values.popleft()
        values["sma_222"] = (
            self.sma_total / Decimal(SMA_PERIOD)
            if len(self.sma_values) == SMA_PERIOD else None
        )
        return values

    @staticmethod
    def calculation_status(values: Mapping[str, Decimal | None]) -> str:
        if values["ema_9"] is None:
            return "warming_up"
        if values["sma_222"] is None:
            return "partial"
        return "ready"


def calculate_indicator_series(
    candles: Iterable[Mapping[str, Any]],
    *,
    instrument_code: str,
    timeframe: str,
    import_batch_id: int,
    generated_at_utc: datetime | None = None,
    calculation_version: str = CALCULATION_VERSION,
) -> list[dict[str, Any]]:
    """Calculate five EMAs and SMA 222 for one instrument/timeframe series.

    Expected fields: period_start, period_end, close, source_status. Aggregate
    candles also require boundary_alignment_status and session_coverage_status.
    Ineligible rows are omitted and reset all indicator state. Missing aggregate
    calendar buckets also reset state. Daily gaps are not inferred from dates.
    """
    code = str(instrument_code).upper()
    if code == INDIA_VIX_CODE:
        raise IndicatorCalculationError("INDIA_VIX is excluded from the standard EMA/SMA engine.")
    if code not in PRICE_INDEX_CODES:
        raise IndicatorCalculationError(f"Unsupported instrument: {instrument_code}")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise IndicatorCalculationError(f"Unsupported timeframe: {timeframe}")
    if import_batch_id <= 0:
        raise IndicatorCalculationError("import_batch_id must be positive.")

    normalized: list[tuple[date, date, Decimal, Mapping[str, Any]]] = []
    seen: set[date] = set()
    for row in candles:
        start = _as_date(row.get("period_start"), "period_start")
        end = _as_date(row.get("period_end", row.get("period_start")), "period_end")
        if end < start:
            raise IndicatorCalculationError(f"period_end {end} precedes period_start {start}.")
        if start in seen:
            raise IndicatorCalculationError(f"Duplicate {timeframe} period_start: {start}.")
        seen.add(start)
        normalized.append((start, end, _as_decimal(row.get("close")), row))
    normalized.sort(key=lambda item: item[0])

    generated = generated_at_utc or datetime.now(timezone.utc)
    if generated.tzinfo is None:
        raise IndicatorCalculationError("generated_at_utc must be timezone-aware.")

    source_table = "daily_ohlcv" if timeframe == "1D" else "aggregated_ohlcv"
    state = _IndicatorState()
    previous_eligible_start: date | None = None
    results: list[dict[str, Any]] = []

    with localcontext() as context:
        context.prec = 40
        for period_start, period_end, close, source_row in normalized:
            if not _is_eligible(source_row, timeframe):
                state.reset()
                previous_eligible_start = None
                continue

            if previous_eligible_start is not None:
                expected = _next_period_start(previous_eligible_start, timeframe)
                if expected is not None and period_start != expected:
                    state.reset()

            values = state.update(close)
            results.append({
                "import_batch_id": import_batch_id,
                "instrument_code": code,
                "timeframe": timeframe,
                "period_start": period_start,
                "period_end": period_end,
                "source_table": source_table,
                "source_status": str(source_row.get("source_status")),
                "boundary_alignment_status": source_row.get("boundary_alignment_status") if timeframe != "1D" else None,
                "session_coverage_status": source_row.get("session_coverage_status") if timeframe != "1D" else None,
                "source_close": _quantize(close),
                "ema_9": _quantize(values["ema_9"]),
                "ema_20": _quantize(values["ema_20"]),
                "ema_50": _quantize(values["ema_50"]),
                "ema_100": _quantize(values["ema_100"]),
                "ema_200": _quantize(values["ema_200"]),
                "sma_222": _quantize(values["sma_222"]),
                "calculation_status": state.calculation_status(values),
                "calculation_version": calculation_version,
                "generated_at_utc": generated,
            })
            previous_eligible_start = period_start
    return results
