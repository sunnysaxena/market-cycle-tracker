from __future__ import annotations

import csv
import sys
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

# Supports execution from the project root or by absolute script path.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.engines.backtest_config import BacktestConfig
from app.engines.backtest_engine import BacktestEngine, BacktestTrade, OpenPositionMark
from app.engines.backtest_strategy import (
    BacktestStrategy,
    PositionSide,
    SignalAction,
    StrategyContext,
    TradeSignal,
)
from app.services.backtest_data_loader import load_daily_backtest_data
from app.strategies.ema_crossover import EmaCrossoverStrategy
from app.strategies.entry_filter import LongEntryFilterStrategy


IMPORT_BATCH_ID = 5
INSTRUMENTS = ("NIFTY50", "SENSEX")
PERIODS = (
    ("2012_2019", date(2012, 1, 1), date(2019, 12, 31)),
    ("2020_2026", date(2020, 1, 1), date(2026, 10, 30)),
)
FILTERS = (
    ("BLOCK_ADX_GE_20", "20"),
    ("BLOCK_ADX_GE_25", "25"),
)
SLIPPAGE_BPS = "5"
WARMUP_BARS = 1
QUANTITY = "1"

OUTCOME_FIELDS = (
    "instrument", "period", "filter_experiment", "signal_date", "signal_regime",
    "signal_adx_14", "block_reason", "hypothetical_entry_date", "baseline_match_status",
    "baseline_trade_outcome", "side", "quantity", "entry_date", "exit_date",
    "entry_reference_price", "entry_fill_price", "exit_reference_price", "exit_fill_price",
    "gross_points", "net_points", "unrealized_points", "entry_reason", "exit_reason",
    "holding_calendar_days",
)
SUMMARY_FIELDS = (
    "instrument", "period", "filter_experiment", "blocked_signals",
    "matched_closed_trades", "matched_open_positions", "unmatched_signals",
    "no_next_bar_in_period", "profitable_closed_trades", "losing_closed_trades",
    "breakeven_closed_trades", "closed_trade_net_points", "open_position_unrealized_points",
)


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fields})


def _regime(record: dict[str, Any]) -> str:
    value = record.get("cycle_classification")
    return value.strip().upper() if isinstance(value, str) and value.strip() else "UNCLASSIFIED"


class BlockedSignalTracker(BacktestStrategy):
    """Observe filtered LONG signals rejected by the existing ADX wrapper."""

    def __init__(self, delegate: LongEntryFilterStrategy) -> None:
        self.delegate = delegate
        self.blocked_events: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self.delegate.name

    def generate_signal(self, history, context: StrategyContext) -> TradeSignal | None:
        before = self.delegate.filtered_entry_count
        before_reasons = self.delegate.blocked_reason_counts
        signal = self.delegate.generate_signal(history, context)
        delta = self.delegate.filtered_entry_count - before
        if delta and history:
            candle = history[-1]
            after_reasons = self.delegate.blocked_reason_counts
            reasons = [
                reason
                for reason, count in after_reasons.items()
                if count - before_reasons.get(reason, 0) > 0
            ]
            self.blocked_events.append({
                "signal_date": candle.get("candle_date"),
                "signal_regime": _regime(dict(candle)),
                "signal_adx_14": candle.get("adx_14"),
                "block_reason": ";".join(sorted(reasons)),
            })
        return signal


def _make_config(instrument: str, start: date, end: date) -> BacktestConfig:
    return BacktestConfig(
        import_batch_id=IMPORT_BATCH_ID,
        instrument_code=instrument,
        timeframe="1D",
        start_date=start,
        end_date=end,
        indicator_status_policy="ALL",
        execution_policy="NEXT_BAR_OPEN",
        slippage_bps=SLIPPAGE_BPS,
    )


