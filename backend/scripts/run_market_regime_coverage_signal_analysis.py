from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

# Supports execution from the project root or by absolute script path.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.engines.backtest_config import BacktestConfig
from app.engines.backtest_engine import BacktestEngine
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
EXPERIMENTS = (
    ("BASELINE", None),
    ("BLOCK_ADX_GE_20", "20"),
    ("BLOCK_ADX_GE_25", "25"),
)
MARKET_REGIMES = (
    "ACCUMULATION",
    "MARKUP",
    "DISTRIBUTION",
    "MARKDOWN",
    "SIDEWAYS_CONSOLIDATION",
    "TRANSITION_UNCERTAIN",
    "INSUFFICIENT_DATA",
)
UNCLASSIFIED = "UNCLASSIFIED"
UNKNOWN_CLASSIFICATION = "UNKNOWN_CLASSIFICATION"
SLIPPAGE_BPS = "5"
WARMUP_BARS = 1
QUANTITY = "1"

COVERAGE_FIELDS = (
    "instrument", "period", "start_date", "end_date", "regime",
    "daily_candles", "ema_9_20_current_available",
    "ema_9_20_previous_and_current_available", "adx_14_available",
    "indicator_status_ready", "percentage_of_period_candles",
)
SIGNAL_FIELDS = (
    "instrument", "period", "experiment", "regime",
    "entry_signal_attempts", "accepted_entries", "blocked_entries",
    "blocked_adx_threshold", "blocked_adx_missing",
    "accepted_percent_of_attempts",
)
EVENT_FIELDS = (
    "instrument", "period", "experiment", "signal_date", "regime",
    "decision", "block_reason", "adx_14", "ema_9_previous",
    "ema_20_previous", "ema_9_current", "ema_20_current",
)
SUMMARY_FIELDS = (
    "instrument", "period", "experiment", "start_date", "end_date",
    "candles", "evaluated_candles", "skipped_indicator_candles",
    "generated_entry_signals", "accepted_entries", "blocked_entries",
    "closed_trades", "open_position_present",
    "unexecuted_final_signal_present",
)


def _regime_for(record: dict[str, Any]) -> str:
    raw = record.get("cycle_classification")
    if not isinstance(raw, str) or not raw.strip():
        return UNCLASSIFIED
    value = raw.strip().upper()
    return value if value in MARKET_REGIMES else UNKNOWN_CLASSIFICATION


def _present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


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


class SignalTrackingStrategy(BacktestStrategy):
    """Observe actual strategy-generated LONG entries without changing execution."""

    def __init__(self, delegate: BacktestStrategy, experiment: str) -> None:
        self.delegate = delegate
        self.experiment = experiment
        self.attempts: Counter[str] = Counter()
        self.accepted: Counter[str] = Counter()
        self.blocked: Counter[str] = Counter()
        self.blocked_reasons: dict[str, Counter[str]] = defaultdict(Counter)
        self.events: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self.delegate.name

    def generate_signal(self, history, context: StrategyContext) -> TradeSignal | None:
        before_blocked = 0
        before_reasons: dict[str, int] = {}
        if isinstance(self.delegate, LongEntryFilterStrategy):
            before_blocked = self.delegate.filtered_entry_count
            before_reasons = self.delegate.blocked_reason_counts

        signal = self.delegate.generate_signal(history, context)

        if not history:
            return signal
        candle = history[-1]
        regime = _regime_for(dict(candle))
        blocked_delta = 0
        reason_delta: dict[str, int] = {}

        if isinstance(self.delegate, LongEntryFilterStrategy):
            blocked_delta = self.delegate.filtered_entry_count - before_blocked
            after_reasons = self.delegate.blocked_reason_counts
            reason_delta = {
                reason: count - before_reasons.get(reason, 0)
                for reason, count in after_reasons.items()
                if count - before_reasons.get(reason, 0) > 0
            }

        if blocked_delta:
            self.attempts[regime] += blocked_delta
            self.blocked[regime] += blocked_delta
            for reason, count in reason_delta.items():
                self.blocked_reasons[regime][reason] += count
            previous = history[-2] if len(history) >= 2 else {}
            self.events.append(self._event(candle, previous, regime, "BLOCKED", ";".join(sorted(reason_delta))))

        elif (
            signal is not None
            and signal.action is SignalAction.ENTER
            and signal.side is PositionSide.LONG
            and context.position is None
        ):
            self.attempts[regime] += 1
            self.accepted[regime] += 1
            previous = history[-2] if len(history) >= 2 else {}
            self.events.append(self._event(candle, previous, regime, "ACCEPTED", ""))

        return signal

    def _event(self, candle: Any, previous: Any, regime: str, decision: str, reason: str) -> dict[str, Any]:
        return {
            "signal_date": candle.get("candle_date"),
            "regime": regime,
            "decision": decision,
            "block_reason": reason,
            "adx_14": candle.get("adx_14"),
            "ema_9_previous": previous.get("ema_9"),
            "ema_20_previous": previous.get("ema_20"),
            "ema_9_current": candle.get("ema_9"),
            "ema_20_current": candle.get("ema_20"),
        }


