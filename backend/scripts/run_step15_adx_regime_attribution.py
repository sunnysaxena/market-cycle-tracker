from __future__ import annotations

import csv
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

# Make the backend package importable whether this script is launched from
# the backend directory or by its absolute path.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.engines.backtest_config import BacktestConfig
from app.engines.backtest_engine import BacktestEngine
from app.engines.market_regime_attribution import MarketRegimeAttribution
from app.engines.performance_analyzer import PerformanceAnalyzer
from app.services.backtest_data_loader import load_daily_backtest_data
from app.strategies.ema_crossover import EmaCrossoverStrategy
from app.strategies.entry_filter import LongEntryFilterStrategy


IMPORT_BATCH_ID = 5
INSTRUMENTS = ("NIFTY50", "SENSEX")

PERIODS = (
    ("2012_2019", date(2012, 1, 1), date(2019, 12, 31)),
    ("2020_2026", date(2020, 1, 1), date(2026, 10, 30)),
)

EXPERIMENTS = (
    ("BASELINE", None),
    ("ADX_GE_20", "20"),
    ("ADX_GE_25", "25"),
)

SLIPPAGE_BPS = "5"
WARMUP_BARS = 1
QUANTITY = "1"

SUMMARY_FIELDS = (
    "instrument",
    "period",
    "experiment",
    "start_date",
    "end_date",
    "candles",
    "evaluated_candles",
    "skipped_indicator_candles",
    "trades",
    "win_rate_percent",
    "profit_factor",
    "expectancy_points",
    "closed_pnl_points",
    "max_drawdown_points",
    "drawdown_recovered",
    "blocked_entries",
    "attributed_trades",
    "unattributed_trades",
    "open_position_present",
    "unexecuted_final_signal_present",
)

REGIME_FIELDS = (
    "instrument",
    "period",
    "experiment",
    "regime",
    "trades",
    "winning_trades",
    "losing_trades",
    "breakeven_trades",
    "win_rate_percent",
    "gross_profit_points",
    "gross_loss_points",
    "profit_factor",
    "net_points",
    "average_net_points",
    "average_winner_points",
    "average_loser_points",
    "expectancy_points",
)


def _csv_value(value: Any) -> str | int | float | bool:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _display(value: Any, places: int = 2) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, Decimal):
        return f"{value:.{places}f}"
    return str(value)


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _make_strategy(threshold: str | None):
    base = EmaCrossoverStrategy(
        fast_period=9,
        slow_period=20,
        trade_mode="LONG_ONLY",
    )

    if threshold is None:
        return base

    return LongEntryFilterStrategy(
        base,
        block_adx_at_or_above=threshold,
    )