def _match_outcome(
    *,
    event: dict[str, Any],
    instrument: str,
    period_name: str,
    experiment: str,
    next_date_by_signal_date: dict[date, date],
    in_period_dates: set[date],
    trades_by_entry_date: dict[date, BacktestTrade],
    open_position: OpenPositionMark | None,
) -> dict[str, Any]:
    signal_date = event["signal_date"]
    next_date = next_date_by_signal_date.get(signal_date)
    row: dict[str, Any] = {
        "instrument": instrument,
        "period": period_name,
        "filter_experiment": experiment,
        **event,
        "hypothetical_entry_date": next_date,
        "baseline_match_status": "",
        "baseline_trade_outcome": "",
    }

    if next_date is None or next_date not in in_period_dates:
        row["baseline_match_status"] = "NO_NEXT_BAR_IN_PERIOD"
        return row

    trade = trades_by_entry_date.get(next_date)
    if trade is not None:
        net = trade.net_points
        outcome = "PROFIT" if net > 0 else "LOSS" if net < 0 else "BREAKEVEN"
        row.update({
            "baseline_match_status": "MATCHED_CLOSED_TRADE",
            "baseline_trade_outcome": outcome,
            "side": trade.side.value if hasattr(trade.side, "value") else str(trade.side),
            "quantity": trade.quantity,
            "entry_date": trade.entry_date,
            "exit_date": trade.exit_date,
            "entry_reference_price": trade.entry_reference_price,
            "entry_fill_price": trade.entry_fill_price,
            "exit_reference_price": trade.exit_reference_price,
            "exit_fill_price": trade.exit_fill_price,
            "gross_points": trade.gross_points,
            "net_points": trade.net_points,
            "entry_reason": trade.entry_reason,
            "exit_reason": trade.exit_reason,
            "holding_calendar_days": (trade.exit_date - trade.entry_date).days,
        })
        return row

    if open_position is not None and open_position.entry_date == next_date:
        row.update({
            "baseline_match_status": "MATCHED_OPEN_POSITION",
            "baseline_trade_outcome": "OPEN_UNREALIZED",
            "side": open_position.side.value if hasattr(open_position.side, "value") else str(open_position.side),
            "quantity": open_position.quantity,
            "entry_date": open_position.entry_date,
            "exit_date": "",
            "entry_reference_price": open_position.entry_reference_price,
            "entry_fill_price": open_position.entry_fill_price,
            "exit_reference_price": "",
            "exit_fill_price": open_position.estimated_exit_fill_price,
            "unrealized_points": open_position.unrealized_points,
            "entry_reason": open_position.entry_reason,
            "exit_reason": "OPEN_AT_PERIOD_END",
            "holding_calendar_days": (open_position.mark_date - open_position.entry_date).days,
        })
        return row

    row["baseline_match_status"] = "UNMATCHED_BASELINE_POSITION_STATE"
    row["baseline_trade_outcome"] = "NOT_ATTRIBUTABLE"
    return row


