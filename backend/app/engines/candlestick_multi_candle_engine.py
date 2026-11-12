from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from app.engines.candlestick_pattern_engine import (
    CandlestickPatternError,
    calculate_candle_geometry,
)


ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class MultiCandlePatternConfig:
    """Configurable thresholds for multi-candle pattern recognition."""

    long_body_min_range_ratio: Decimal = Decimal("0.50")
    small_body_max_range_ratio: Decimal = Decimal("0.30")
    doji_max_body_ratio: Decimal = Decimal("0.10")

    soldier_min_body_range_ratio: Decimal = Decimal("0.50")
    soldier_max_wick_body_ratio: Decimal = Decimal("0.50")

    confirmation_min_body_range_ratio: Decimal = Decimal("0.30")
    tasuki_gap_min_range_ratio: Decimal = Decimal("0.02")

    methods_middle_max_body_to_first_body_ratio: Decimal = Decimal("0.40")

    def __post_init__(self) -> None:
        for name in (
            "long_body_min_range_ratio",
            "small_body_max_range_ratio",
            "doji_max_body_ratio",
            "soldier_min_body_range_ratio",
            "soldier_max_wick_body_ratio",
            "confirmation_min_body_range_ratio",
            "tasuki_gap_min_range_ratio",
            "methods_middle_max_body_to_first_body_ratio",
        ):
            value = getattr(self, name)

            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(
                    f"{name} must be a finite Decimal."
                )

            if not ZERO <= value <= ONE:
                raise ValueError(
                    f"{name} must be between 0 and 1."
                )
                # Ensure candle-size classifications do not conflict.
        if self.doji_max_body_ratio > self.small_body_max_range_ratio:
            raise ValueError(
                "doji_max_body_ratio must be less than or equal "
                "to small_body_max_range_ratio."
            )

        if (
            self.small_body_max_range_ratio
            >= self.long_body_min_range_ratio
        ):
            raise ValueError(
                "small_body_max_range_ratio must be less than "
                "long_body_min_range_ratio."
            )


DEFAULT_MULTI_CANDLE_CONFIG = MultiCandlePatternConfig()

MULTI_CANDLE_CALCULATION_VERSION = "candlestick_multi_patterns_v1.2"

@dataclass(frozen=True)
class MultiCandlePatternMatch:
    pattern: str
    candle_count: int
    start_index: int
    end_index: int


@dataclass(frozen=True)
class MultiCandlePatternResult:
    calculation_version: str
    patterns: tuple[str, ...]
    matches: tuple[MultiCandlePatternMatch, ...]


@dataclass(frozen=True)
class _Candle:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    body: Decimal
    upper_wick: Decimal
    lower_wick: Decimal
    total_range: Decimal
    body_ratio: Decimal

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def bearish(self) -> bool:
        return self.close < self.open

    @property
    def neutral(self) -> bool:
        return self.close == self.open

    @property
    def body_high(self) -> Decimal:
        return max(self.open, self.close)

    @property
    def body_low(self) -> Decimal:
        return min(self.open, self.close)

    @property
    def midpoint(self) -> Decimal:
        return (self.open + self.close) / Decimal("2")


def _convert_candle(record: Mapping) -> _Candle:
    geometry = calculate_candle_geometry(record)

    return _Candle(
        open=geometry.open,
        high=geometry.high,
        low=geometry.low,
        close=geometry.close,
        body=geometry.body_size,
        upper_wick=geometry.upper_wick,
        lower_wick=geometry.lower_wick,
        total_range=geometry.total_range,
        body_ratio=geometry.body_range_ratio,
    )


def _long_body(c: _Candle, config: MultiCandlePatternConfig) -> bool:
    return (
        c.total_range > ZERO
        and c.body_ratio >= config.long_body_min_range_ratio
    )


def _small_body(c: _Candle, config: MultiCandlePatternConfig) -> bool:
    return (
        c.total_range > ZERO
        and c.body_ratio > config.doji_max_body_ratio
        and c.body_ratio <= config.small_body_max_range_ratio
    )


