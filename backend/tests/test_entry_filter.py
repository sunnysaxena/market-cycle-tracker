from datetime import date
from decimal import Decimal

import pytest

from app.engines.backtest_strategy import (
    BacktestStrategy,
    OpenPositionContext,
    PositionSide,
    SignalAction,
    StrategyContext,
    StrategyContractError,
    TradeSignal,
)
from app.strategies.entry_filter import LongEntryFilterStrategy


TEST_DATE = date(2024, 1, 2)


class FixedSignalStrategy(BacktestStrategy):
    def __init__(self, signal):
        self.signal = signal

    @property
    def name(self):
        return "FIXED_TEST_STRATEGY"

    def generate_signal(self, history, context):
        return self.signal


def make_context(position=None):
    return StrategyContext(
        current_date=TEST_DATE,
        current_close=Decimal("100"),
        position=position,
    )


def make_history(adx="20", bbw="50"):
    candle = {
        "candle_date": TEST_DATE,
        "close": Decimal("100"),
    }

    if adx is not None:
        candle["adx_14"] = adx

    if bbw is not None:
        candle["cycle_bandwidth_percentile"] = bbw

    return [candle]


def long_entry():
    return TradeSignal(
        action=SignalAction.ENTER,
        side=PositionSide.LONG,
        reason="Test bullish entry",
    )


def short_entry():
    return TradeSignal(
        action=SignalAction.ENTER,
        side=PositionSide.SHORT,
        reason="Test bearish entry",
    )


def long_exit():
    return TradeSignal(
        action=SignalAction.EXIT,
        side=PositionSide.LONG,
        reason="Test long exit",
    )


def make_open_position():
    return OpenPositionContext(
        side=PositionSide.LONG,
        entry_date=date(2024, 1, 1),
        entry_reference_price=Decimal("98"),
        entry_fill_price=Decimal("98.10"),
        quantity=Decimal("1"),
        stop_loss=None,
        take_profit=None,
        entry_reason="Test position",
    )


def make_filter(
    signal,
    *,
    adx_threshold=None,
    bbw_ranges=(),
):
    return LongEntryFilterStrategy(
        FixedSignalStrategy(signal),
        block_adx_at_or_above=adx_threshold,
        blocked_bbw_percentile_ranges=bbw_ranges,
    )


def test_adx_below_threshold_allows_entry():
    strategy = make_filter(
        long_entry(),
        adx_threshold="25",
    )

    signal = strategy.generate_signal(
        make_history(adx="24.99"),
        make_context(),
    )

    assert signal is not None
    assert signal.side is PositionSide.LONG
    assert strategy.filtered_entry_count == 0


def test_adx_exactly_at_threshold_blocks_entry():
    strategy = make_filter(
        long_entry(),
        adx_threshold="25",
    )

    signal = strategy.generate_signal(
        make_history(adx="25"),
        make_context(),
    )

    assert signal is None
    assert strategy.filtered_entry_count == 1
    assert strategy.blocked_reason_counts == {
        "ADX_AT_OR_ABOVE_THRESHOLD": 1
    }


def test_bbw_lower_boundary_is_inclusive():
    strategy = make_filter(
        long_entry(),
        bbw_ranges=(("40", "60"),),
    )

    signal = strategy.generate_signal(
        make_history(bbw="40"),
        make_context(),
    )

    assert signal is None
    assert strategy.filtered_entry_count == 1


def test_bbw_upper_boundary_is_exclusive():
    strategy = make_filter(
        long_entry(),
        bbw_ranges=(("40", "60"),),
    )

    signal = strategy.generate_signal(
        make_history(bbw="60"),
        make_context(),
    )

    assert signal is not None
    assert strategy.filtered_entry_count == 0


def test_missing_adx_blocks_entry_when_enabled():
    strategy = make_filter(
        long_entry(),
        adx_threshold="25",
    )

    signal = strategy.generate_signal(
        make_history(adx=None),
        make_context(),
    )

    assert signal is None
    assert strategy.blocked_reason_counts == {
        "ADX_MISSING": 1
    }