def main() -> None:
    from app.core.database import SessionLocal

    outcome_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    print("\n===== BLOCKED SIGNAL OUTCOME ANALYSIS V1 =====")
    print(f"Import batch: {IMPORT_BATCH_ID}")
    print("Instruments: " + ", ".join(INSTRUMENTS))
    print("Reference: unfiltered BASELINE EMA 9/20 LONG_ONLY trade sequence")
    print("Execution: NEXT_BAR_OPEN | slippage 5 bps | warm-up 1 | indicator policy ALL")
    print("Read-only analysis: no database writes")
    print("Note: matched outcomes are counterfactual baseline outcomes, not filtered-portfolio outcomes.")

    for instrument in INSTRUMENTS:
        with SessionLocal() as session:
            records = load_daily_backtest_data(
                session,
                import_batch_id=IMPORT_BATCH_ID,
                instrument_code=instrument,
            )
        if len(records) < 2:
            raise RuntimeError(f"{instrument}: at least two daily candles are required.")

        dates = [record["candle_date"] for record in records]
        next_date_by_signal_date = {dates[index]: dates[index + 1] for index in range(len(dates) - 1)}

        for period_name, requested_start, requested_end in PERIODS:
            active_start = max(dates[1], requested_start)
            active_end = min(dates[-1], requested_end)
            if active_start > active_end:
                raise RuntimeError(f"{instrument} {period_name}: no data in requested range.")

            config = _make_config(instrument, active_start, active_end)
            in_period_dates = {d for d in dates if active_start <= d <= active_end}

            baseline = BacktestEngine(config).run(
                records,
                EmaCrossoverStrategy(fast_period=9, slow_period=20, trade_mode="LONG_ONLY"),
                quantity=QUANTITY,
                warmup_bars=WARMUP_BARS,
            )
            trades_by_entry_date = {trade.entry_date: trade for trade in baseline.trades}

            print(f"\n{instrument} {period_name}: baseline closed={len(baseline.trades)}, open={baseline.open_position is not None}")

            for experiment, threshold in FILTERS:
                delegate = LongEntryFilterStrategy(
                    EmaCrossoverStrategy(fast_period=9, slow_period=20, trade_mode="LONG_ONLY"),
                    block_adx_at_or_above=threshold,
                )
                tracker = BlockedSignalTracker(delegate)
                BacktestEngine(config).run(
                    records,
                    tracker,
                    quantity=QUANTITY,
                    warmup_bars=WARMUP_BARS,
                )

                matched_closed = matched_open = unmatched = no_next = 0
                winners = losers = breakeven = 0
                closed_net = Decimal("0")
                open_unrealized = Decimal("0")

                for event in tracker.blocked_events:
                    row = _match_outcome(
                        event=event,
                        instrument=instrument,
                        period_name=period_name,
                        experiment=experiment,
                        next_date_by_signal_date=next_date_by_signal_date,
                        in_period_dates=in_period_dates,
                        trades_by_entry_date=trades_by_entry_date,
                        open_position=baseline.open_position,
                    )
                    outcome_rows.append(row)
                    status = row["baseline_match_status"]
                    if status == "MATCHED_CLOSED_TRADE":
                        matched_closed += 1
                        closed_net += Decimal(str(row["net_points"]))
                        if row["baseline_trade_outcome"] == "PROFIT":
                            winners += 1
                        elif row["baseline_trade_outcome"] == "LOSS":
                            losers += 1
                        else:
                            breakeven += 1
                    elif status == "MATCHED_OPEN_POSITION":
                        matched_open += 1
                        open_unrealized += Decimal(str(row["unrealized_points"]))
                    elif status == "NO_NEXT_BAR_IN_PERIOD":
                        no_next += 1
                    else:
                        unmatched += 1

                summary_rows.append({
                    "instrument": instrument,
                    "period": period_name,
                    "filter_experiment": experiment,
                    "blocked_signals": len(tracker.blocked_events),
                    "matched_closed_trades": matched_closed,
                    "matched_open_positions": matched_open,
                    "unmatched_signals": unmatched,
                    "no_next_bar_in_period": no_next,
                    "profitable_closed_trades": winners,
                    "losing_closed_trades": losers,
                    "breakeven_closed_trades": breakeven,
                    "closed_trade_net_points": closed_net,
                    "open_position_unrealized_points": open_unrealized,
                })
                print(
                    f"  {experiment}: blocked={len(tracker.blocked_events)}, "
                    f"matched_closed={matched_closed}, matched_open={matched_open}, "
                    f"unmatched={unmatched}, no_next_bar={no_next}, "
                    f"baseline_matched_net={closed_net}"
                )

    output_dir = BACKEND_DIR / "data" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outcomes_path = output_dir / f"blocked_signal_outcomes_{timestamp}.csv"
    summary_path = output_dir / f"blocked_signal_outcome_summary_{timestamp}.csv"
    _write_csv(outcomes_path, OUTCOME_FIELDS, outcome_rows)
    _write_csv(summary_path, SUMMARY_FIELDS, summary_rows)

    print("\n===== ANALYSIS COMPLETE =====")
    print(f"Outcome CSV: {outcomes_path}")
    print(f"Summary CSV: {summary_path}")
    print(f"Outcome rows: {len(outcome_rows)} | Summary rows: {len(summary_rows)}")
    print("No database writes were performed.")


if __name__ == "__main__":
    main()