def _doji(c: _Candle, config: MultiCandlePatternConfig) -> bool:
    return (
        c.total_range == ZERO
        or c.body_ratio <= config.doji_max_body_ratio
    )


def _add(
    matches: list[MultiCandlePatternMatch],
    name: str,
    count: int,
    end_index: int,
) -> None:
    matches.append(
        MultiCandlePatternMatch(
            pattern=name,
            candle_count=count,
            start_index=end_index - count + 1,
            end_index=end_index,
        )
    )


def _analyze_three(
    a: _Candle,
    b: _Candle,
    c: _Candle,
    index: int,
    config: MultiCandlePatternConfig,
    matches: list[MultiCandlePatternMatch],
) -> None:
    # --------------------------------------------------
    # MORNING STAR / EVENING STAR
    # --------------------------------------------------

    if (
        a.bearish
        and _long_body(a, config)
        and _small_body(b, config)
        and c.bullish
        and _long_body(c, config)
        and c.close > a.midpoint
    ):
        _add(matches, "MORNING_STAR", 3, index)

    if (
        a.bearish
        and _long_body(a, config)
        and _doji(b, config)
        and c.bullish
        and _long_body(c, config)
        and c.close > a.midpoint
    ):
        _add(matches, "MORNING_DOJI_STAR", 3, index)

    if (
        a.bullish
        and _long_body(a, config)
        and _small_body(b, config)
        and c.bearish
        and _long_body(c, config)
        and c.close < a.midpoint
    ):
        _add(matches, "EVENING_STAR", 3, index)

    if (
        a.bullish
        and _long_body(a, config)
        and _doji(b, config)
        and c.bearish
        and _long_body(c, config)
        and c.close < a.midpoint
    ):
        _add(matches, "EVENING_DOJI_STAR", 3, index)

    # --------------------------------------------------
    # THREE WHITE SOLDIERS / THREE BLACK CROWS
    # --------------------------------------------------

    # --------------------------------------------------
    # THREE STARS IN THE SOUTH
    # --------------------------------------------------

    if (
        a.bearish
        and b.bearish
        and c.bearish
        and _long_body(a, config)
        and a.lower_wick >= a.body * Decimal("0.20")
        and a.upper_wick <= a.body * Decimal("0.20")
        and b.body < a.body
        and b.low < a.low
        and b.high < a.high
        and b.open < a.close
        and b.lower_wick < a.lower_wick
        and b.upper_wick <= b.body * Decimal("0.20")
        and c.body < b.body
        and c.body_high <= b.body_high
        and c.body_low >= b.body_low
        and c.lower_wick <= b.lower_wick
        and c.upper_wick <= c.body * Decimal("0.20")
    ):
        _add(matches, "THREE_STARS_IN_THE_SOUTH", 3, index)

    soldier_body_min = config.soldier_min_body_range_ratio
    wick_limit = config.soldier_max_wick_body_ratio

    soldiers = (a, b, c)

    
    if all(x.bullish and x.total_range > ZERO for x in soldiers):
        if (
            all(x.body_ratio >= soldier_body_min for x in soldiers)
            and a.close < b.close < c.close
            and a.open < b.open < c.open
            and a.open < b.open < a.close
            and b.open < c.open < b.close
            and all(
                x.upper_wick <= x.body * wick_limit
                for x in soldiers
            )
        ):
            _add(matches, "THREE_WHITE_SOLDIERS", 3, index)

    if all(x.bearish and x.total_range > ZERO for x in soldiers):
        if (
            all(x.body_ratio >= soldier_body_min for x in soldiers)
            and a.close > b.close > c.close
            and a.open > b.open > c.open
            and a.close < b.open < a.open
            and b.close < c.open < b.open
            and all(
                x.lower_wick <= x.body * wick_limit
                for x in soldiers
            )
        ):
            _add(matches, "THREE_BLACK_CROWS", 3, index)


    # --------------------------------------------------
    # THREE INSIDE UP / DOWN
    # --------------------------------------------------

    if (
        a.bearish
        and _long_body(a, config)
        and b.bullish
        and b.body_high < a.body_high
        and b.body_low > a.body_low
        and c.bullish
        and c.close > a.open
        and c.body_ratio >= config.confirmation_min_body_range_ratio
    ):
        _add(matches, "THREE_INSIDE_UP", 3, index)

    if (
        a.bullish
        and _long_body(a, config)
        and b.bearish
        and b.body_high < a.body_high
        and b.body_low > a.body_low
        and c.bearish
        and c.close < a.open
        and c.body_ratio >= config.confirmation_min_body_range_ratio
    ):
        _add(matches, "THREE_INSIDE_DOWN", 3, index)

    # --------------------------------------------------
    # THREE OUTSIDE UP / DOWN
    # --------------------------------------------------

    bullish_engulfing = (
        a.bearish
        and b.bullish
        and b.body_high >= a.body_high
        and b.body_low <= a.body_low
        and (
            b.body_high > a.body_high
            or b.body_low < a.body_low
        )
    )

    bearish_engulfing = (
        a.bullish
        and b.bearish
        and b.body_high >= a.body_high
        and b.body_low <= a.body_low
        and (
            b.body_high > a.body_high
            or b.body_low < a.body_low
        )
    )

    if (
        bullish_engulfing
        and c.bullish
        and c.close > b.close
        and c.body_ratio >= config.confirmation_min_body_range_ratio
    ):
        _add(matches, "THREE_OUTSIDE_UP", 3, index)

    if (
        bearish_engulfing
        and c.bearish
        and c.close < b.close
        and c.body_ratio >= config.confirmation_min_body_range_ratio
    ):
        _add(matches, "THREE_OUTSIDE_DOWN", 3, index)

    # --------------------------------------------------
    # TASUKI GAP
    # --------------------------------------------------

    gap_min = max(a.total_range, b.total_range) * (
        config.tasuki_gap_min_range_ratio
    )

    if (
        a.bullish
        and b.bullish
        and b.low > a.high
        and b.low - a.high >= gap_min
        and c.bearish
        and c.open > b.body_low
        and c.open < b.body_high
        and c.close > a.high
        and c.close < b.low
    ):
        _add(matches, "UPSIDE_TASUKI_GAP", 3, index)

    if (
        a.bearish
        and b.bearish
        and b.high < a.low
        and a.low - b.high >= gap_min
        and c.bullish
        and c.open > b.body_low
        and c.open < b.body_high
        and c.close < a.low
        and c.close > b.high
    ):
        _add(matches, "DOWNSIDE_TASUKI_GAP", 3, index)

    # --------------------------------------------------
    # ABANDONED BABY
    # --------------------------------------------------

    if (
        a.bearish
        and _long_body(a, config)
        and _doji(b, config)
        and b.high < a.low
        and c.bullish
        and _long_body(c, config)
        and c.low > b.high
        and c.close > a.midpoint
    ):
        _add(matches, "BULLISH_ABANDONED_BABY", 3, index)

    if (
        a.bullish
        and _long_body(a, config)
        and _doji(b, config)
        and b.low > a.high
        and c.bearish
        and _long_body(c, config)
        and c.high < b.low
        and c.close < a.midpoint
    ):
        _add(matches, "BEARISH_ABANDONED_BABY", 3, index)



