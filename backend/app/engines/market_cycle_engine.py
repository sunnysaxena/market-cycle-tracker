"""Market Cycle Classification Engine V1.

Uses historical technical indicators and confirmed market structure.

Classifications:
    ACCUMULATION
    MARKUP
    DISTRIBUTION
    MARKDOWN
    SIDEWAYS_CONSOLIDATION
    TRANSITION_UNCERTAIN
    INSUFFICIENT_DATA

Accumulation/distribution are price-action heuristics, not measurements
of actual institutional orders or volume flow.

BandWidth percentiles are calculated causally using only the current
and preceding observations in the current uninterrupted segment.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

PRICE_INDEX_CODES = (
    "NIFTY50",
    "BANKNIFTY",
    "SENSEX",
    "FINNIFTY",
    "MIDCPNIFTY",
)

SUPPORTED_TIMEFRAMES = ("1D", "1W", "1M", "1Y")

# CALCULATION_VERSION = "market_cycle_v1.0_rules"
CALCULATION_VERSION = "market_cycle_v1.1_confirmed_context"

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


@dataclass(frozen=True)
class CycleConfig:
    """Configurable V1 market-cycle thresholds."""

    adx_strong: Decimal = Decimal("25")
    adx_weak: Decimal = Decimal("20")

    chop_sideways: Decimal = Decimal("61.8")
    chop_trending: Decimal = Decimal("38.2")
    chop_transition: Decimal = Decimal("50")

    bbw_low_percentile: Decimal = Decimal("25")
    bbw_high_percentile: Decimal = Decimal("75")
    bbw_accumulation_percentile: Decimal = Decimal("30")

    prior_trend_lookback: int = 20
    prior_context_min_samples: int = 10
    prior_trend_min_ratio: Decimal = Decimal("0.60")


DEFAULT_CONFIG = CycleConfig()

# Causal BandWidth history windows.
# Minimum observations include the current observation.
BBW_LOOKBACK = {
    "1D": 252,
    "1W": 104,
    "1M": 60,
    "1Y": 60,
}

BBW_MIN_SAMPLES = {
    "1D": 60,
    "1W": 26,
    "1M": 20,
    "1Y": 30,
}

STRUCTURE_STATES = (
    "BULLISH",
    "BEARISH",
    "MIXED_TRANSITION",
    "INSUFFICIENT_DATA",
)

BREAKOUT_STATES = (
    "NONE",
    "BULLISH_BREAKOUT",
    "BEARISH_BREAKDOWN",
    "BOTH",
)

CYCLE_CLASSES = (
    "ACCUMULATION",
    "MARKUP",
    "DISTRIBUTION",
    "MARKDOWN",
    "SIDEWAYS_CONSOLIDATION",
    "TRANSITION_UNCERTAIN",
    "INSUFFICIENT_DATA",
)


class MarketCycleCalculationError(ValueError):
    """Raised when market-cycle input data is invalid."""


# ---------------------------------------------------------
# VALIDATION
# ---------------------------------------------------------

def _as_date(value: Any, field_name: str) -> date:

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    try:
        return date.fromisoformat(str(value)[:10])

    except (TypeError, ValueError) as exc:
        raise MarketCycleCalculationError(
            f"Invalid {field_name}: {value!r}"
        ) from exc


def _as_decimal(
    value: Any,
    field_name: str,
    *,
    nullable: bool = False,
) -> Decimal | None:

    if value is None:

        if nullable:
            return None

        raise MarketCycleCalculationError(
            f"{field_name} cannot be NULL."
        )

    try:
        result = (
            value
            if isinstance(value, Decimal)
            else Decimal(str(value))
        )

    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MarketCycleCalculationError(
            f"Invalid {field_name}: {value!r}"
        ) from exc

    if not result.is_finite():
        raise MarketCycleCalculationError(
            f"{field_name} must be finite."
        )

    return result


def _normalize_rows(
    candles: Iterable[Mapping[str, Any]],
    timeframe: str,
) -> list[dict[str, Any]]:

    rows = []

    for source in candles:

        period_start = _as_date(
            source.get("period_start"),
            "period_start",
        )

        period_end = _as_date(
            source.get("period_end", period_start),
            "period_end",
        )

        if period_end < period_start:
            raise MarketCycleCalculationError(
                "period_end cannot precede period_start."
            )

        close = _as_decimal(
            source.get("source_close", source.get("close")),
            "source_close",
        )

        if close <= ZERO:
            raise MarketCycleCalculationError(
                f"source_close must be positive at {period_start}."
            )

        indicator_fields = (
            "ema_20",
            "ema_50",
            "ema_200",
            "rsi_14",
            "adx_14",
            "macd_histogram",
            "chop_14",
            "bollinger_bandwidth_20_2",
        )

        values = {}

        for field in indicator_fields:
            values[field] = _as_decimal(
                source.get(field),
                field,
                nullable=True,
            )

        # -------------------------------------------------
        # SOURCE QUALITY AND ELIGIBILITY
        # -------------------------------------------------

        source_status = str(
            source.get("source_status") or ""
        ).lower()

        alignment = str(
            source.get("boundary_alignment_status") or ""
        ).lower()

        # Allow standalone test inputs without source metadata.
        if not source_status:
            eligible = True

        elif timeframe == "1D":
            eligible = source_status == "accepted"

        else:
            eligible = (
                source_status == "completed"
                and alignment == "aligned"
            )

        # -------------------------------------------------
        # MARKET STRUCTURE
        # -------------------------------------------------

        structure = str(
            source.get("market_structure_state")
            or (
                "INSUFFICIENT_DATA"
                if not eligible
                else ""
            )
        ).upper()

        breakout = str(
            source.get("breakout_status") or "NONE"
        ).upper()

        if structure not in STRUCTURE_STATES:
            raise MarketCycleCalculationError(
                f"Invalid market_structure_state at {period_start}: "
                f"{structure!r}"
            )

        if breakout not in BREAKOUT_STATES:
            raise MarketCycleCalculationError(
                f"Invalid breakout_status at {period_start}: "
                f"{breakout!r}"
            )

        # -------------------------------------------------
        # INDICATOR VALIDATION
        # -------------------------------------------------

        if (
            values["rsi_14"] is not None
            and not ZERO <= values["rsi_14"] <= HUNDRED
        ):
            raise MarketCycleCalculationError(
                f"RSI outside 0-100 at {period_start}."
            )

        if (
            values["adx_14"] is not None
            and values["adx_14"] < ZERO
        ):
            raise MarketCycleCalculationError(
                f"ADX cannot be negative at {period_start}."
            )

        if (
            values["bollinger_bandwidth_20_2"] is not None
            and values["bollinger_bandwidth_20_2"] < ZERO
        ):
            raise MarketCycleCalculationError(
                f"BandWidth cannot be negative at {period_start}."
            )

        # -------------------------------------------------
        # NORMALIZED OUTPUT
        # -------------------------------------------------

        rows.append({
            "period_start": period_start,
            "period_end": period_end,
            "source_close": close,
            **values,
            "market_structure_state": structure,
            "breakout_status": breakout,
            "eligible": eligible,
        })

    # -----------------------------------------------------
    # CHRONOLOGICAL ORDER AND DUPLICATE VALIDATION
    # -----------------------------------------------------

    rows.sort(key=lambda row: row["period_start"])

    seen = set()

    for row in rows:

        if row["period_start"] in seen:
            raise MarketCycleCalculationError(
                f"Duplicate period_start: {row['period_start']}"
            )

        seen.add(row["period_start"])

    return rows


def _next_period_start(value: date, timeframe: str) -> date:

    if timeframe == "1W":
        return value + timedelta(days=7)

    if timeframe == "1M":

        if value.month == 12:
            return date(value.year + 1, 1, 1)

        return date(value.year, value.month + 1, 1)

    if timeframe == "1Y":
        return date(value.year + 1, 1, 1)

    raise MarketCycleCalculationError(
        f"Unsupported aggregate timeframe: {timeframe}"
    )


# ---------------------------------------------------------
# ROLLING BANDWIDTH PERCENTILE
# ---------------------------------------------------------

def _percentile_rank(
    values: list[Decimal],
    current: Decimal,
) -> Decimal:

    if not values:
        raise MarketCycleCalculationError(
            "Cannot calculate percentile without observations."
        )

    count = sum(value <= current for value in values)

    return (
        Decimal(count)
        / Decimal(len(values))
        * HUNDRED
    )


# ---------------------------------------------------------
# CLASSIFICATION
# ---------------------------------------------------------

def _classify_one(
    row: dict[str, Any],
    *,
    bbw_percentile: Decimal | None,
    recent_bullish_context: bool,
    recent_bearish_context: bool,
    previous_valid_row: dict[str, Any] | None,
    config: CycleConfig,
) -> dict[str, Any]:

    required_fields = (
        "ema_20",
        "ema_50",
        "ema_200",
        "rsi_14",
        "adx_14",
        "macd_histogram",
        "chop_14",
        "bollinger_bandwidth_20_2",
    )

    missing = [
        field
        for field in required_fields
        if row[field] is None
    ]

    if bbw_percentile is None:
        missing.append("bandwidth_percentile_history")

    if row["market_structure_state"] == "INSUFFICIENT_DATA":
        missing.append("confirmed_market_structure")

    if missing:

        return {
            "cycle_classification": "INSUFFICIENT_DATA",
            "rule_score": 0,
            "bandwidth_percentile": bbw_percentile,
            "classification_basis": "INSUFFICIENT_INPUT",
            "evidence": [],
            "missing_inputs": sorted(set(missing)),
        }

    close = row["source_close"]

    ema20 = row["ema_20"]
    ema50 = row["ema_50"]
    ema200 = row["ema_200"]

    rsi = row["rsi_14"]
    adx = row["adx_14"]
    macd = row["macd_histogram"]
    chop = row["chop_14"]

    structure = row["market_structure_state"]
    breakout = row["breakout_status"]

    previous_rsi = (
        previous_valid_row["rsi_14"]
        if previous_valid_row is not None else None
    )

    previous_macd = (
        previous_valid_row["macd_histogram"]
        if previous_valid_row is not None else None
    )

    previous_adx = (
        previous_valid_row["adx_14"]
        if previous_valid_row is not None else None
    )

    adx_weakening = (
        previous_adx is not None
        and adx < previous_adx
    )

    rsi_improving = (
        previous_rsi is not None
        and rsi > previous_rsi
    )

    rsi_weakening = (
        previous_rsi is not None
        and rsi < previous_rsi
    )

    macd_improving = (
        previous_macd is not None
        and macd > previous_macd
    )

    macd_weakening = (
        previous_macd is not None
        and macd < previous_macd
    )

    bullish_stack = (
        close > ema20 > ema50 > ema200
    )

    bearish_stack = (
        close < ema20 < ema50 < ema200
    )

    # -----------------------------------------------------
    # STRONG MARKUP
    # -----------------------------------------------------

    if (
        structure == "BULLISH"
        and bullish_stack
        and adx >= config.adx_strong
        and rsi >= Decimal("50")
        and macd > ZERO
    ):

        evidence = [
            "BULLISH_STRUCTURE",
            "BULLISH_EMA_ALIGNMENT",
            "STRONG_ADX",
            "RSI_BULLISH",
            "MACD_POSITIVE",
        ]

        if chop <= config.chop_trending:
            evidence.append("LOW_CHOP_TREND_EVIDENCE")

        return {
            "cycle_classification": "MARKUP",
            "rule_score": 100,
            "bandwidth_percentile": bbw_percentile,
            "classification_basis": "PRICE_TREND_RULES",
            "evidence": evidence,
            "missing_inputs": [],
        }

    # -----------------------------------------------------
    # STRONG MARKDOWN
    # -----------------------------------------------------

    if (
        structure == "BEARISH"
        and bearish_stack
        and adx >= config.adx_strong
        and rsi < Decimal("50")
        and macd < ZERO
    ):

        evidence = [
            "BEARISH_STRUCTURE",
            "BEARISH_EMA_ALIGNMENT",
            "STRONG_ADX",
            "RSI_BEARISH",
            "MACD_NEGATIVE",
        ]

        if chop <= config.chop_trending:
            evidence.append("LOW_CHOP_TREND_EVIDENCE")

        return {
            "cycle_classification": "MARKDOWN",
            "rule_score": 100,
            "bandwidth_percentile": bbw_percentile,
            "classification_basis": "PRICE_TREND_RULES",
            "evidence": evidence,
            "missing_inputs": [],
        }


    # -----------------------------------------------------
    # RANGE / TREND-COOLING CONFIRMATION
    # -----------------------------------------------------

    range_or_cooling_conditions = {
        "CHOP_ELEVATED": (
            chop >= config.chop_transition
        ),
        "BANDWIDTH_COMPRESSED": (
            bbw_percentile
            <= config.bbw_accumulation_percentile
        ),
        "ADX_WEAK_OR_DECLINING": (
            adx < config.adx_strong
            or adx_weakening
        ),
    }

    range_or_cooling_score = sum(
        range_or_cooling_conditions.values()
    )
    

    # -----------------------------------------------------
    # ACCUMULATION CANDIDATE
    # -----------------------------------------------------

    accumulation_conditions = {
        "LOW_VOLATILITY_COMPRESSION": (
            bbw_percentile
            <= config.bbw_accumulation_percentile
        ),
        "ELEVATED_CHOP": (
            chop >= config.chop_transition
        ),
        "MOMENTUM_IMPROVING": (
            rsi_improving or macd_improving
        ),
        "PRICE_OR_STRUCTURE_RECOVERY": (
            close > ema20 or structure == "BULLISH"
        ),
    }

    accumulation_score = sum(
        accumulation_conditions.values()
    )

    if (
        recent_bearish_context
        and structure != "BEARISH"
        and accumulation_score >= 3
        and range_or_cooling_score >= 2
    ):

        evidence = [
            key
            for key, matched in accumulation_conditions.items()
            if matched
        ]

        evidence.append("RECENT_BEARISH_CONTEXT")

        evidence.extend(
            key
            for key, matched in range_or_cooling_conditions.items()
            if matched
        )

        evidence.append("RANGE_OR_TREND_COOLING_CONFIRMED")

        return {
            "cycle_classification": "ACCUMULATION",
            "rule_score": int(
                accumulation_score / 4 * 100
            ),
            "bandwidth_percentile": bbw_percentile,
            "classification_basis": "PRICE_ACTION_HEURISTIC",
            "evidence": evidence,
            "missing_inputs": [],
        }

    # -----------------------------------------------------
    # DISTRIBUTION CANDIDATE
    # -----------------------------------------------------

    distribution_conditions = {
        "LOW_VOLATILITY_COMPRESSION": (
            bbw_percentile
            <= config.bbw_accumulation_percentile
        ),
        "ELEVATED_CHOP": (
            chop >= config.chop_transition
        ),
        "MOMENTUM_WEAKENING": (
            rsi_weakening or macd_weakening
        ),
        "PRICE_OR_STRUCTURE_DETERIORATION": (
            close < ema20 or structure == "BEARISH"
        ),
    }

    distribution_score = sum(
        distribution_conditions.values()
    )

    if (
        recent_bullish_context
        and structure != "BULLISH"
        and distribution_score >= 3
        and range_or_cooling_score >= 2
    ):

        evidence = [
            key
            for key, matched in distribution_conditions.items()
            if matched
        ]

        evidence.append("RECENT_BULLISH_CONTEXT")

        evidence.extend(
            key
            for key, matched in range_or_cooling_conditions.items()
            if matched
        )

        evidence.append("RANGE_OR_TREND_COOLING_CONFIRMED")

        return {
            "cycle_classification": "DISTRIBUTION",
            "rule_score": int(
                distribution_score / 4 * 100
            ),
            "bandwidth_percentile": bbw_percentile,
            "classification_basis": "PRICE_ACTION_HEURISTIC",
            "evidence": evidence,
            "missing_inputs": [],
        }

    # -----------------------------------------------------
    # SIDEWAYS / CONSOLIDATION
    # -----------------------------------------------------

    sideways_conditions = {
        "HIGH_CHOP": chop >= config.chop_sideways,
        "WEAK_ADX": adx < config.adx_weak,
        "LOW_BANDWIDTH": (
            bbw_percentile <= config.bbw_low_percentile
        ),
    }

    sideways_score = sum(
        sideways_conditions.values()
    )

    if (
        structure == "MIXED_TRANSITION"
        and sideways_score >= 2
        and breakout == "NONE"
    ):

        evidence = [
            key
            for key, matched in sideways_conditions.items()
            if matched
        ]

        return {
            "cycle_classification": "SIDEWAYS_CONSOLIDATION",
            "rule_score": int(
                sideways_score / 3 * 100
            ),
            "bandwidth_percentile": bbw_percentile,
            "classification_basis": "RANGE_AND_VOLATILITY_RULES",
            "evidence": evidence,
            "missing_inputs": [],
        }

    # -----------------------------------------------------
    # TRANSITION / UNCERTAIN
    # -----------------------------------------------------

    evidence = []

    if structure == "MIXED_TRANSITION":
        evidence.append("MIXED_MARKET_STRUCTURE")

    if adx < config.adx_strong:
        evidence.append("TREND_STRENGTH_NOT_CONFIRMED")

    if config.chop_trending < chop < config.chop_sideways:
        evidence.append("INTERMEDIATE_CHOP")

    if breakout != "NONE":
        evidence.append("BREAKOUT_OR_BREAKDOWN_PRESENT")

    if bullish_stack != bearish_stack:
        evidence.append("EMA_DIRECTIONAL_EVIDENCE")

    return {
        "cycle_classification": "TRANSITION_UNCERTAIN",
        "rule_score": min(
            100,
            len(evidence) * 20,
        ),
        "bandwidth_percentile": bbw_percentile,
        "classification_basis": "MIXED_OR_INCOMPLETE_RULES",
        "evidence": evidence,
        "missing_inputs": [],
    }


# ---------------------------------------------------------
# SEGMENT PROCESSING
# ---------------------------------------------------------

def _process_segment(
    rows: list[dict[str, Any]],
    *,
    timeframe: str,
    config: CycleConfig,
) -> list[dict[str, Any]]:

    history_limit = BBW_LOOKBACK[timeframe]
    minimum_samples = BBW_MIN_SAMPLES[timeframe]

    bandwidth_history: deque[Decimal] = deque(
        maxlen=history_limit
    )

    recent_bullish: deque[bool] = deque(
        maxlen=config.prior_trend_lookback
    )

    recent_bearish: deque[bool] = deque(
        maxlen=config.prior_trend_lookback
    )

    output = []
    previous_valid_row = None

    for row in rows:

        bandwidth = row["bollinger_bandwidth_20_2"]

        if bandwidth is not None:
            bandwidth_history.append(bandwidth)

        percentile = None

        if (
            bandwidth is not None
            and len(bandwidth_history) >= minimum_samples
        ):

            percentile = _percentile_rank(
                list(bandwidth_history),
                bandwidth,
            )

                # -------------------------------------------------
        # CONFIRMED PRIOR TREND CONTEXT
        # -------------------------------------------------

        context_samples = len(recent_bearish)

        bearish_context = False
        bullish_context = False

        if context_samples >= config.prior_context_min_samples:

            bearish_ratio = (
                Decimal(sum(recent_bearish))
                / Decimal(context_samples)
            )

            bullish_ratio = (
                Decimal(sum(recent_bullish))
                / Decimal(context_samples)
            )

            bearish_context = (
                bearish_ratio >= config.prior_trend_min_ratio
            )

            bullish_context = (
                bullish_ratio >= config.prior_trend_min_ratio
            )

        classification = _classify_one(
            row,
            bbw_percentile=percentile,
            recent_bullish_context=bullish_context,
            recent_bearish_context=bearish_context,
            previous_valid_row=previous_valid_row,
            config=config,
        )

        output_row = {
            "period_start": row["period_start"],
            "period_end": row["period_end"],
            "cycle_classification": (
                classification["cycle_classification"]
            ),
            "rule_score": classification["rule_score"],
            "bandwidth_percentile": percentile,
            "classification_basis": (
                classification["classification_basis"]
            ),
            "evidence": classification["evidence"],
            "missing_inputs": classification["missing_inputs"],
            "calculation_version": CALCULATION_VERSION,
        }

        output.append(output_row)

        # Maintain prior trend context only from rows with
        # enough information for a meaningful trend assessment.
        has_trend_inputs = all(
            row[field] is not None
            for field in (
                "ema_20",
                "ema_50",
                "ema_200",
                "rsi_14",
                "adx_14",
                "macd_histogram",
            )
        )

        if has_trend_inputs:

            bullish = (
                row["market_structure_state"] == "BULLISH"
                and row["source_close"]
                > row["ema_20"]
                > row["ema_50"]
                > row["ema_200"]
                and row["adx_14"] >= config.adx_strong
                and row["rsi_14"] >= Decimal("50")
                and row["macd_histogram"] > ZERO
            )

            bearish = (
                row["market_structure_state"] == "BEARISH"
                and row["source_close"]
                < row["ema_20"]
                < row["ema_50"]
                < row["ema_200"]
                and row["adx_14"] >= config.adx_strong
                and row["rsi_14"] < Decimal("50")
                and row["macd_histogram"] < ZERO
            )

            recent_bullish.append(bullish)
            recent_bearish.append(bearish)

            if (
                row["rsi_14"] is not None
                and row["macd_histogram"] is not None
            ):
                previous_valid_row = row

    return output


# ---------------------------------------------------------
# PUBLIC CALCULATION FUNCTION
# ---------------------------------------------------------

def calculate_market_cycles(
    candles: Iterable[Mapping[str, Any]],
    *,
    instrument_code: str,
    timeframe: str,
    config: CycleConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """
    Classify one historical instrument/timeframe sequence.

    Input rows combine technical-indicator values and corresponding
    market-structure snapshot fields.

    BandWidth percentile uses only current and prior observations.
    Aggregate missing periods reset percentile and trend context.

    Daily calendar gaps are allowed because exchange holidays and
    weekends do not necessarily represent missing trading sessions.
    """

    code = str(instrument_code).upper()

    if code not in PRICE_INDEX_CODES:
        raise MarketCycleCalculationError(
            f"Unsupported instrument: {code}"
        )

    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise MarketCycleCalculationError(
            f"Unsupported timeframe: {timeframe}"
        )

    if config.prior_trend_lookback < 1:
        raise MarketCycleCalculationError(
            "prior_trend_lookback must be positive."
        )

    if not (
        1 <= config.prior_context_min_samples
        <= config.prior_trend_lookback
    ):
        raise MarketCycleCalculationError(
            "prior_context_min_samples must be between 1 "
            "and prior_trend_lookback."
        )

    if not (
        ZERO < config.prior_trend_min_ratio <= ONE
    ):
        raise MarketCycleCalculationError(
            "prior_trend_min_ratio must be greater than 0 "
            "and at most 1."
        )

    if not (
        ZERO <= config.bbw_low_percentile
        <= config.bbw_high_percentile <= HUNDRED
    ):
        raise MarketCycleCalculationError(
            "Invalid BandWidth percentile thresholds."
        )

    rows = _normalize_rows(candles, timeframe)

    if not rows:
        raise MarketCycleCalculationError(
            "No candles provided."
        )

    segments: list[list[dict[str, Any]]] = []
    current_segment: list[dict[str, Any]] = []

    for row in rows:
        # Ineligible source candles break the analysis segment.
        if not row["eligible"]:

            if current_segment:
                segments.append(current_segment)
                current_segment = []

            continue

        # Missing weekly/monthly/yearly periods also break
        # the historical indicator context.
        if timeframe != "1D" and current_segment:

            expected = _next_period_start(
                current_segment[-1]["period_start"],
                timeframe,
            )

            if row["period_start"] != expected:
                segments.append(current_segment)
                current_segment = []

        current_segment.append(row)

    if current_segment:
        segments.append(current_segment)

    classifications = []

    for segment in segments:

        classifications.extend(
            _process_segment(
                segment,
                timeframe=timeframe,
                config=config,
            )
        )

    counts = {
        cycle: 0
        for cycle in CYCLE_CLASSES
    }

    for row in classifications:
        counts[row["cycle_classification"]] += 1

    return {
        "instrument_code": code,
        "timeframe": timeframe,
        "calculation_version": CALCULATION_VERSION,
        "source_rows": len(rows),
        "segment_count": len(segments),
        "classification_count": len(classifications),
        "classification_counts": counts,
        "classifications": classifications,
    }
