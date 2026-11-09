
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from typing import Iterable, Literal, Mapping
from zoneinfo import ZoneInfo


Timeframe = Literal["1W", "1M", "1Y"]
PeriodStatus = Literal["provisional", "completed"]
VolumeStatus = Literal["complete", "partial", "unavailable"]

INDIA_TZ = timezone(
    timedelta(hours=5, minutes=30),
    name="IST"
)

SUPPORTED_TIMEFRAMES = ("1W", "1M", "1Y")


class CandleValidationError(ValueError):
    """Raised when daily OHLCV input is invalid."""


@dataclass(frozen=True)
class DailyCandle:
    session_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int | None


@dataclass(frozen=True)
class AggregatedCandle:
    timeframe: Timeframe

    # Calendar boundaries, not necessarily trading dates.
    period_start: date
    period_end: date

    # Actual first and last available trading dates.
    first_session_date: date
    last_session_date: date

    open: float
    high: float
    low: float
    close: float

    volume: int | None
    volume_status: VolumeStatus

    session_count: int
    period_status: PeriodStatus

    @property
    def candle_time(self) -> datetime:
        """Calendar-period start at midnight, without timezone."""
        return datetime.combine(self.period_start, time.min)


def _parse_session_date(value) -> date:
    """Convert a timestamp into its Indian market trading date."""

    if isinstance(value, datetime):
        timestamp = value

        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(INDIA_TZ)

        return timestamp.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        try:
            timestamp = datetime.fromisoformat(value.strip())

            if timestamp.tzinfo is not None:
                timestamp = timestamp.astimezone(INDIA_TZ)

            return timestamp.date()

        except ValueError as exc:
            raise CandleValidationError(
                f"Invalid timestamp: {value}"
            ) from exc

    raise CandleValidationError(
        f"Unsupported timestamp type: {type(value).__name__}"
    )


def _parse_price(value, field_name: str) -> float:
    try:
        price = float(value)
    except (TypeError, ValueError) as exc:
        raise CandleValidationError(
            f"Invalid {field_name}: {value}"
        ) from exc

    if not isfinite(price) or price <= 0:
        raise CandleValidationError(
            f"{field_name} must be a finite positive number."
        )

    return price


def _parse_volume(value) -> int | None:
    if value is None:
        return None

    try:
        numeric_volume = float(value)
    except (TypeError, ValueError) as exc:
        raise CandleValidationError(
            f"Invalid volume: {value}"
        ) from exc

    if (
        not isfinite(numeric_volume)
        or numeric_volume < 0
        or not numeric_volume.is_integer()
    ):
        raise CandleValidationError(
            f"Volume must be a non-negative integer: {value}"
        )

    return int(numeric_volume)


def normalize_daily_candle(record: Mapping) -> DailyCandle:
    """Validate and normalize one Daily OHLCV record."""

    required_fields = (
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
    )

    missing_fields = [
        field for field in required_fields
        if field not in record
    ]

    if missing_fields:
        raise CandleValidationError(
            f"Missing fields: {', '.join(missing_fields)}"
        )

    session_date = _parse_session_date(record["timestamp"])

    open_price = _parse_price(record["open"], "open")
    high_price = _parse_price(record["high"], "high")
    low_price = _parse_price(record["low"], "low")
    close_price = _parse_price(record["close"], "close")

    if high_price < low_price:
        raise CandleValidationError(
            f"High is below Low on {session_date}"
        )

    if high_price < max(open_price, close_price):
        raise CandleValidationError(
            f"High is below Open or Close on {session_date}"
        )

    if low_price > min(open_price, close_price):
        raise CandleValidationError(
            f"Low is above Open or Close on {session_date}"
        )

    volume = _parse_volume(record["volume"])

    return DailyCandle(
        session_date=session_date,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
    )


def normalize_daily_data(
    records: Iterable[Mapping],
) -> list[DailyCandle]:
    """
    Normalize and sort Daily candles.

    Duplicate trading dates are rejected rather than silently
    selecting or merging potentially conflicting records.
    """

    candles = [
        normalize_daily_candle(record)
        for record in records
    ]

    candles.sort(key=lambda candle: candle.session_date)

    seen_dates = set()

    for candle in candles:
        if candle.session_date in seen_dates:
            raise CandleValidationError(
                f"Duplicate daily candle: {candle.session_date}"
            )

        seen_dates.add(candle.session_date)

    return candles


