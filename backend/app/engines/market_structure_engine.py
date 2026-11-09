"""Market Structure Engine V1.

Detects confirmed swing highs/lows, HH/HL/LH/LL structure,
support/resistance levels and close-based breakouts.

Pivot dates are kept separate from confirmation dates to prevent
look-ahead bias in historical analysis.

Daily calendar gaps are allowed. Ineligible candles and missing
aggregate periods break the analysis segment.
"""

from __future__ import annotations

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

DEFAULT_PIVOT_BARS = {
    "1D": (3, 3),
    "1W": (2, 2),
    "1M": (2, 2),
    "1Y": (1, 1),
}

DEFAULT_EQUAL_TOLERANCE_PCT = Decimal("0.001")

CALCULATION_VERSION = "market_structure_v1.0_confirmed_pivots"

ZERO = Decimal("0")
ONE = Decimal("1")


class MarketStructureCalculationError(ValueError):
    """Raised when market-structure input data is invalid."""


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
        raise MarketStructureCalculationError(
            f"Invalid {field_name}: {value!r}"
        ) from exc


def _as_decimal(value: Any, field_name: str) -> Decimal:

    if value is None:
        raise MarketStructureCalculationError(
            f"{field_name} cannot be NULL."
        )

    try:
        result = (
            value
            if isinstance(value, Decimal)
            else Decimal(str(value))
        )

    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MarketStructureCalculationError(
            f"Invalid {field_name}: {value!r}"
        ) from exc

    if not result.is_finite():
        raise MarketStructureCalculationError(
            f"{field_name} must be finite."
        )

    return result


def _next_period_start(value: date, timeframe: str) -> date:

    if timeframe == "1W":
        return value + timedelta(days=7)

    if timeframe == "1M":
        if value.month == 12:
            return date(value.year + 1, 1, 1)

        return date(value.year, value.month + 1, 1)

    if timeframe == "1Y":
        return date(value.year + 1, 1, 1)

    raise MarketStructureCalculationError(
        f"Unsupported aggregate timeframe: {timeframe}"
    )


def _is_eligible(row: Mapping[str, Any], timeframe: str) -> bool:

    status = str(row.get("source_status") or "").lower()

    if timeframe == "1D":
        return status == "accepted"

    alignment = str(
        row.get("boundary_alignment_status") or ""
    ).lower()

    return (
        status == "completed"
        and alignment == "aligned"
    )


