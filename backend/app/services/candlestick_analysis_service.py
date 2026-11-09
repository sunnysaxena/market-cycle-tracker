
"""Unified candlestick analysis orchestration service.

Coordinates the single-, two-, and multi-candle pattern engines.

This service performs pattern recognition only. It does not calculate
trend context, trading signals, or persist results.

Input candles must be completed OHLC records in chronological order
(oldest to newest).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.engines.candlestick_pattern_config import (
    CALCULATION_VERSION,
    DEFAULT_PATTERN_CONFIG,
    CandlestickPatternConfig,
)
from app.engines.candlestick_pattern_engine import (
    CandlestickPatternError,
    CandlestickPatternResult,
    TwoCandlePatternResult,
    analyze_candle,
    analyze_two_candle_patterns,
)
from app.engines.candlestick_multi_candle_engine import (
    DEFAULT_MULTI_CANDLE_CONFIG,
    MULTI_CANDLE_CALCULATION_VERSION,
    MultiCandlePatternConfig,
    MultiCandlePatternMatch,
    MultiCandlePatternResult,
    analyze_multi_candle_patterns,
)


@dataclass(frozen=True)
class IndexedSingleCandleResult:
    """Single-candle analysis associated with its input candle index."""

    candle_index: int
    result: CandlestickPatternResult


@dataclass(frozen=True)
class TwoCandlePatternMatch:
    """A two-candle pattern associated with its input candle indices."""

    pattern: str
    start_index: int
    end_index: int


@dataclass(frozen=True)
class CandlestickAnalysisResult:
    """Combined results from all candlestick pattern engines."""

    candle_count: int

    single_candle_calculation_version: str
    two_candle_calculation_version: str
    multi_candle_calculation_version: str

    single_candle_results: tuple[IndexedSingleCandleResult, ...]
    two_candle_matches: tuple[TwoCandlePatternMatch, ...]
    multi_candle_matches: tuple[MultiCandlePatternMatch, ...]


def analyze_candlestick_patterns(
    records: Sequence[Mapping],
    *,
    pattern_config: CandlestickPatternConfig = DEFAULT_PATTERN_CONFIG,
    multi_candle_config: MultiCandlePatternConfig = (
        DEFAULT_MULTI_CANDLE_CONFIG
    ),
) -> CandlestickAnalysisResult:
    """
    Run all applicable candlestick pattern engines over OHLC records.

    Args:
        records:
            Completed OHLC records ordered oldest to newest.

        pattern_config:
            Configuration shared by the single- and two-candle engines.

        multi_candle_config:
            Configuration for three-, four-, and five-candle patterns.

    Returns:
        CandlestickAnalysisResult containing indexed results.

    Raises:
        CandlestickPatternError:
            If the input sequence, configurations, or candle data
            are invalid.

    Notes:
        - One candle: single-candle analysis only.
        - Two candles: single- and two-candle analysis.
        - Three or more candles: all three engines.
        - Indices are zero-based positions in the supplied input.
        - The caller must supply completed candles only.
    """

    # -----------------------------------------------------
    # VALIDATE INPUT SEQUENCE
    # -----------------------------------------------------

    if (
        not isinstance(records, Sequence)
        or isinstance(records, (str, bytes, bytearray))
    ):
        raise CandlestickPatternError(
            "records must be a sequence of OHLC mappings."
        )

    if not records:
        raise CandlestickPatternError(
            "At least one candle is required."
        )

    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise CandlestickPatternError(
                f"Candle at index {index} must be a mapping."
            )

    # -----------------------------------------------------
    # VALIDATE CONFIGURATIONS
    # -----------------------------------------------------

    if not isinstance(pattern_config, CandlestickPatternConfig):
        raise CandlestickPatternError(
            "pattern_config must be a CandlestickPatternConfig."
        )

    if not isinstance(multi_candle_config, MultiCandlePatternConfig):
        raise CandlestickPatternError(
            "multi_candle_config must be a MultiCandlePatternConfig."
        )

    # -----------------------------------------------------
    # 1. SINGLE-CANDLE ANALYSIS
    # -----------------------------------------------------

    single_results = []

    for index, record in enumerate(records):
        result = analyze_candle(
            record,
            config=pattern_config,
        )

        single_results.append(
            IndexedSingleCandleResult(
                candle_index=index,
                result=result,
            )
        )

    # -----------------------------------------------------
    # 2. TWO-CANDLE ANALYSIS
    # -----------------------------------------------------

    two_candle_matches = []

    for current_index in range(1, len(records)):
        result: TwoCandlePatternResult = (
            analyze_two_candle_patterns(
                records[current_index - 1],
                records[current_index],
                config=pattern_config,
            )
        )

        for pattern in result.patterns:
            two_candle_matches.append(
                TwoCandlePatternMatch(
                    pattern=pattern,
                    start_index=current_index - 1,
                    end_index=current_index,
                )
            )

    # -----------------------------------------------------
    # 3. MULTI-CANDLE ANALYSIS
    # -----------------------------------------------------

    multi_candle_matches: tuple[MultiCandlePatternMatch, ...]

    if len(records) >= 3:
        multi_result: MultiCandlePatternResult = (
            analyze_multi_candle_patterns(
                records,
                config=multi_candle_config,
            )
        )

        multi_candle_matches = multi_result.matches

    else:
        # The multi-candle engine requires at least three records.
        # Return an empty result for shorter valid input sequences.
        multi_candle_matches = ()

    # -----------------------------------------------------
    # BUILD UNIFIED RESULT
    # -----------------------------------------------------

    return CandlestickAnalysisResult(
        candle_count=len(records),

        single_candle_calculation_version=CALCULATION_VERSION,
        two_candle_calculation_version=CALCULATION_VERSION,
        multi_candle_calculation_version=(
            MULTI_CANDLE_CALCULATION_VERSION
        ),

        single_candle_results=tuple(single_results),
        two_candle_matches=tuple(two_candle_matches),
        multi_candle_matches=multi_candle_matches,
    )
