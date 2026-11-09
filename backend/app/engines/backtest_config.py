from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.engines.indicator_engine import PRICE_INDEX_CODES


SUPPORTED_BACKTEST_TIMEFRAMES = ("1D",)

INDICATOR_STATUS_POLICIES = (
    "ALL",
    "READY_ONLY",
)

EXECUTION_POLICIES = (
    "NEXT_BAR_OPEN",
)

MAX_SLIPPAGE_BPS = Decimal("10000")


class BacktestConfigurationError(ValueError):
    """Raised when backtesting configuration is invalid."""


def _to_decimal(value, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise BacktestConfigurationError(
            f"{field_name} must be a valid decimal number."
        ) from exc

    if not result.is_finite():
        raise BacktestConfigurationError(
            f"{field_name} must be finite."
        )

    return result


def _normalize_date(value, field_name: str) -> date | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    raise BacktestConfigurationError(
        f"{field_name} must be a date or None."
    )


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Immutable configuration for historical index backtesting."""

    import_batch_id: int
    instrument_code: str
    timeframe: str = "1D"
    start_date: date | None = None
    end_date: date | None = None
    indicator_status_policy: str = "ALL"
    execution_policy: str = "NEXT_BAR_OPEN"
    slippage_bps: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if (
            not isinstance(self.import_batch_id, int)
            or isinstance(self.import_batch_id, bool)
            or self.import_batch_id <= 0
        ):
            raise BacktestConfigurationError(
                "import_batch_id must be a positive integer."
            )

        if not isinstance(self.instrument_code, str):
            raise BacktestConfigurationError(
                "instrument_code must be a string."
            )

        instrument = self.instrument_code.strip().upper()

        if instrument not in PRICE_INDEX_CODES:
            allowed = ", ".join(sorted(PRICE_INDEX_CODES))
            raise BacktestConfigurationError(
                f"Unsupported instrument: {instrument!r}. "
                f"Supported instruments: {allowed}."
            )

        object.__setattr__(self, "instrument_code", instrument)

        if self.timeframe not in SUPPORTED_BACKTEST_TIMEFRAMES:
            allowed = ", ".join(SUPPORTED_BACKTEST_TIMEFRAMES)
            raise BacktestConfigurationError(
                f"Unsupported timeframe: {self.timeframe!r}. "
                f"Currently supported: {allowed}."
            )

        start = _normalize_date(self.start_date, "start_date")
        end = _normalize_date(self.end_date, "end_date")

        if start is not None and end is not None and start > end:
            raise BacktestConfigurationError(
                "start_date cannot be later than end_date."
            )

        object.__setattr__(self, "start_date", start)
        object.__setattr__(self, "end_date", end)

        if self.indicator_status_policy not in INDICATOR_STATUS_POLICIES:
            raise BacktestConfigurationError(
                "indicator_status_policy must be one of: "
                + ", ".join(INDICATOR_STATUS_POLICIES)
            )

        if self.execution_policy not in EXECUTION_POLICIES:
            raise BacktestConfigurationError(
                "execution_policy must be one of: "
                + ", ".join(EXECUTION_POLICIES)
            )

        slippage = _to_decimal(self.slippage_bps, "slippage_bps")

        if slippage < 0 or slippage > MAX_SLIPPAGE_BPS:
            raise BacktestConfigurationError(
                f"slippage_bps must be between 0 and "
                f"{MAX_SLIPPAGE_BPS}."
            )

        object.__setattr__(self, "slippage_bps", slippage)


__all__ = [
    "BacktestConfig",
    "BacktestConfigurationError",
    "SUPPORTED_BACKTEST_TIMEFRAMES",
    "INDICATOR_STATUS_POLICIES",
    "EXECUTION_POLICIES",
]