def _analyze_four(
    candles: Sequence[_Candle],
    index: int,
    config: MultiCandlePatternConfig,
    matches: list[MultiCandlePatternMatch],
) -> None:
    a, b, c, d = candles

    minimum_body_ratio = config.confirmation_min_body_range_ratio

    # Bearish Three Line Strike:
    # Three advancing bullish candles followed by a bearish
    # candle opening above the third close and closing below
    # the first candle's open.

    if (
        a.bullish
        and b.bullish
        and c.bullish
        and d.bearish
        and all(
            x.body_ratio >= minimum_body_ratio
            for x in (a, b, c, d)
        )
        and a.close < b.close < c.close
        and a.open < b.open < a.close
        and b.open < c.open < b.close
        and d.open > c.close
        and d.close < a.open
    ):
        _add(matches, "BEARISH_THREE_LINE_STRIKE", 4, index)

    # Bullish Three Line Strike:
    # Three declining bearish candles followed by a bullish
    # candle opening below the third close and closing above
    # the first candle's open.

    if (
        a.bearish
        and b.bearish
        and c.bearish
        and d.bullish
        and all(
            x.body_ratio >= minimum_body_ratio
            for x in (a, b, c, d)
        )
        and a.close > b.close > c.close
        and a.close < b.open < a.open
        and b.close < c.open < b.open
        and d.open < c.close
        and d.close > a.open
    ):
        _add(matches, "BULLISH_THREE_LINE_STRIKE", 4, index)


