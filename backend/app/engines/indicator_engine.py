
"""Full V1 technical indicator calculation engine.

Calculation conventions:
- EMA: SMA-seeded exponential moving average.
- RSI: Wilder smoothing, period 14.
- ADX, +DI, -DI: Wilder directional movement, period 14.
- MACD: EMA(12) - EMA(26), signal EMA(9).
- ATR: Wilder smoothing, period 14.
- Bollinger Bands: SMA(20) +/- 2 population standard deviations.
- SMA: 222 periods.
- CHOP: Choppiness Index, rolling 14 True Range values.
- Bollinger BandWidth: (Upper - Lower) / Middle * 100.

All calculations use Decimal arithmetic.
All output values are rounded to eight decimal places.
"""

from __future__ import annotations

from collections import deque
from datetime import date, datetime, timedelta, timezone
from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_HALF_UP,
    localcontext,
)
from typing import Any, Iterable, Mapping


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

EMA_PERIODS = (9, 20, 50, 100, 200)
SMA_PERIOD = 222

RSI_PERIOD = 14
ADX_PERIOD = 14
ATR_PERIOD = 14
CHOP_PERIOD = 14

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

BB_PERIOD = 20
BB_MULTIPLIER = Decimal("2")

SUPPORTED_TIMEFRAMES = ("1D", "1W", "1M", "1Y")

PRICE_INDEX_CODES = (
    "NIFTY50",
    "BANKNIFTY",
    "SENSEX",
    "FINNIFTY",
    "MIDCPNIFTY",
)

INDIA_VIX_CODE = "INDIA_VIX"

# CALCULATION_VERSION = "indicator_v1.1_wilder_sma_seeded"
CALCULATION_VERSION = "indicator_v1.2_chop_bbw"

PRICE_QUANTUM = Decimal("0.00000001")

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


class IndicatorCalculationError(ValueError):
    """Raised when indicator input data is invalid."""


# ---------------------------------------------------------
# VALIDATION AND CONVERSION
# ---------------------------------------------------------