def get_period_bounds(
    session_date: date,
    timeframe: Timeframe,
) -> tuple[date, date]:

    if timeframe == "1W":
        # Monday through Sunday.
        period_start = (
            session_date
            - timedelta(days=session_date.weekday())
        )

        period_end = period_start + timedelta(days=6)

    elif timeframe == "1M":
        period_start = date(
            session_date.year,
            session_date.month,
            1,
        )

        if session_date.month == 12:
            next_month = date(session_date.year + 1, 1, 1)
        else:
            next_month = date(
                session_date.year,
                session_date.month + 1,
                1,
            )

        period_end = next_month - timedelta(days=1)

    elif timeframe == "1Y":
        # Calendar year: January 1 through December 31.
        period_start = date(session_date.year, 1, 1)
        period_end = date(session_date.year, 12, 31)

    else:
        raise ValueError(
            f"Unsupported timeframe: {timeframe}"
        )

    return period_start, period_end


def _get_as_of_date(value: date | None) -> date:
    if value is not None:
        return value

    return datetime.now(INDIA_TZ).date()


def _aggregate_group(
    candles: list[DailyCandle],
    timeframe: Timeframe,
    period_start: date,
    period_end: date,
    as_of_date: date,
) -> AggregatedCandle:

    candles.sort(key=lambda candle: candle.session_date)

    volumes = [candle.volume for candle in candles]

    # All-zero volume is treated as unavailable for index analytics.
    # Original source values remain unchanged in daily storage.
    if all(volume is None or volume == 0 for volume in volumes):
        volume = None
        volume_status: VolumeStatus = "unavailable"

    elif all(volume is not None for volume in volumes):
        volume = sum(volumes)
        volume_status = "complete"

    else:
        volume = None
        volume_status = "partial"

    # A period remains provisional until its entire
    # calendar period has elapsed.
    period_status: PeriodStatus = (
        "completed"
        if period_end < as_of_date
        else "provisional"
    )

    return AggregatedCandle(
        timeframe=timeframe,
        period_start=period_start,
        period_end=period_end,

        first_session_date=candles[0].session_date,
        last_session_date=candles[-1].session_date,

        open=candles[0].open,
        high=max(candle.high for candle in candles),
        low=min(candle.low for candle in candles),
        close=candles[-1].close,

        volume=volume,
        volume_status=volume_status,

        session_count=len(candles),
        period_status=period_status,
    )


def aggregate_daily_candles(
    records: Iterable[Mapping],
    timeframe: Timeframe,
    as_of_date: date | None = None,
) -> list[AggregatedCandle]:
    """
    Aggregate Daily OHLCV into Weekly, Monthly or Yearly candles.

    All output candles are generated directly from Daily records.
    """

    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(
            f"Unsupported timeframe: {timeframe}. "
            f"Supported: {SUPPORTED_TIMEFRAMES}"
        )

    daily_candles = normalize_daily_data(records)
    reference_date = _get_as_of_date(as_of_date)

    groups = defaultdict(list)

    for candle in daily_candles:
        period_start, period_end = get_period_bounds(
            candle.session_date,
            timeframe,
        )

        groups[(period_start, period_end)].append(candle)

    result = []

    for (period_start, period_end), group in sorted(
        groups.items()
    ):
        aggregated = _aggregate_group(
            candles=group,
            timeframe=timeframe,
            period_start=period_start,
            period_end=period_end,
            as_of_date=reference_date,
        )

        result.append(aggregated)

    return result


def aggregate_all_timeframes(
    records: Iterable[Mapping],
    as_of_date: date | None = None,
) -> dict[str, list[AggregatedCandle]]:
    """
    Generate Weekly, Monthly and Calendar-Year candles
    independently from the same Daily source data.
    """

    # Normalize once and reuse the same validated Daily input.
    daily_candles = normalize_daily_data(records)

    normalized_records = [
        {
            "timestamp": candle.session_date,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
        }
        for candle in daily_candles
    ]

    return {
        timeframe: aggregate_daily_candles(
            normalized_records,
            timeframe,
            as_of_date,
        )
        for timeframe in SUPPORTED_TIMEFRAMES
    }