def _analyze_five(
    candles: Sequence[_Candle],
    index: int,
    config: MultiCandlePatternConfig,
    matches: list[MultiCandlePatternMatch],
) -> None:
    a, b, c, d, e = candles

    middle = (b, c, d)

    # All three countertrend candles must:
    # 1. Have a non-zero real body.
    # 2. Have a body no larger than the configured
    #    percentage of the first candle's body.
    # 3. Remain strictly inside the first candle's
    #    complete high-low range.

    maximum_middle_body = (
        a.body
        * config.methods_middle_max_body_to_first_body_ratio
    )

    middle_candles_valid = (
        a.body > ZERO
        and all(
            x.total_range > ZERO
            and x.body <= maximum_middle_body
            and x.high < a.high
            and x.low > a.low
            for x in middle
        )
    )

    # -----------------------------------------------
    # RISING THREE METHODS
    # -----------------------------------------------

    if (
        a.bullish
        and _long_body(a, config)
        and all(x.bearish for x in middle)
        and middle_candles_valid
        and e.bullish
        and _long_body(e, config)
        and e.close > a.close
    ):
        _add(
            matches,
            "RISING_THREE_METHODS",
            5,
            index,
        )

    # -----------------------------------------------
    # FALLING THREE METHODS
    # -----------------------------------------------

    if (
        a.bearish
        and _long_body(a, config)
        and all(x.bullish for x in middle)
        and middle_candles_valid
        and e.bearish
        and _long_body(e, config)
        and e.close < a.close
    ):
        _add(
            matches,
            "FALLING_THREE_METHODS",
            5,
            index,
        )



def analyze_multi_candle_patterns(
    records: Sequence[Mapping],
    config: MultiCandlePatternConfig = DEFAULT_MULTI_CANDLE_CONFIG,
) -> MultiCandlePatternResult:
    """
    Recognize multi-candle patterns in consecutive OHLC records.

    Input records must be ordered oldest to newest.

    The function evaluates every consecutive 3-, 4-, and 5-candle
    window. It does not determine whether a timeframe candle is
    complete; the calling service must supply completed candles only.

    This function identifies geometric patterns only. It does not
    generate trading signals or determine trend context.
    """

    if not isinstance(config, MultiCandlePatternConfig):
        raise CandlestickPatternError(
            "config must be a MultiCandlePatternConfig instance."
        )

    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        raise CandlestickPatternError(
            "records must be a sequence of OHLC mappings."
        )

    if len(records) < 3:
        raise CandlestickPatternError(
            "At least three candles are required."
        )

    candles = []

    for index, record in enumerate(records):
        try:
            candles.append(_convert_candle(record))
        except (TypeError, ValueError, KeyError) as exc:
            raise CandlestickPatternError(
                f"Invalid candle at index {index}: {exc}"
            ) from exc

    matches: list[MultiCandlePatternMatch] = []

    for end in range(2, len(candles)):
        _analyze_three(
            candles[end - 2],
            candles[end - 1],
            candles[end],
            end,
            config,
            matches,
        )

    for end in range(3, len(candles)):
        _analyze_four(
            candles[end - 3:end + 1],
            end,
            config,
            matches,
        )

    for end in range(4, len(candles)):
        _analyze_five(
            candles[end - 4:end + 1],
            end,
            config,
            matches,
        )

    return MultiCandlePatternResult(
        calculation_version=MULTI_CANDLE_CALCULATION_VERSION,
        patterns=tuple(match.pattern for match in matches),
        matches=tuple(matches),
    )