def main() -> None:
    # Import the database session only when execution starts. This keeps the
    # runner module importable for configuration checks without opening a DB.
    from app.core.database import SessionLocal

    summary_rows: list[dict[str, Any]] = []
    regime_rows: list[dict[str, Any]] = []

    print("\n===== STEP 15 + MARKET REGIME ATTRIBUTION =====")
    print(f"Import batch: {IMPORT_BATCH_ID}")
    print("Strategy: EMA 9/20 LONG_ONLY")
    print("Experiments: BASELINE, BLOCK_ADX_GE_20, BLOCK_ADX_GE_25")
    print(f"Slippage: {SLIPPAGE_BPS} bps")
    print("Execution: NEXT_BAR_OPEN")
    print(f"Warm-up: {WARMUP_BARS} candle")
    print("ADX filter meaning: reject new LONG entries when ADX >= threshold")
    print("Attribution: signal-candle market-cycle classification")

    for instrument in INSTRUMENTS:
        with SessionLocal() as session:
            # Load the complete available history once. Do not date-filter this
            # list: the preceding candle is needed for warm-up and attribution.
            records = load_daily_backtest_data(
                session,
                import_batch_id=IMPORT_BATCH_ID,
                instrument_code=instrument,
            )

        if len(records) < 2:
            raise RuntimeError(
                f"{instrument}: at least two daily records are required "
                "for the configured one-candle warm-up and attribution."
            )

        first_date = records[0]["candle_date"]
        second_date = records[1]["candle_date"]
        last_date = records[-1]["candle_date"]

        print(f"\n\n========== {instrument} ==========")
        print(f"Available data: {first_date} through {last_date} ({len(records)} candles)")

        for period_name, period_start, period_end in PERIODS:
            # Preserve the original Step 15 boundary logic. Ensuring the
            # active start is at least the second record leaves one prior
            # candle available for warm-up if the requested period predates
            # the beginning of the dataset.
            active_start = max(second_date, period_start)
            active_end = min(last_date, period_end)

            if active_start > active_end:
                raise RuntimeError(
                    f"{instrument} {period_name}: no available candles in "
                    f"requested window {period_start} through {period_end}."
                )

            config = BacktestConfig(
                import_batch_id=IMPORT_BATCH_ID,
                instrument_code=instrument,
                timeframe="1D",
                start_date=active_start,
                end_date=active_end,
                indicator_status_policy="ALL",
                execution_policy="NEXT_BAR_OPEN",
                slippage_bps=SLIPPAGE_BPS,
            )

            print(f"\n--- {period_name}: {active_start} through {active_end} ---")

            for experiment_name, threshold in EXPERIMENTS:
                strategy = _make_strategy(threshold)

                result = BacktestEngine(config).run(
                    records,
                    strategy,
                    quantity=QUANTITY,
                    warmup_bars=WARMUP_BARS,
                )
                performance = PerformanceAnalyzer.analyze(result)

                # Pass the exact same complete records sequence supplied to
                # BacktestEngine.run. This is required to identify the
                # signal candle immediately preceding each entry candle.
                attribution = MarketRegimeAttribution.analyze(
                    result,
                    records,
                )

                blocked_entries = (
                    strategy.filtered_entry_count
                    if isinstance(strategy, LongEntryFilterStrategy)
                    else 0
                )

                summary_row = {
                    "instrument": instrument,
                    "period": period_name,
                    "experiment": experiment_name,
                    "start_date": active_start,
                    "end_date": active_end,
                    "candles": result.total_candles,
                    "evaluated_candles": result.evaluated_candles,
                    "skipped_indicator_candles": result.skipped_indicator_candles,
                    "trades": performance.total_trades,
                    "win_rate_percent": performance.win_rate_percent,
                    "profit_factor": performance.profit_factor,
                    "expectancy_points": performance.expectancy_points,
                    "closed_pnl_points": performance.net_closed_points,
                    "max_drawdown_points": performance.max_drawdown_points,
                    "drawdown_recovered": performance.drawdown_recovered,
                    "blocked_entries": blocked_entries,
                    "attributed_trades": attribution.attributed_trade_count,
                    "unattributed_trades": attribution.unattributed_trade_count,
                    "open_position_present": attribution.open_position_present,
                    "unexecuted_final_signal_present": (
                        attribution.unexecuted_final_signal_present
                    ),
                }
                summary_rows.append(summary_row)

                for item in attribution.regime_performance:
                    regime_rows.append({
                        "instrument": instrument,
                        "period": period_name,
                        "experiment": experiment_name,
                        "regime": item.regime,
                        "trades": item.total_trades,
                        "winning_trades": item.winning_trades,
                        "losing_trades": item.losing_trades,
                        "breakeven_trades": item.breakeven_trades,
                        "win_rate_percent": item.win_rate_percent,
                        "gross_profit_points": item.gross_profit_points,
                        "gross_loss_points": item.gross_loss_points,
                        "profit_factor": item.profit_factor,
                        "net_points": item.net_points,
                        "average_net_points": item.average_net_points,
                        "average_winner_points": item.average_winner_points,
                        "average_loser_points": item.average_loser_points,
                        "expectancy_points": item.expectancy_points,
                    })

                print(
                    f"\n{experiment_name}: "
                    f"trades={performance.total_trades}, "
                    f"win_rate={_display(performance.win_rate_percent)}%, "
                    f"PF={_display(performance.profit_factor)}, "
                    f"expectancy={_display(performance.expectancy_points)}, "
                    f"closed_PnL={_display(performance.net_closed_points)}, "
                    f"max_DD={_display(performance.max_drawdown_points)}, "
                    f"recovered={performance.drawdown_recovered}, "
                    f"blocked_entries={blocked_entries}"
                )
                print(
                    "Attribution: "
                    f"attributed={attribution.attributed_trade_count}, "
                    f"unattributed={attribution.unattributed_trade_count}, "
                    f"open_position={attribution.open_position_present}, "
                    "unexecuted_final_signal="
                    f"{attribution.unexecuted_final_signal_present}"
                )
                print("  REGIME                         TRADES  WIN%       NET PTS       AVG PTS       PF")
                for item in attribution.regime_performance:
                    print(
                        f"  {item.regime:<30} "
                        f"{item.total_trades:>6}  "
                        f"{_display(item.win_rate_percent):>7}  "
                        f"{_display(item.net_points):>12}  "
                        f"{_display(item.average_net_points):>12}  "
                        f"{_display(item.profit_factor):>8}"
                    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = BACKEND_DIR / "data" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_path = output_dir / f"step15_adx_experiment_summary_{timestamp}.csv"
    regime_path = output_dir / f"step15_market_regime_attribution_{timestamp}.csv"

    _write_csv(summary_path, SUMMARY_FIELDS, summary_rows)
    _write_csv(regime_path, REGIME_FIELDS, regime_rows)

    print("\n===== STEP 15 + REGIME ATTRIBUTION COMPLETE =====")
    print(f"Experiment summary CSV: {summary_path}")
    print(f"Regime attribution CSV: {regime_path}")
    print(f"Experiment runs: {len(summary_rows)}")
    print(f"Regime rows: {len(regime_rows)}")
    print("No database writes were performed by this runner.")


if __name__ == "__main__":
    main()