def test_missing_bbw_blocks_entry_when_enabled():
    strategy = make_filter(
        long_entry(),
        bbw_ranges=(("40", "60"),),
    )

    signal = strategy.generate_signal(
        make_history(bbw=None),
        make_context(),
    )

    assert signal is None
    assert strategy.blocked_reason_counts == {
        "BBW_PERCENTILE_MISSING": 1
    }


def test_exit_signal_is_never_blocked_by_filters():
    original_signal = long_exit()

    strategy = make_filter(
        original_signal,
        adx_threshold="25",
        bbw_ranges=(("40", "60"),),
    )

    signal = strategy.generate_signal(
        make_history(adx=None, bbw=None),
        make_context(position=make_open_position()),
    )

    assert signal is original_signal
    assert signal.action is SignalAction.EXIT
    assert strategy.filtered_entry_count == 0


def test_short_entry_is_not_filtered():
    original_signal = short_entry()

    strategy = make_filter(
        original_signal,
        adx_threshold="25",
        bbw_ranges=(("40", "60"),),
    )

    signal = strategy.generate_signal(
        make_history(adx="30", bbw="50"),
        make_context(),
    )

    assert signal is original_signal
    assert strategy.filtered_entry_count == 0


def test_both_filters_record_both_blocking_reasons():
    strategy = make_filter(
        long_entry(),
        adx_threshold="25",
        bbw_ranges=(("40", "60"),),
    )

    signal = strategy.generate_signal(
        make_history(adx="30", bbw="50"),
        make_context(),
    )

    assert signal is None
    assert strategy.filtered_entry_count == 1
    assert strategy.blocked_reason_counts == {
        "ADX_AT_OR_ABOVE_THRESHOLD": 1,
        "BBW_PERCENTILE_IN_RANGE_40_60": 1,
    }


def test_invalid_adx_value_raises_contract_error():
    strategy = make_filter(
        long_entry(),
        adx_threshold="25",
    )

    with pytest.raises(StrategyContractError):
        strategy.generate_signal(
            make_history(adx="invalid"),
            make_context(),
        )


def test_invalid_bbw_value_raises_contract_error():
    strategy = make_filter(
        long_entry(),
        bbw_ranges=(("40", "60"),),
    )

    with pytest.raises(StrategyContractError):
        strategy.generate_signal(
            make_history(bbw="invalid"),
            make_context(),
        )


def test_no_enabled_filters_allows_entry_with_missing_values():
    strategy = make_filter(long_entry())

    signal = strategy.generate_signal(
        make_history(adx=None, bbw=None),
        make_context(),
    )

    assert signal is not None
    assert strategy.filtered_entry_count == 0


def test_invalid_bbw_range_is_rejected():
    with pytest.raises(ValueError):
        make_filter(
            long_entry(),
            bbw_ranges=(("60", "40"),),
        )


def test_bbw_outside_percentile_domain_is_rejected():
    with pytest.raises(ValueError):
        make_filter(
            long_entry(),
            bbw_ranges=(("-1", "20"),),
        )


def test_blocked_entry_counter_increments_for_each_rejection():
    strategy = make_filter(
        long_entry(),
        adx_threshold="25",
    )

    for _ in range(3):
        signal = strategy.generate_signal(
            make_history(adx="30"),
            make_context(),
        )
        assert signal is None

    assert strategy.filtered_entry_count == 3
    assert strategy.blocked_reason_counts == {
        "ADX_AT_OR_ABOVE_THRESHOLD": 3
    }


def test_strategy_name_identifies_active_filters():
    strategy = make_filter(
        long_entry(),
        adx_threshold="25",
        bbw_ranges=(("40", "60"),),
    )

    assert "ADX >= 25" in strategy.name
    assert "BBW percentile [40, 60)" in strategy.name