def _as_date(value: Any, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise IndicatorCalculationError(
            f"Invalid {field_name}: {value!r}"
        ) from exc


def _as_decimal(value: Any, field_name: str) -> Decimal:
    if value is None:
        raise IndicatorCalculationError(
            f"{field_name} cannot be NULL."
        )

    try:
        result = (
            value
            if isinstance(value, Decimal)
            else Decimal(str(value))
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise IndicatorCalculationError(
            f"Invalid {field_name}: {value!r}"
        ) from exc

    if not result.is_finite():
        raise IndicatorCalculationError(
            f"{field_name} must be finite."
        )

    return result


def _quantize(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None

    return value.quantize(
        PRICE_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)

    return date(value.year, value.month + 1, 1)


def _next_period_start(
    value: date,
    timeframe: str,
) -> date | None:

    if timeframe == "1D":
        # Daily calendar gaps are not treated as missing sessions.
        # Weekends and exchange holidays are normal.
        return None

    if timeframe == "1W":
        return value + timedelta(days=7)

    if timeframe == "1M":
        return _next_month(value)

    if timeframe == "1Y":
        return date(value.year + 1, 1, 1)

    raise IndicatorCalculationError(
        f"Unsupported timeframe: {timeframe}"
    )


def _is_eligible(
    row: Mapping[str, Any],
    timeframe: str,
) -> bool:

    status = str(
        row.get("source_status") or ""
    ).lower()

    if timeframe == "1D":
        return status == "accepted"

    alignment = str(
        row.get("boundary_alignment_status") or ""
    ).lower()

    return (
        status == "completed"
        and alignment == "aligned"
    )


# ---------------------------------------------------------
# EMA HELPER
# ---------------------------------------------------------

def _ema_update(
    value: Decimal,
    period: int,
    seed_values: list[Decimal],
    previous: Decimal | None,
) -> tuple[Decimal | None, list[Decimal]]:

    if previous is None:

        seed_values.append(value)

        if len(seed_values) < period:
            return None, seed_values

        if len(seed_values) == period:
            initial_ema = (
                sum(seed_values, ZERO)
                / Decimal(period)
            )

            return initial_ema, seed_values

    alpha = Decimal("2") / Decimal(period + 1)

    current = (
        value * alpha
        + previous * (ONE - alpha)
    )

    return current, seed_values


# ---------------------------------------------------------
# INDICATOR STATE
# ---------------------------------------------------------

class _IndicatorState:
    """Maintains rolling indicator state for one uninterrupted series."""

    def __init__(self) -> None:

        self.count = 0

        # EMA state
        self.ema_seeds = {
            period: []
            for period in EMA_PERIODS
        }

        self.ema_values = {
            period: None
            for period in EMA_PERIODS
        }

        # SMA 222
        self.sma_window = deque()
        self.sma_total = ZERO

        # Bollinger Bands
        self.bb_window = deque()
        self.bb_total = ZERO

        # CHOP 14: (True Range, High, Low)
        self.chop_window = deque()

        # Previous candle
        self.previous_close = None
        self.previous_high = None
        self.previous_low = None

        # RSI
        self.rsi_gain_seed = []
        self.rsi_loss_seed = []

        self.rsi_avg_gain = None
        self.rsi_avg_loss = None

        # ATR
        self.atr_seed = []
        self.atr_value = None

        # Directional movement / ADX
        self.dm_tr_seed = []
        self.dm_plus_seed = []
        self.dm_minus_seed = []

        self.smoothed_tr = None
        self.smoothed_plus = None
        self.smoothed_minus = None

        self.adx_dx_seed = []
        self.adx_value = None

        # MACD signal
        self.macd_fast_seed = []
        self.macd_slow_seed = []

        self.macd_fast_value = None
        self.macd_slow_value = None

        self.macd_signal_seed = []
        self.macd_signal_value = None

    # -----------------------------------------------------
    # MAIN UPDATE
    # -----------------------------------------------------

    def update(
        self,
        open_: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
    ) -> dict[str, Decimal | None]:

        self.count += 1

        values: dict[str, Decimal | None] = {}

        # -------------------------------------------------
        # EMA 9 / 20 / 50 / 100 / 200
        # -------------------------------------------------

        for period in EMA_PERIODS:

            ema, seed = _ema_update(
                close,
                period,
                self.ema_seeds[period],
                self.ema_values[period],
            )

            self.ema_seeds[period] = seed
            self.ema_values[period] = ema

            values[f"ema_{period}"] = ema

        # -------------------------------------------------
        # SMA 222
        # -------------------------------------------------

        self.sma_window.append(close)
        self.sma_total += close

        if len(self.sma_window) > SMA_PERIOD:

            removed = self.sma_window.popleft()
            self.sma_total -= removed

        if len(self.sma_window) == SMA_PERIOD:

            values["sma_222"] = (
                self.sma_total / Decimal(SMA_PERIOD)
            )

        else:
            values["sma_222"] = None

        # -------------------------------------------------
        # RSI 14 - WILDER
        # -------------------------------------------------

        values["rsi_14"] = None

        if self.previous_close is not None:

            change = close - self.previous_close

            gain = max(change, ZERO)
            loss = max(-change, ZERO)

            if self.rsi_avg_gain is None:

                self.rsi_gain_seed.append(gain)
                self.rsi_loss_seed.append(loss)

                if len(self.rsi_gain_seed) == RSI_PERIOD:

                    self.rsi_avg_gain = (
                        sum(self.rsi_gain_seed, ZERO)
                        / Decimal(RSI_PERIOD)
                    )

                    self.rsi_avg_loss = (
                        sum(self.rsi_loss_seed, ZERO)
                        / Decimal(RSI_PERIOD)
                    )

            else:

                n = Decimal(RSI_PERIOD)

                self.rsi_avg_gain = (
                    self.rsi_avg_gain * Decimal(RSI_PERIOD - 1)
                    + gain
                ) / n

                self.rsi_avg_loss = (
                    self.rsi_avg_loss * Decimal(RSI_PERIOD - 1)
                    + loss
                ) / n

            if (
                self.rsi_avg_gain is not None
                and self.rsi_avg_loss is not None
            ):

                total = (
                    self.rsi_avg_gain
                    + self.rsi_avg_loss
                )

                if total == ZERO:
                    values["rsi_14"] = Decimal("50")

                else:
                    values["rsi_14"] = (
                        HUNDRED
                        * self.rsi_avg_gain
                        / total
                    )

        # -------------------------------------------------
        # ATR 14 - WILDER
        # -------------------------------------------------

        values["atr_14"] = None

        if self.previous_close is not None:

            true_range = max(
                high - low,
                abs(high - self.previous_close),
                abs(low - self.previous_close),
            )

            if self.atr_value is None:

                self.atr_seed.append(true_range)

                if len(self.atr_seed) == ATR_PERIOD:

                    self.atr_value = (
                        sum(self.atr_seed, ZERO)
                        / Decimal(ATR_PERIOD)
                    )

            else:

                self.atr_value = (
                    self.atr_value * Decimal(ATR_PERIOD - 1)
                    + true_range
                ) / Decimal(ATR_PERIOD)

            values["atr_14"] = self.atr_value


                # -------------------------------------------------
        # CHOPPINESS INDEX 14
        # -------------------------------------------------

        values["chop_14"] = None

        if self.previous_close is not None:

            self.chop_window.append(
                (true_range, high, low)
            )

            if len(self.chop_window) > CHOP_PERIOD:
                self.chop_window.popleft()

            if len(self.chop_window) == CHOP_PERIOD:

                sum_true_range = sum(
                    (item[0] for item in self.chop_window),
                    ZERO,
                )

                highest_high = max(
                    item[1] for item in self.chop_window
                )

                lowest_low = min(
                    item[2] for item in self.chop_window
                )

                price_range = highest_high - lowest_low

                if (
                    sum_true_range > ZERO
                    and price_range > ZERO
                ):

                    with localcontext() as context:
                        context.prec = 40

                        ratio = sum_true_range / price_range

                        values["chop_14"] = (
                            HUNDRED
                            * ratio.ln()
                            / Decimal(CHOP_PERIOD).ln()
                        )

        # -------------------------------------------------
        # ADX 14 / PLUS DI / MINUS DI
        # -------------------------------------------------

        values["adx_14"] = None
        values["plus_di_14"] = None
        values["minus_di_14"] = None

        if self.previous_close is not None:

            true_range = max(
                high - low,
                abs(high - self.previous_close),
                abs(low - self.previous_close),
            )

            upward_move = high - self.previous_high
            downward_move = self.previous_low - low

            plus_dm = (
                upward_move
                if upward_move > downward_move and upward_move > ZERO
                else ZERO
            )

            minus_dm = (
                downward_move
                if downward_move > upward_move and downward_move > ZERO
                else ZERO
            )

            if self.smoothed_tr is None:

                self.dm_tr_seed.append(true_range)
                self.dm_plus_seed.append(plus_dm)
                self.dm_minus_seed.append(minus_dm)

                if len(self.dm_tr_seed) == ADX_PERIOD:

                    self.smoothed_tr = sum(
                        self.dm_tr_seed, ZERO
                    )

                    self.smoothed_plus = sum(
                        self.dm_plus_seed, ZERO
                    )

                    self.smoothed_minus = sum(
                        self.dm_minus_seed, ZERO
                    )

            else:

                n = Decimal(ADX_PERIOD)

                self.smoothed_tr = (
                    self.smoothed_tr
                    - self.smoothed_tr / n
                    + true_range
                )

                self.smoothed_plus = (
                    self.smoothed_plus
                    - self.smoothed_plus / n
                    + plus_dm
                )

                self.smoothed_minus = (
                    self.smoothed_minus
                    - self.smoothed_minus / n
                    + minus_dm
                )

            if self.smoothed_tr is not None:

                if self.smoothed_tr == ZERO:

                    plus_di = ZERO
                    minus_di = ZERO

                else:

                    plus_di = (
                        HUNDRED
                        * self.smoothed_plus
                        / self.smoothed_tr
                    )

                    minus_di = (
                        HUNDRED
                        * self.smoothed_minus
                        / self.smoothed_tr
                    )

                values["plus_di_14"] = plus_di
                values["minus_di_14"] = minus_di

                di_total = plus_di + minus_di

                if di_total == ZERO:
                    dx = ZERO

                else:
                    dx = (
                        HUNDRED
                        * abs(plus_di - minus_di)
                        / di_total
                    )

                if self.adx_value is None:

                    self.adx_dx_seed.append(dx)

                    if len(self.adx_dx_seed) == ADX_PERIOD:

                        self.adx_value = (
                            sum(self.adx_dx_seed, ZERO)
                            / Decimal(ADX_PERIOD)
                        )

                else:

                    self.adx_value = (
                        self.adx_value * Decimal(ADX_PERIOD - 1)
                        + dx
                    ) / Decimal(ADX_PERIOD)

                values["adx_14"] = self.adx_value

        # -------------------------------------------------
        # MACD 12 / 26 / 9
        # -------------------------------------------------

        values["macd_line_12_26"] = None
        values["macd_signal_9"] = None
        values["macd_histogram"] = None

        self.macd_fast_value, self.macd_fast_seed = _ema_update(
            close,
            MACD_FAST,
            self.macd_fast_seed,
            self.macd_fast_value,
        )

        self.macd_slow_value, self.macd_slow_seed = _ema_update(
            close,
            MACD_SLOW,
            self.macd_slow_seed,
            self.macd_slow_value,
        )

        if (
            self.macd_fast_value is not None
            and self.macd_slow_value is not None
        ):

            macd_line = (
                self.macd_fast_value
                - self.macd_slow_value
            )

            values["macd_line_12_26"] = macd_line

            if self.macd_signal_value is None:

                self.macd_signal_seed.append(macd_line)

                if len(self.macd_signal_seed) == MACD_SIGNAL:

                    self.macd_signal_value = (
                        sum(self.macd_signal_seed, ZERO)
                        / Decimal(MACD_SIGNAL)
                    )

            else:

                alpha = Decimal("2") / Decimal(MACD_SIGNAL + 1)

                self.macd_signal_value = (
                    macd_line * alpha
                    + self.macd_signal_value * (ONE - alpha)
                )

            values["macd_signal_9"] = self.macd_signal_value

            if self.macd_signal_value is not None:

                values["macd_histogram"] = (
                    macd_line - self.macd_signal_value
                )

        
        # -------------------------------------------------
        # BOLLINGER BANDS 20 / 2
        # -------------------------------------------------

        values["bollinger_bandwidth_20_2"] = None

        self.bb_window.append(close)
        self.bb_total += close

        if len(self.bb_window) > BB_PERIOD:

            removed = self.bb_window.popleft()
            self.bb_total -= removed

        if len(self.bb_window) == BB_PERIOD:

            middle = (
                self.bb_total / Decimal(BB_PERIOD)
            )

            variance = sum(
                (
                    (item - middle) ** 2
                    for item in self.bb_window
                ),
                ZERO,
            ) / Decimal(BB_PERIOD)

            standard_deviation = variance.sqrt()

            values["bollinger_middle_20_2"] = middle

            values["bollinger_upper_20_2"] = (
                middle + BB_MULTIPLIER * standard_deviation
            )

            values["bollinger_lower_20_2"] = (
                middle - BB_MULTIPLIER * standard_deviation
            )

            # Bollinger BandWidth 20 / 2
            if middle != ZERO:

                values["bollinger_bandwidth_20_2"] = (
                    (
                        values["bollinger_upper_20_2"]
                        - values["bollinger_lower_20_2"]
                    )
                    / middle
                ) * HUNDRED

        else:

            values["bollinger_upper_20_2"] = None
            values["bollinger_middle_20_2"] = None
            values["bollinger_lower_20_2"] = None

        # Save the previous candle for the next update.
        self.previous_close = close
        self.previous_high = high
        self.previous_low = low

        return values

    @staticmethod
    def status(
        values: Mapping[str, Decimal | None],
    ) -> str:

        indicator_fields = (
            "ema_9",
            "ema_20",
            "ema_50",
            "ema_100",
            "ema_200",
            "sma_222",
            "rsi_14",
            "adx_14",
            "plus_di_14",
            "minus_di_14",
            "macd_line_12_26",
            "macd_signal_9",
            "macd_histogram",
            "atr_14",
            "bollinger_upper_20_2",
            "bollinger_middle_20_2",
            "bollinger_lower_20_2",
        )

        available = sum(
            values.get(field) is not None
            for field in indicator_fields
        )

        if available == 0:
            return "warming_up"

        if available == len(indicator_fields):
            return "ready"

        return "partial"


# ---------------------------------------------------------
# PUBLIC CALCULATION FUNCTION
# ---------------------------------------------------------

def calculate_indicator_series(
    candles: Iterable[Mapping[str, Any]],
    *,
    instrument_code: str,
    timeframe: str,
    import_batch_id: int,
    generated_at_utc: datetime | None = None,
    calculation_version: str = CALCULATION_VERSION,
) -> list[dict[str, Any]]:
    """Calculate all V1 indicators for one instrument/timeframe."""

    code = str(instrument_code).upper()

    if code == INDIA_VIX_CODE:

        raise IndicatorCalculationError(
            "INDIA_VIX is excluded from the standard indicator engine."
        )

    if code not in PRICE_INDEX_CODES:

        raise IndicatorCalculationError(
            f"Unsupported instrument: {instrument_code}"
        )

    if timeframe not in SUPPORTED_TIMEFRAMES:

        raise IndicatorCalculationError(
            f"Unsupported timeframe: {timeframe}"
        )

    if import_batch_id <= 0:

        raise IndicatorCalculationError(
            "import_batch_id must be positive."
        )

    normalized = []
    seen = set()

    for row in candles:

        period_start = _as_date(
            row.get("period_start"),
            "period_start",
        )

        period_end = _as_date(
            row.get("period_end", row.get("period_start")),
            "period_end",
        )

        if period_end < period_start:
            raise IndicatorCalculationError(
                f"period_end precedes period_start at {period_start}."
            )

        if period_start in seen:
            raise IndicatorCalculationError(
                f"Duplicate {timeframe} period: {period_start}."
            )

        seen.add(period_start)

        open_ = _as_decimal(row.get("open"), "open")
        high = _as_decimal(row.get("high"), "high")
        low = _as_decimal(row.get("low"), "low")
        close = _as_decimal(row.get("close"), "close")

        if high < low:
            raise IndicatorCalculationError(
                f"Invalid OHLC at {period_start}: high < low."
            )

        if high < max(open_, close) or low > min(open_, close):
            raise IndicatorCalculationError(
                f"Invalid OHLC bounds at {period_start}."
            )

        normalized.append(
            (
                period_start,
                period_end,
                open_,
                high,
                low,
                close,
                row,
            )
        )

    normalized.sort(key=lambda item: item[0])

    generated = generated_at_utc or datetime.now(timezone.utc)

    if generated.tzinfo is None:
        raise IndicatorCalculationError(
            "generated_at_utc must be timezone-aware."
        )

    source_table = (
        "daily_ohlcv"
        if timeframe == "1D"
        else "aggregated_ohlcv"
    )

    state = _IndicatorState()

    previous_eligible_start = None
    results = []

    with localcontext() as context:

        context.prec = 40

        for (
            period_start,
            period_end,
            open_,
            high,
            low,
            close,
            source_row,
        ) in normalized:

            if not _is_eligible(source_row, timeframe):

                state = _IndicatorState()
                previous_eligible_start = None

                continue

            if previous_eligible_start is not None:

                expected = _next_period_start(
                    previous_eligible_start,
                    timeframe,
                )

                if (
                    expected is not None
                    and period_start != expected
                ):
                    # Do not bridge missing aggregate periods.
                    state = _IndicatorState()

            values = state.update(
                open_,
                high,
                low,
                close,
            )

            result = {
                "import_batch_id": import_batch_id,
                "instrument_code": code,
                "timeframe": timeframe,
                "period_start": period_start,
                "period_end": period_end,
                "source_table": source_table,
                "source_status": str(
                    source_row.get("source_status")
                ),
                "boundary_alignment_status": (
                    source_row.get("boundary_alignment_status")
                    if timeframe != "1D"
                    else None
                ),
                "session_coverage_status": (
                    source_row.get("session_coverage_status")
                    if timeframe != "1D"
                    else None
                ),
                "source_open": _quantize(open_),
                "source_high": _quantize(high),
                "source_low": _quantize(low),
                "source_close": _quantize(close),
                "calculation_status": state.status(values),
                "calculation_version": calculation_version,
                "generated_at_utc": generated,
            }

            result.update(
                {
                    key: _quantize(value)
                    for key, value in values.items()
                }
            )

            results.append(result)

            previous_eligible_start = period_start

    return results