def _normalize_candles(
    candles: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:

    normalized = []

    for source_row in candles:

        start = _as_date(
            source_row.get("period_start"),
            "period_start",
        )

        end = _as_date(
            source_row.get(
                "period_end",
                source_row.get("period_start"),
            ),
            "period_end",
        )

        if end < start:
            raise MarketStructureCalculationError(
                "period_end cannot precede period_start."
            )

        open_ = _as_decimal(source_row.get("open"), "open")
        high = _as_decimal(source_row.get("high"), "high")
        low = _as_decimal(source_row.get("low"), "low")
        close = _as_decimal(source_row.get("close"), "close")

        if high < max(open_, low, close):
            raise MarketStructureCalculationError(
                f"Invalid OHLC high at {start}."
            )

        if low > min(open_, high, close):
            raise MarketStructureCalculationError(
                f"Invalid OHLC low at {start}."
            )

        normalized.append({
            "period_start": start,
            "period_end": end,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "source_status": source_row.get("source_status"),
            "boundary_alignment_status": (
                source_row.get("boundary_alignment_status")
            ),
            "eligible": False,
        })

    normalized.sort(key=lambda row: row["period_start"])

    seen_dates = set()

    for row in normalized:

        period_start = row["period_start"]

        if period_start in seen_dates:
            raise MarketStructureCalculationError(
                f"Duplicate period_start: {period_start}"
            )

        seen_dates.add(period_start)

    return normalized


# ---------------------------------------------------------
# PIVOT CLASSIFICATION
# ---------------------------------------------------------

def _classify_swing_high(
    current: Decimal,
    previous: Decimal | None,
    tolerance: Decimal,
) -> str:

    if previous is None:
        return "SH"

    if current > previous * (ONE + tolerance):
        return "HH"

    if current < previous * (ONE - tolerance):
        return "LH"

    return "EQH"


def _classify_swing_low(
    current: Decimal,
    previous: Decimal | None,
    tolerance: Decimal,
) -> str:

    if previous is None:
        return "SL"

    if current > previous * (ONE + tolerance):
        return "HL"

    if current < previous * (ONE - tolerance):
        return "LL"

    return "EQL"


# ---------------------------------------------------------
# MARKET STRUCTURE CLASSIFICATION
# ---------------------------------------------------------

def _structure_state(
    last_high: dict[str, Any] | None,
    last_low: dict[str, Any] | None,
) -> str:

    if last_high is None or last_low is None:
        return "INSUFFICIENT_DATA"

    high_class = last_high["classification"]
    low_class = last_low["classification"]

    if high_class == "HH" and low_class == "HL":
        return "BULLISH"

    if high_class == "LH" and low_class == "LL":
        return "BEARISH"

    mature_highs = ("HH", "LH", "EQH")
    mature_lows = ("HL", "LL", "EQL")

    if (
        high_class in mature_highs
        and low_class in mature_lows
    ):
        return "MIXED_TRANSITION"

    return "INSUFFICIENT_DATA"


# ---------------------------------------------------------
# SEGMENT PROCESSING
# ---------------------------------------------------------

def _process_segment(
    segment: list[dict[str, Any]],
    *,
    instrument_code: str,
    timeframe: str,
    left_bars: int,
    right_bars: int,
    equal_tolerance_pct: Decimal,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:

    events: list[dict[str, Any]] = []

    events_by_confirmation: dict[int, list[dict[str, Any]]] = {}

    previous_high_price = None
    previous_low_price = None

    # -----------------------------------------------------
    # DETECT PIVOTS
    # -----------------------------------------------------

    for pivot_index in range(
        left_bars,
        len(segment) - right_bars,
    ):

        pivot = segment[pivot_index]

        left = segment[
            pivot_index - left_bars:pivot_index
        ]

        right = segment[
            pivot_index + 1:pivot_index + right_bars + 1
        ]

        confirmation_index = pivot_index + right_bars
        confirmation = segment[confirmation_index]

        # A tie with the left side is allowed, but the
        # pivot must be strictly more extreme than the
        # right side. This selects the rightmost plateau.
        is_swing_high = (
            pivot["high"] >= max(row["high"] for row in left)
            and pivot["high"] > max(row["high"] for row in right)
        )

        is_swing_low = (
            pivot["low"] <= min(row["low"] for row in left)
            and pivot["low"] < min(row["low"] for row in right)
        )

        confirmed_events = events_by_confirmation.setdefault(
            confirmation_index,
            [],
        )

        if is_swing_high:

            classification = _classify_swing_high(
                pivot["high"],
                previous_high_price,
                equal_tolerance_pct,
            )

            event = {
                "instrument_code": instrument_code,
                "timeframe": timeframe,
                "event_type": "SWING_HIGH",
                "pivot_date": pivot["period_start"],
                "pivot_period_end": pivot["period_end"],
                "confirmation_date": confirmation["period_end"],
                "confirmation_period_end": confirmation["period_end"],
                "pivot_price": pivot["high"],
                "classification": classification,
            }

            confirmed_events.append(event)
            events.append(event)

            previous_high_price = pivot["high"]

        if is_swing_low:

            classification = _classify_swing_low(
                pivot["low"],
                previous_low_price,
                equal_tolerance_pct,
            )

            event = {
                "instrument_code": instrument_code,
                "timeframe": timeframe,
                "event_type": "SWING_LOW",
                "pivot_date": pivot["period_start"],
                "pivot_period_end": pivot["period_end"],
                "confirmation_date": confirmation["period_end"],
                "confirmation_period_end": confirmation["period_end"],
                "pivot_price": pivot["low"],
                "classification": classification,
            }

            confirmed_events.append(event)
            events.append(event)

            previous_low_price = pivot["low"]

    # -----------------------------------------------------
    # BUILD CANDLE-BY-CANDLE SNAPSHOTS
    # -----------------------------------------------------

    snapshots: list[dict[str, Any]] = []

    last_high = None
    last_low = None
    previous_close = None

    for index, candle in enumerate(segment):

        newly_confirmed = events_by_confirmation.get(index, [])

        # First check breakouts against levels that were
        # already known before this candle was processed.
        bullish_breakout = False
        bearish_breakdown = False

        if previous_close is not None:

            if last_high is not None:

                bullish_breakout = (
                    previous_close <= last_high["pivot_price"]
                    and candle["close"] > last_high["pivot_price"]
                )

            if last_low is not None:

                bearish_breakdown = (
                    previous_close >= last_low["pivot_price"]
                    and candle["close"] < last_low["pivot_price"]
                )

        # Now register pivots confirmed on this candle.
        for event in newly_confirmed:

            if event["event_type"] == "SWING_HIGH":
                last_high = event

            elif event["event_type"] == "SWING_LOW":
                last_low = event

        # Breakouts are based on candle closes crossing
        # an already confirmed swing level.
        bullish_breakout = False
        bearish_breakdown = False

        if previous_close is not None:

            if last_high is not None:

                bullish_breakout = (
                    previous_close <= last_high["pivot_price"]
                    and candle["close"] > last_high["pivot_price"]
                )

            if last_low is not None:

                bearish_breakdown = (
                    previous_close >= last_low["pivot_price"]
                    and candle["close"] < last_low["pivot_price"]
                )

        if bullish_breakout and bearish_breakdown:
            breakout_status = "BOTH"

        elif bullish_breakout:
            breakout_status = "BULLISH_BREAKOUT"

        elif bearish_breakdown:
            breakout_status = "BEARISH_BREAKDOWN"

        else:
            breakout_status = "NONE"

        if last_high is None or last_low is None:
            range_position = "INSUFFICIENT_LEVELS"

        elif candle["close"] > last_high["pivot_price"]:
            range_position = "ABOVE_RESISTANCE"

        elif candle["close"] < last_low["pivot_price"]:
            range_position = "BELOW_SUPPORT"

        else:
            range_position = "WITHIN_SWING_RANGE"

        snapshot = {
            "instrument_code": instrument_code,
            "timeframe": timeframe,
            "period_start": candle["period_start"],
            "period_end": candle["period_end"],
            "source_close": candle["close"],

            "support_price": (
                last_low["pivot_price"]
                if last_low is not None else None
            ),
            "support_pivot_date": (
                last_low["pivot_date"]
                if last_low is not None else None
            ),
            "support_confirmation_date": (
                last_low["confirmation_date"]
                if last_low is not None else None
            ),
            "support_classification": (
                last_low["classification"]
                if last_low is not None else None
            ),

            "resistance_price": (
                last_high["pivot_price"]
                if last_high is not None else None
            ),
            "resistance_pivot_date": (
                last_high["pivot_date"]
                if last_high is not None else None
            ),
            "resistance_confirmation_date": (
                last_high["confirmation_date"]
                if last_high is not None else None
            ),
            "resistance_classification": (
                last_high["classification"]
                if last_high is not None else None
            ),

            "market_structure_state": _structure_state(
                last_high,
                last_low,
            ),

            "breakout_status": breakout_status,
            "range_position": range_position,
            "calculation_version": CALCULATION_VERSION,
        }

        snapshots.append(snapshot)

        previous_close = candle["close"]

    return events, snapshots


# ---------------------------------------------------------
# PUBLIC CALCULATION FUNCTION
# ---------------------------------------------------------

def calculate_market_structure(
    candles: Iterable[Mapping[str, Any]],
    *,
    instrument_code: str,
    timeframe: str,
    left_bars: int | None = None,
    right_bars: int | None = None,
    equal_tolerance_pct: Decimal = DEFAULT_EQUAL_TOLERANCE_PCT,
) -> dict[str, Any]:
    """
    Calculate confirmed market structure for one instrument/timeframe.

    Returns confirmed swing events and one snapshot for every
    eligible candle.

    Default pivot settings:
        1D: 3 left / 3 right
        1W: 2 left / 2 right
        1M: 2 left / 2 right
        1Y: 1 left / 1 right
    """

    code = str(instrument_code).upper()

    if code not in PRICE_INDEX_CODES:
        raise MarketStructureCalculationError(
            f"Unsupported price index: {code}"
        )

    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise MarketStructureCalculationError(
            f"Unsupported timeframe: {timeframe}"
        )

    default_left, default_right = DEFAULT_PIVOT_BARS[timeframe]

    left = default_left if left_bars is None else left_bars
    right = default_right if right_bars is None else right_bars

    if (
        isinstance(left, bool)
        or not isinstance(left, int)
        or left < 1
    ):
        raise MarketStructureCalculationError(
            "left_bars must be a positive integer."
        )

    if (
        isinstance(right, bool)
        or not isinstance(right, int)
        or right < 1
    ):
        raise MarketStructureCalculationError(
            "right_bars must be a positive integer."
        )

    tolerance = _as_decimal(
        equal_tolerance_pct,
        "equal_tolerance_pct",
    )

    if tolerance < ZERO or tolerance >= ONE:
        raise MarketStructureCalculationError(
            "equal_tolerance_pct must be >= 0 and < 1."
        )

    normalized = _normalize_candles(candles)

    if not normalized:
        raise MarketStructureCalculationError(
            "No source candles provided."
        )

    for row in normalized:
        row["eligible"] = _is_eligible(row, timeframe)

    # -----------------------------------------------------
    # SPLIT INTO UNINTERRUPTED ELIGIBLE SEGMENTS
    # -----------------------------------------------------

    segments: list[list[dict[str, Any]]] = []
    current_segment: list[dict[str, Any]] = []

    for row in normalized:

        if not row["eligible"]:

            if current_segment:
                segments.append(current_segment)
                current_segment = []

            continue

        if (
            timeframe != "1D"
            and current_segment
        ):

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

    eligible_count = sum(len(segment) for segment in segments)

    if eligible_count == 0:
        raise MarketStructureCalculationError(
            "No eligible source candles found."
        )

    # -----------------------------------------------------
    # PROCESS ALL SEGMENTS
    # -----------------------------------------------------

    all_events: list[dict[str, Any]] = []
    all_snapshots: list[dict[str, Any]] = []

    for segment in segments:

        events, snapshots = _process_segment(
            segment,
            instrument_code=code,
            timeframe=timeframe,
            left_bars=left,
            right_bars=right,
            equal_tolerance_pct=tolerance,
        )

        all_events.extend(events)
        all_snapshots.extend(snapshots)

    return {
        "instrument_code": code,
        "timeframe": timeframe,
        "calculation_version": CALCULATION_VERSION,
        "left_bars": left,
        "right_bars": right,
        "equal_tolerance_pct": tolerance,
        "source_rows": len(normalized),
        "eligible_rows": eligible_count,
        "excluded_rows": len(normalized) - eligible_count,
        "segment_count": len(segments),
        "event_count": len(all_events),
        "snapshot_count": len(all_snapshots),
        "events": all_events,
        "snapshots": all_snapshots,
    }
