from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from app.engines.backtest_strategy import (
    BacktestStrategy,
    PositionSide,
    SignalAction,
    StrategyContext,
    StrategyContractError,
    TradeSignal,
)


class LongEntryFilterStrategy(BacktestStrategy):
    """
    Wrap an existing strategy and filter only new LONG entry signals.

    Supported filters:
        1. Block entries when ADX >= block_adx_at_or_above.
        2. Block entries inside configured BBW percentile ranges.

    BBW ranges use a lower-inclusive, upper-exclusive boundary.

    Missing values for enabled filters block the entry.
    EXIT signals are always passed through unchanged.
    """

    def __init__(
        self,
        base_strategy: BacktestStrategy,
        *,
        block_adx_at_or_above: Decimal | int | float | str | None = None,
        blocked_bbw_percentile_ranges: Sequence[
            tuple[Decimal | int | float | str,
                  Decimal | int | float | str]
        ] = (),
    ) -> None:

        if not isinstance(base_strategy, BacktestStrategy):
            raise TypeError(
                "base_strategy must implement BacktestStrategy."
            )

        self.base_strategy = base_strategy

        if block_adx_at_or_above is None:
            self.block_adx_at_or_above = None
        else:
            try:
                threshold = Decimal(str(block_adx_at_or_above))
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise ValueError(
                    "block_adx_at_or_above must be a valid decimal."
                ) from exc

            if not threshold.is_finite() or threshold < 0:
                raise ValueError(
                    "ADX threshold must be finite and non-negative."
                )

            self.block_adx_at_or_above = threshold

        normalized_ranges = []

        for bounds in blocked_bbw_percentile_ranges:
            try:
                lower_raw, upper_raw = bounds
                lower = Decimal(str(lower_raw))
                upper = Decimal(str(upper_raw))
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise ValueError(
                    "Each BBW range must contain two valid decimals."
                ) from exc

            if not lower.is_finite() or not upper.is_finite():
                raise ValueError(
                    "BBW range boundaries must be finite."
                )

            if lower < 0 or upper > 100 or lower >= upper:
                raise ValueError(
                    "BBW ranges must satisfy 0 <= lower < upper <= 100."
                )

            normalized_ranges.append((lower, upper))

        self.blocked_bbw_percentile_ranges = tuple(normalized_ranges)

        self._filtered_entry_count = 0
        self._blocked_reason_counts: Counter[str] = Counter()

    @property
    def name(self) -> str:
        rules = []

        if self.block_adx_at_or_above is not None:
            rules.append(
                f"ADX >= {self.block_adx_at_or_above}"
            )

        for lower, upper in self.blocked_bbw_percentile_ranges:
            rules.append(f"BBW percentile [{lower}, {upper})")

        if not rules:
            return f"{self.base_strategy.name} [NO ENTRY FILTERS]"

        return (
            f"{self.base_strategy.name} "
            f"[LONG ENTRY FILTER: {'; '.join(rules)}]"
        )

    @property
    def filtered_entry_count(self) -> int:
        """Number of new LONG entry signals rejected by this wrapper."""
        return self._filtered_entry_count

    @property
    def blocked_reason_counts(self) -> dict[str, int]:
        """Return a copy of the counts for individual blocking reasons."""
        return dict(self._blocked_reason_counts)

    @staticmethod
    def _read_optional_decimal(
        record: Mapping[str, Any],
        field: str,
    ) -> Decimal | None:

        value = record.get(field)

        if value is None:
            return None

        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise StrategyContractError(
                f"Invalid value for {field}: {value!r}."
            ) from exc

        if not result.is_finite():
            raise StrategyContractError(
                f"Value for {field} must be finite."
            )

        return result

    def generate_signal(
        self,
        history: Sequence[Mapping[str, Any]],
        context: StrategyContext,
    ) -> TradeSignal | None:

        if not isinstance(context, StrategyContext):
            raise StrategyContractError(
                "context must be a StrategyContext."
            )

        # Always ask the original strategy first.
        signal = self.base_strategy.generate_signal(
            history,
            context,
        )

        if signal is None:
            return None

        if not isinstance(signal, TradeSignal):
            raise StrategyContractError(
                "Base strategy must return TradeSignal or None."
            )

        # Never filter exits, short entries, or signals while a
        # position is already open.
        if (
            signal.action is not SignalAction.ENTER
            or signal.side is not PositionSide.LONG
            or context.position is not None
        ):
            return signal

        if not history:
            raise StrategyContractError(
                "History is required to evaluate an entry filter."
            )

        # The latest completed candle is the signal candle.
        signal_candle = history[-1]

        if signal_candle.get("candle_date") != context.current_date:
            raise StrategyContractError(
                "Signal candle date must match the strategy context date."
            )

        blocked_reasons = []

        # ADX rule: block when ADX is greater than or equal
        # to the configured threshold.
        if self.block_adx_at_or_above is not None:
            adx = self._read_optional_decimal(
                signal_candle,
                "adx_14",
            )

            if adx is None:
                blocked_reasons.append("ADX_MISSING")

            elif adx >= self.block_adx_at_or_above:
                blocked_reasons.append("ADX_AT_OR_ABOVE_THRESHOLD")

        # BBW rule: lower boundary included, upper boundary excluded.
        if self.blocked_bbw_percentile_ranges:
            bbw_percentile = self._read_optional_decimal(
                signal_candle,
                "cycle_bandwidth_percentile",
            )

            if bbw_percentile is None:
                blocked_reasons.append("BBW_PERCENTILE_MISSING")

            else:
                for lower, upper in self.blocked_bbw_percentile_ranges:
                    if lower <= bbw_percentile < upper:
                        blocked_reasons.append(
                            f"BBW_PERCENTILE_IN_RANGE_{lower}_{upper}"
                        )

        if blocked_reasons:
            self._filtered_entry_count += 1

            for reason in blocked_reasons:
                self._blocked_reason_counts[reason] += 1

            return None

        return signal


__all__ = ["LongEntryFilterStrategy"]