def _make_delegate(threshold: str | None) -> BacktestStrategy:
    base = EmaCrossoverStrategy(fast_period=9, slow_period=20, trade_mode="LONG_ONLY")
    if threshold is None:
        return base
    return LongEntryFilterStrategy(base, block_adx_at_or_above=threshold)


def _coverage_rows(
    instrument: str,
    period_name: str,
    start: date,
    end: date,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    active = [r for r in records if start <= r["candle_date"] <= end]
    counts: Counter[str] = Counter()
    ema_current: Counter[str] = Counter()
    ema_pair: Counter[str] = Counter()
    adx_available: Counter[str] = Counter()
    indicator_ready: Counter[str] = Counter()

    previous_by_date = {
        records[i]["candle_date"]: records[i - 1]
        for i in range(1, len(records))
    }

    for record in active:
        regime = _regime_for(record)
        counts[regime] += 1
        if _present(record.get("ema_9")) and _present(record.get("ema_20")):
            ema_current[regime] += 1
        previous = previous_by_date.get(record["candle_date"])
        if (
            previous is not None
            and _present(previous.get("ema_9"))
            and _present(previous.get("ema_20"))
            and _present(record.get("ema_9"))
            and _present(record.get("ema_20"))
        ):
            ema_pair[regime] += 1
        if _present(record.get("adx_14")):
            adx_available[regime] += 1
        if str(record.get("indicator_calculation_status") or "").lower() == "ready":
            indicator_ready[regime] += 1

    regimes = (*MARKET_REGIMES, UNCLASSIFIED, UNKNOWN_CLASSIFICATION)
    total = len(active)
    rows = []
    for regime in regimes:
        count = counts[regime]
        rows.append({
            "instrument": instrument,
            "period": period_name,
            "start_date": start,
            "end_date": end,
            "regime": regime,
            "daily_candles": count,
            "ema_9_20_current_available": ema_current[regime],
            "ema_9_20_previous_and_current_available": ema_pair[regime],
            "adx_14_available": adx_available[regime],
            "indicator_status_ready": indicator_ready[regime],
            "percentage_of_period_candles": (count / total * 100) if total else 0,
        })
    return rows


def main() -> None:
    from app.core.database import SessionLocal

    coverage_rows: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    print("\n===== MARKET REGIME COVERAGE & SIGNAL DISTRIBUTION V1 =====")
    print(f"Import batch: {IMPORT_BATCH_ID}")
    print("Instruments: " + ", ".join(INSTRUMENTS))
    print("Strategy: EMA 9/20 LONG_ONLY | 5 bps | NEXT_BAR_OPEN | warm-up 1")
    print("ADX filters: reject new LONG entries when ADX >= 20 or >= 25; missing ADX blocks")
    print("Indicator status policy: ALL (matches Step 15)")
    print("Read-only analysis: no database writes")

    for instrument in INSTRUMENTS:
        with SessionLocal() as session:
            records = load_daily_backtest_data(
                session,
                import_batch_id=IMPORT_BATCH_ID,
                instrument_code=instrument,
            )

        if len(records) < 2:
            raise RuntimeError(f"{instrument}: at least two daily candles are required.")

        first_date, second_date, last_date = records[0]["candle_date"], records[1]["candle_date"], records[-1]["candle_date"]
        print(f"\n{instrument}: {first_date} to {last_date} | {len(records)} accepted daily candles")

        for period_name, requested_start, requested_end in PERIODS:
            active_start = max(second_date, requested_start)
            active_end = min(last_date, requested_end)
            if active_start > active_end:
                raise RuntimeError(f"{instrument} {period_name}: no data in requested range.")

            coverage_rows.extend(_coverage_rows(instrument, period_name, active_start, active_end, records))

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

            for experiment, threshold in EXPERIMENTS:
                tracker = SignalTrackingStrategy(_make_delegate(threshold), experiment)
                result = BacktestEngine(config).run(
                    records,
                    tracker,
                    quantity=QUANTITY,
                    warmup_bars=WARMUP_BARS,
                )

                for regime in (*MARKET_REGIMES, UNCLASSIFIED, UNKNOWN_CLASSIFICATION):
                    attempts = tracker.attempts[regime]
                    accepted = tracker.accepted[regime]
                    blocked = tracker.blocked[regime]
                    signal_rows.append({
                        "instrument": instrument,
                        "period": period_name,
                        "experiment": experiment,
                        "regime": regime,
                        "entry_signal_attempts": attempts,
                        "accepted_entries": accepted,
                        "blocked_entries": blocked,
                        "blocked_adx_threshold": tracker.blocked_reasons[regime]["ADX_AT_OR_ABOVE_THRESHOLD"],
                        "blocked_adx_missing": tracker.blocked_reasons[regime]["ADX_MISSING"],
                        "accepted_percent_of_attempts": (accepted / attempts * 100) if attempts else 0,
                    })

                for event in tracker.events:
                    event_rows.append({
                        "instrument": instrument,
                        "period": period_name,
                        "experiment": experiment,
                        **event,
                    })

                total_attempts = sum(tracker.attempts.values())
                total_accepted = sum(tracker.accepted.values())
                total_blocked = sum(tracker.blocked.values())
                summary_rows.append({
                    "instrument": instrument,
                    "period": period_name,
                    "experiment": experiment,
                    "start_date": active_start,
                    "end_date": active_end,
                    "candles": result.total_candles,
                    "evaluated_candles": result.evaluated_candles,
                    "skipped_indicator_candles": result.skipped_indicator_candles,
                    "generated_entry_signals": total_attempts,
                    "accepted_entries": total_accepted,
                    "blocked_entries": total_blocked,
                    "closed_trades": result.closed_trade_count,
                    "open_position_present": result.open_position is not None,
                    "unexecuted_final_signal_present": result.unexecuted_final_signal is not None,
                })

                print(
                    f"  {period_name} {experiment}: attempts={total_attempts}, "
                    f"accepted={total_accepted}, blocked={total_blocked}, "
                    f"closed_trades={result.closed_trade_count}"
                )

    output_dir = BACKEND_DIR / "data" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outputs = {
        "coverage": output_dir / f"market_regime_coverage_{timestamp}.csv",
        "signals": output_dir / f"market_regime_signal_distribution_{timestamp}.csv",
        "events": output_dir / f"market_regime_signal_events_{timestamp}.csv",
        "summary": output_dir / f"market_regime_signal_run_summary_{timestamp}.csv",
    }
    _write_csv(outputs["coverage"], COVERAGE_FIELDS, coverage_rows)
    _write_csv(outputs["signals"], SIGNAL_FIELDS, signal_rows)
    _write_csv(outputs["events"], EVENT_FIELDS, event_rows)
    _write_csv(outputs["summary"], SUMMARY_FIELDS, summary_rows)

    print("\n===== ANALYSIS COMPLETE =====")
    for label, path in outputs.items():
        print(f"{label.title()} CSV: {path}")
    print(f"Coverage rows: {len(coverage_rows)} | Signal rows: {len(signal_rows)} | Signal events: {len(event_rows)}")
    print("No database writes were performed.")


if __name__ == "__main__":
    main()
