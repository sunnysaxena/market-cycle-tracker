from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any


class StrategyContractError(ValueError):
    """Raised when a strategy returns an invalid signal."""


class SignalAction(str, Enum):
    ENTER = "ENTER"
    EXIT = "EXIT"


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


def _positive_decimal(
    value: Decimal | int | float | str | None,
    field_name: str,
) -> Decimal | None:
    if value is None:
        return None

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise StrategyContractError(
            f"{field_name} must be a valid decimal number."
        ) from exc

    if not result.is_finite() or result <= 0:
        raise StrategyContractError(
            f"{field_name} must be a finite positive number."
        )

    return result


@dataclass(frozen=True, slots=True)
class TradeSignal:
    """Standardized directional entry or exit signal."""

    action: SignalAction | str
    side: PositionSide | str
    reason: str
    stop_loss: Decimal | int | float | str | None = None
    take_profit: Decimal | int | float | str | None = None

    def __post_init__(self) -> None:
        try:
            action = SignalAction(self.action)
        except (ValueError, TypeError) as exc:
            raise StrategyContractError(
                f"Unsupported signal action: {self.action!r}."
            ) from exc

        try:
            side = PositionSide(self.side)
        except (ValueError, TypeError) as exc:
            raise StrategyContractError(
                f"Unsupported position side: {self.side!r}."
            ) from exc

        if not isinstance(self.reason, str) or not self.reason.strip():
            raise StrategyContractError(
                "Signal reason must be a non-empty string."
            )

        stop_loss = _positive_decimal(
            self.stop_loss,
            "stop_loss",
        )
        take_profit = _positive_decimal(
            self.take_profit,
            "take_profit",
        )

        if action is SignalAction.EXIT and (
            stop_loss is not None or take_profit is not None
        ):
            raise StrategyContractError(
                "EXIT signals cannot define new stop-loss "
                "or take-profit levels."
            )

        object.__setattr__(self, "action", action)
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "reason", self.reason.strip())
        object.__setattr__(self, "stop_loss", stop_loss)
        object.__setattr__(self, "take_profit", take_profit)


@dataclass(frozen=True, slots=True)
class OpenPositionContext:
    """Read-only view of the position currently held by the engine."""

    side: PositionSide
    entry_date: date
    entry_reference_price: Decimal
    entry_fill_price: Decimal
    quantity: Decimal
    stop_loss: Decimal | None
    take_profit: Decimal | None
    entry_reason: str


@dataclass(frozen=True, slots=True)
class StrategyContext:
    """
    Market and position state available when a strategy evaluates a bar.

    The context reflects execution and protective exits already processed
    for the current candle. It never contains future candle information.
    """

    current_date: date
    current_close: Decimal
    position: OpenPositionContext | None

    @property
    def has_open_position(self) -> bool:
        return self.position is not None


class BacktestStrategy(ABC):
    """
    Abstract interface for historical backtesting strategies.

    History is chronological and contains only eligible completed
    candles up to and including the current candle.

    Context provides the current simulated position, if any.

    Signals are evaluated after a candle closes and become eligible
    for execution no earlier than the next candle.

    Strategies must not execute orders or modify historical data.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return a stable, human-readable strategy name."""
        raise NotImplementedError

    @abstractmethod
    def generate_signal(
        self,
        history: Sequence[Mapping[str, Any]],
        context: StrategyContext,
    ) -> TradeSignal | None:
        """
        Evaluate market history and current position state.

        Return a TradeSignal when an action is required,
        otherwise return None.
        """
        raise NotImplementedError


__all__ = [
    "BacktestStrategy",
    "SignalAction",
    "PositionSide",
    "TradeSignal",
    "OpenPositionContext",
    "StrategyContext",
    "StrategyContractError",
]
