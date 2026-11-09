from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping

from app.engines.candlestick_pattern_config import (
    CALCULATION_VERSION,
    DEFAULT_PATTERN_CONFIG,
    CandlestickPatternConfig,
)


class CandlestickPatternError(ValueError):
    """Raised when candle data or pattern configuration is invalid."""


ZERO = Decimal("0")


@dataclass(frozen=True)
class CandleGeometry:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    direction: str

    body_size: Decimal
    upper_wick: Decimal
    lower_wick: Decimal
    total_range: Decimal

    body_range_ratio: Decimal
    upper_wick_range_ratio: Decimal
    lower_wick_range_ratio: Decimal


@dataclass(frozen=True)
class CandlestickPatternResult:
    calculation_version: str
    geometry: CandleGeometry
    patterns: tuple[str, ...]


def _as_decimal(value, field_name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CandlestickPatternError(
            f"Invalid {field_name}: {value}"
        ) from exc

    if not number.is_finite():
        raise CandlestickPatternError(
            f"{field_name} must be finite."
        )

    return number


def _normalize_ohlc(
    record: Mapping,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:

    if not isinstance(record, Mapping):
        raise CandlestickPatternError(
        "Candle data must be a mapping."
    )

    required = ("open", "high", "low", "close")

    missing = [
        field for field in required
        if field not in record
    ]

    if missing:
        raise CandlestickPatternError(
            f"Missing OHLC fields: {', '.join(missing)}"
        )

    open_price = _as_decimal(record["open"], "open")
    high_price = _as_decimal(record["high"], "high")
    low_price = _as_decimal(record["low"], "low")
    close_price = _as_decimal(record["close"], "close")

    if min(open_price, high_price, low_price, close_price) <= ZERO:
        raise CandlestickPatternError(
            "OHLC prices must be positive."
        )

    if high_price < low_price:
        raise CandlestickPatternError("High is below Low.")

    if high_price < max(open_price, close_price):
        raise CandlestickPatternError(
            "High is below Open or Close."
        )

    if low_price > min(open_price, close_price):
        raise CandlestickPatternError(
            "Low is above Open or Close."
        )

    return open_price, high_price, low_price, close_price


def calculate_candle_geometry(
    record: Mapping,
) -> CandleGeometry:

    open_price, high_price, low_price, close_price = (
        _normalize_ohlc(record)
    )

    total_range = high_price - low_price
    body_size = abs(close_price - open_price)

    upper_wick = high_price - max(open_price, close_price)
    lower_wick = min(open_price, close_price) - low_price

    if close_price > open_price:
        direction = "BULLISH"
    elif close_price < open_price:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    # Four-Price Doji has no price range.
    # It is handled as a valid special candle.
    if total_range == ZERO:
        return CandleGeometry(
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            direction=direction,
            body_size=body_size,
            upper_wick=upper_wick,
            lower_wick=lower_wick,
            total_range=total_range,
            body_range_ratio=ZERO,
            upper_wick_range_ratio=ZERO,
            lower_wick_range_ratio=ZERO,
        )

    return CandleGeometry(
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        direction=direction,
        body_size=body_size,
        upper_wick=upper_wick,
        lower_wick=lower_wick,
        total_range=total_range,
        body_range_ratio=body_size / total_range,
        upper_wick_range_ratio=upper_wick / total_range,
        lower_wick_range_ratio=lower_wick / total_range,
    )


def identify_single_candle_patterns(
    geometry: CandleGeometry,
    config: CandlestickPatternConfig = DEFAULT_PATTERN_CONFIG,
) -> tuple[str, ...]:

    if not isinstance(config, CandlestickPatternConfig):
        raise CandlestickPatternError(
        "config must be a CandlestickPatternConfig."
    )
    patterns = []

    body_ratio = geometry.body_range_ratio
    upper_ratio = geometry.upper_wick_range_ratio
    lower_ratio = geometry.lower_wick_range_ratio

    # --------------------------------------------------
    # 1. FOUR-PRICE DOJI
    # --------------------------------------------------

    if geometry.total_range == ZERO:
        return ("FOUR_PRICE_DOJI",)

    
    # --------------------------------------------------
    # 2. DOJI FAMILY
    # --------------------------------------------------

    is_doji = (
        body_ratio <= config.doji_max_body_ratio
    )

    is_high_wave = (
        body_ratio <= config.spinning_top_max_body_ratio
        and upper_ratio >= config.high_wave_min_wick_ratio
        and lower_ratio >= config.high_wave_min_wick_ratio
    )

    if is_doji:
        patterns.append("DOJI")

        # Long-Legged Doji
        if (
            upper_ratio >= config.long_legged_doji_min_wick_ratio
            and lower_ratio >= config.long_legged_doji_min_wick_ratio
        ):
            patterns.append("LONG_LEGGED_DOJI")

        # Dragonfly Doji
        if (
            lower_ratio >= config.doji_wick_dominance_ratio
            and upper_ratio <= config.dragonfly_max_upper_wick_ratio
        ):
            patterns.append("DRAGONFLY_DOJI")

        # Gravestone Doji
        if (
            upper_ratio >= config.doji_wick_dominance_ratio
            and lower_ratio <= config.gravestone_max_lower_wick_ratio
        ):
            patterns.append("GRAVESTONE_DOJI")

    # --------------------------------------------------
    # 3. SPINNING TOP
    # --------------------------------------------------

    if (
        not is_doji
        and not is_high_wave
        and body_ratio <= config.spinning_top_max_body_ratio
        and upper_ratio >= config.spinning_top_min_wick_ratio
        and lower_ratio >= config.spinning_top_min_wick_ratio
    ):
        patterns.append("SPINNING_TOP")

    # --------------------------------------------------
    # 4. HAMMER / HANGING MAN SHAPE
    # --------------------------------------------------
    # Geometry only. Trend context will distinguish them.

    if (
        ZERO < body_ratio <= config.hammer_max_body_ratio
        and geometry.lower_wick
        >= geometry.body_size
        * config.hammer_min_lower_wick_body_ratio
        and upper_ratio
        <= config.hammer_max_upper_wick_range_ratio
    ):
        patterns.append("HAMMER_SHAPE")

    # --------------------------------------------------
    # 5. INVERTED HAMMER / SHOOTING STAR SHAPE
    # --------------------------------------------------

    if (
        ZERO < body_ratio <= config.inverted_hammer_max_body_ratio
        and geometry.upper_wick
        >= geometry.body_size
        * config.inverted_hammer_min_upper_wick_body_ratio
        and lower_ratio
        <= config.inverted_hammer_max_lower_wick_range_ratio
    ):
        patterns.append("INVERTED_HAMMER_SHAPE")

    # --------------------------------------------------
    # 6. BULLISH / BEARISH MARUBOZU
    # --------------------------------------------------

    if (
        body_ratio >= config.marubozu_min_body_ratio
        and upper_ratio <= config.marubozu_max_wick_range_ratio
        and lower_ratio <= config.marubozu_max_wick_range_ratio
    ):
        if geometry.direction == "BULLISH":
            patterns.append("BULLISH_MARUBOZU")

        elif geometry.direction == "BEARISH":
            patterns.append("BEARISH_MARUBOZU")

    # --------------------------------------------------
    # 7. HIGH-WAVE CANDLE
    # --------------------------------------------------

    if is_high_wave:
        patterns.append("HIGH_WAVE_CANDLE")

    # --------------------------------------------------
    # 8. LONG-LOWER-WICK CANDLE
    # --------------------------------------------------
    # Generic long lower shadow.
    # Does not require the opposite wick to be nearly zero.

    if (
        lower_ratio >= config.long_wick_min_range_ratio
    ):
        patterns.append("LONG_LOWER_WICK_CANDLE")

    # --------------------------------------------------
    # 9. LONG-UPPER-WICK CANDLE
    # --------------------------------------------------
    # Generic long upper shadow.

    if (
        upper_ratio >= config.long_wick_min_range_ratio
    ):
        patterns.append("LONG_UPPER_WICK_CANDLE")

    return tuple(patterns)


def analyze_candle(
    record: Mapping,
    config: CandlestickPatternConfig = DEFAULT_PATTERN_CONFIG,
) -> CandlestickPatternResult:

    geometry = calculate_candle_geometry(record)

    patterns = identify_single_candle_patterns(
        geometry,
        config,
    )

    return CandlestickPatternResult(
        calculation_version=CALCULATION_VERSION,
        geometry=geometry,
        patterns=patterns,
    )


@dataclass(frozen=True)
class TwoCandlePatternResult:
    calculation_version: str
    patterns: tuple[str, ...]


def analyze_two_candle_patterns(
    previous_record: Mapping,
    current_record: Mapping,
    config: CandlestickPatternConfig = DEFAULT_PATTERN_CONFIG,
) -> TwoCandlePatternResult:
    """
    Identify two-candle patterns using two consecutive completed candles.

    The function recognizes candle geometry only.
    Trend context is evaluated separately.
    """

    if not isinstance(config, CandlestickPatternConfig):
        raise CandlestickPatternError(
            "config must be a CandlestickPatternConfig."
        )

    previous = calculate_candle_geometry(previous_record)
    current = calculate_candle_geometry(current_record)

    patterns = []

    # A previous candle must have a real body.
    if previous.body_size == ZERO:
        return TwoCandlePatternResult(
            calculation_version=CALCULATION_VERSION,
            patterns=(),
        )

    previous_body_high = max(previous.open, previous.close)
    previous_body_low = min(previous.open, previous.close)

    current_body_high = max(current.open, current.close)
    current_body_low = min(current.open, current.close)

    
    # --------------------------------------------------
    # 1. BULLISH / BEARISH ENGULFING
    # --------------------------------------------------
    # Current real body must strictly engulf the previous
    # real body. At least one boundary must extend.

    if (
        previous.direction == "BEARISH"
        and current.direction == "BULLISH"
        and current_body_low <= previous_body_low
        and current_body_high >= previous_body_high
        and (
            current_body_low < previous_body_low
            or current_body_high > previous_body_high
        )
    ):
        patterns.append("BULLISH_ENGULFING")

    elif (
        previous.direction == "BULLISH"
        and current.direction == "BEARISH"
        and current_body_low <= previous_body_low
        and current_body_high >= previous_body_high
        and (
            current_body_low < previous_body_low
            or current_body_high > previous_body_high
        )
    ):
        patterns.append("BEARISH_ENGULFING")


    # --------------------------------------------------
    # 2. BULLISH / BEARISH HARAMI
    # --------------------------------------------------
    # Current real body must be strictly inside the
    # previous real body. At least one boundary must contract.

    current_body_inside_previous = (
        current_body_high <= previous_body_high
        and current_body_low >= previous_body_low
    )

    current_body_strictly_inside_previous = (
        current_body_high <= previous_body_high
        and current_body_low >= previous_body_low
        and (
            current_body_high < previous_body_high
            or current_body_low > previous_body_low
        )
    )

    current_is_doji = (
        current.total_range > ZERO
        and current.body_range_ratio <= config.doji_max_body_ratio
    )

    if (
        current_body_strictly_inside_previous
        and previous.direction == "BEARISH"
        and current.direction == "BULLISH"
        and not current_is_doji
    ):
        patterns.append("BULLISH_HARAMI")

    elif (
        current_body_strictly_inside_previous
        and previous.direction == "BULLISH"
        and current.direction == "BEARISH"
        and not current_is_doji
    ):
        patterns.append("BEARISH_HARAMI")


    
    # --------------------------------------------------
    # 3. BULLISH / BEARISH HARAMI CROSS
    # --------------------------------------------------
    # A Doji real body must be contained within the
    # previous candle's real body.

    if (
        current_body_inside_previous
        and current_is_doji
        and previous.direction == "BEARISH"
    ):
        patterns.append("BULLISH_HARAMI_CROSS")

    elif (
        current_body_inside_previous
        and current_is_doji
        and previous.direction == "BULLISH"
    ):
        patterns.append("BEARISH_HARAMI_CROSS")

    # --------------------------------------------------
    # 4. PIERCING LINE
    # --------------------------------------------------
    # Previous candle bearish.
    # Current candle bullish and closes into the previous body.

    previous_range = previous.total_range

    if (
        previous.direction == "BEARISH"
        and current.direction == "BULLISH"
        and previous.body_range_ratio
        >= config.reversal_min_body_range_ratio
        and previous_range > ZERO
    ):
        penetration = (
            current.close - previous.close
        ) / previous.body_size

        if (
            penetration >= config.piercing_min_penetration_ratio
            and current.open
            <= previous.low
            + previous_range * config.piercing_gap_tolerance_ratio
            and current.close < previous.open
        ):
            patterns.append("PIERCING_LINE")

    # --------------------------------------------------
    # 5. DARK CLOUD COVER
    # --------------------------------------------------
    # Previous candle bullish.
    # Current candle bearish and closes into previous body.

    if (
        previous.direction == "BULLISH"
        and current.direction == "BEARISH"
        and previous.body_range_ratio
        >= config.reversal_min_body_range_ratio
        and previous_range > ZERO
    ):
        penetration = (
            previous.close - current.close
        ) / previous.body_size

        if (
            penetration >= config.dark_cloud_min_penetration_ratio
            and current.open
            >= previous.high
            - previous_range * config.dark_cloud_gap_tolerance_ratio
            and current.close > previous.open
        ):
            patterns.append("DARK_CLOUD_COVER")

    # --------------------------------------------------
    # 6. TWEEZER BOTTOM
    # --------------------------------------------------
    # Consecutive candles with approximately equal lows.

    if (
        previous.direction == "BEARISH"
        and current.direction == "BULLISH"
        and previous.total_range > ZERO
        and abs(previous.low - current.low)
        <= previous.total_range * config.tweezer_tolerance_ratio
    ):
        patterns.append("TWEEZER_BOTTOM")

    # --------------------------------------------------
    # 7. TWEEZER TOP
    # --------------------------------------------------
    # Consecutive candles with approximately equal highs.

    if (
        previous.direction == "BULLISH"
        and current.direction == "BEARISH"
        and previous.total_range > ZERO
        and abs(previous.high - current.high)
        <= previous.total_range * config.tweezer_tolerance_ratio
    ):
        patterns.append("TWEEZER_TOP")

    
    # --------------------------------------------------
    # 8. BULLISH / BEARISH KICKER
    # --------------------------------------------------
    # Opposite-direction candles with a significant gap
    # between their real bodies.

    if previous.total_range > ZERO:

        minimum_gap = (
            previous.total_range * config.kicker_min_gap_ratio
        )

        # Bullish Kicker:
        # Previous bearish candle followed by a bullish candle.
        # Current body must gap completely above previous body.

        if (
            previous.direction == "BEARISH"
            and current.direction == "BULLISH"
            and current_body_low > previous_body_high
            and current_body_low - previous_body_high >= minimum_gap
        ):
            patterns.append("BULLISH_KICKER")

        # Bearish Kicker:
        # Previous bullish candle followed by a bearish candle.
        # Current body must gap completely below previous body.

        elif (
            previous.direction == "BULLISH"
            and current.direction == "BEARISH"
            and previous_body_low > current_body_high
            and previous_body_low - current_body_high >= minimum_gap
        ):
            patterns.append("BEARISH_KICKER")

    # --------------------------------------------------
    # 9. BULLISH / BEARISH MEETING LINES
    # --------------------------------------------------
    # Opposite-direction candles closing at approximately
    # the same price.

    if (
        previous.direction == "BEARISH"
        and current.direction == "BULLISH"
        and previous.total_range > ZERO
        and abs(current.close - previous.close)
        <= previous.total_range
        * config.meeting_lines_close_tolerance_ratio
    ):
        patterns.append("BULLISH_MEETING_LINES")

    elif (
        previous.direction == "BULLISH"
        and current.direction == "BEARISH"
        and previous.total_range > ZERO
        and abs(current.close - previous.close)
        <= previous.total_range
        * config.meeting_lines_close_tolerance_ratio
    ):
        patterns.append("BEARISH_MEETING_LINES")


    # --------------------------------------------------
    # 10. BULLISH / BEARISH SEPARATING LINES
    # --------------------------------------------------
    # Opposite-direction candles opening at approximately
    # the same price.

    if (
        previous.direction == "BEARISH"
        and current.direction == "BULLISH"
        and previous.total_range > ZERO
        and abs(current.open - previous.open)
        <= previous.total_range
        * config.separating_lines_open_tolerance_ratio
    ):
        patterns.append("BULLISH_SEPARATING_LINES")

    elif (
        previous.direction == "BULLISH"
        and current.direction == "BEARISH"
        and previous.total_range > ZERO
        and abs(current.open - previous.open)
        <= previous.total_range
        * config.separating_lines_open_tolerance_ratio
    ):
        patterns.append("BEARISH_SEPARATING_LINES")


        # --------------------------------------------------
    # 11. ON-NECK / IN-NECK / THRUSTING
    # --------------------------------------------------
    # Previous candle must be bearish with a sufficiently
    # large real body.
    # Current candle must be bullish and open below
    # the previous candle's low.

    if (
        previous.direction == "BEARISH"
        and current.direction == "BULLISH"
        and previous.total_range > ZERO
        and previous.body_range_ratio
        >= config.continuation_min_body_range_ratio
        and current.open < previous.low
    ):
        neck_tolerance = (
            previous.total_range
            * config.neck_close_tolerance_ratio
        )

        previous_body_midpoint = (
            previous.open + previous.close
        ) / Decimal("2")

        # On-Neck:
        # Current close is at or slightly above previous low.
        if (
            current.close >= previous.low
            and current.close <= previous.low + neck_tolerance
        ):
            patterns.append("ON_NECK")

        # In-Neck:
        # Current close is slightly above previous close.
        elif (
            current.close > previous.close
            and current.close <= previous.close + neck_tolerance
        ):
            patterns.append("IN_NECK")

        # Thrusting:
        # Current close is above the previous close,
        # beyond the In-Neck tolerance, but below midpoint.
        elif (
            current.close > previous.close + neck_tolerance
            and current.close < previous_body_midpoint
        ):
            patterns.append("THRUSTING")


    return TwoCandlePatternResult(
        calculation_version=CALCULATION_VERSION,
        patterns=tuple(patterns),
    )
