
"""
ADX Filter Robustness & Final Comparison V1

Market Cycle Tracker
Purpose:
Consolidate existing ADX research CSV files into a final
read-only comparison report.

No backtests are executed.
No database connection is made.
No existing research files are modified.

Run from project root:

python .\backend\scripts\run_adx_filter_robustness_final_comparison.py
"""

import csv
from pathlib import Path
from datetime import datetime
from collections import defaultdict


# ============================================================
# 1. PROJECT PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

REPORT_DIR = PROJECT_ROOT / "backend" / "data" / "reports"

INPUT_FILES = {
    "backtest":
        "step15_adx_experiment_summary_20261102_162750.csv",

    "regime_attribution":
        "step15_market_regime_attribution_20261102_162750.csv",

    "regime_coverage":
        "market_regime_coverage_20261102_165154.csv",

    "signal_distribution":
        "market_regime_signal_distribution_20261102_165154.csv",

    "blocked_outcomes":
        "blocked_signal_outcomes_20261102_170302.csv",

    "blocked_summary":
        "blocked_signal_outcome_summary_20261102_170302.csv",
}

INSTRUMENTS = ["NIFTY50", "SENSEX"]

PERIODS = ["2012_2019", "2020_2026"]

EXPERIMENTS = [
    "BASELINE",
    "ADX_GE_20",
    "ADX_GE_25",
]


# ============================================================
# 2. GENERAL HELPERS
# ============================================================

def read_csv(filename):
    """Read an existing CSV without modifying it."""

    path = REPORT_DIR / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Required input file is missing: {path}"
        )

    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        rows = list(csv.DictReader(file))

    if not rows:
        raise ValueError(
            f"Input CSV contains no data: {path}"
        )

    return rows


def to_float(value, default=0.0):

    if value is None or str(value).strip() == "":
        return default

    return float(value)


def to_int(value, default=0):

    if value is None or str(value).strip() == "":
        return default

    return int(float(value))


def to_bool(value):

    return str(value).strip().lower() in (
        "true", "1", "yes"
    )


def write_csv(filename, rows):

    if not rows:
        print(f"WARNING: No rows available for {filename}")
        return

    path = REPORT_DIR / filename

    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=list(rows[0].keys())
        )

        writer.writeheader()
        writer.writerows(rows)

    print(f"Created: {path}")


def safe_average(values):

    if not values:
        return 0.0

    return sum(values) / len(values)


def safe_profit_factor(gross_profit, gross_loss):

    if gross_loss > 0:
        return round(gross_profit / gross_loss, 3)

    if gross_profit > 0:
        return "N/A"

    return 0


def get_timestamp():

    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# 3. LOAD AND VALIDATE INPUT FILES
# ============================================================

def load_all_data():

    print("\nLoading existing research CSV files...")

    data = {}

    for key, filename in INPUT_FILES.items():

        data[key] = read_csv(filename)

        print(
            f"{filename}: {len(data[key])} rows"
        )

    expected_counts = {
        "backtest": 12,
        "regime_attribution": 84,
        "regime_coverage": 36,
        "signal_distribution": 108,
        "blocked_outcomes": 97,
        "blocked_summary": 8,
    }

    print("\nValidating expected row counts...")

    for key, expected in expected_counts.items():

        actual = len(data[key])

        if actual != expected:

            raise ValueError(
                f"{key}: expected {expected} rows, "
                f"but found {actual}. "
                "Check the source CSV before proceeding."
            )

        print(f"{key}: PASS ({actual} rows)")

    expected_runs = {
        (instrument, period, experiment)
        for instrument in INSTRUMENTS
        for period in PERIODS
        for experiment in EXPERIMENTS
    }

    actual_runs = {
        (
            row["instrument"],
            row["period"],
            row["experiment"]
        )
        for row in data["backtest"]
    }

    missing = expected_runs - actual_runs

    if missing:

        raise ValueError(
            f"Missing backtest combinations: {sorted(missing)}"
        )

    print("\nAll required input files validated.")

    return data


# ============================================================
# 4. BACKTEST PERFORMANCE COMPARISON
# ============================================================

def build_backtest_comparison(backtest_rows):

    print("\nBuilding backtest comparison...")

    lookup = {
        (
            row["instrument"],
            row["period"],
            row["experiment"]
        ): row

        for row in backtest_rows
    }

    output = []

    for instrument in INSTRUMENTS:

        for period in PERIODS:

            baseline = lookup[
                (instrument, period, "BASELINE")
            ]

            result = {
                "instrument": instrument,
                "period": period,
            }

            variants = [
                ("BASELINE", "baseline"),
                ("ADX_GE_20", "adx20"),
                ("ADX_GE_25", "adx25"),
            ]

            for experiment, prefix in variants:

                row = lookup[
                    (instrument, period, experiment)
                ]

                trades = to_int(row["trades"])

                pnl = to_float(
                    row["closed_pnl_points"]
                )

                drawdown = to_float(
                    row["max_drawdown_points"]
                )

                result.update({

                    f"{prefix}_trades":
                        trades,

                    f"{prefix}_win_rate_pct":
                        to_float(row["win_rate_percent"]),

                    f"{prefix}_profit_factor":
                        to_float(row["profit_factor"]),

                    f"{prefix}_expectancy_points":
                        to_float(row["expectancy_points"]),

                    f"{prefix}_closed_pnl_points":
                        pnl,

                    f"{prefix}_max_drawdown_points":
                        drawdown,

                    f"{prefix}_drawdown_recovered":
                        to_bool(row["drawdown_recovered"]),

                    f"{prefix}_blocked_entries":
                        to_int(row["blocked_entries"]),

                    f"{prefix}_attributed_trades":
                        to_int(row["attributed_trades"]),

                    f"{prefix}_unattributed_trades":
                        to_int(row["unattributed_trades"]),

                    f"{prefix}_open_position":
                        to_bool(row["open_position_present"]),

                    f"{prefix}_unexecuted_final_signal":
                        to_bool(
                            row["unexecuted_final_signal_present"]
                        ),
                })

                if experiment != "BASELINE":

                    result.update({

                        f"{prefix}_pnl_delta_vs_baseline":
                            round(
                                pnl - to_float(
                                    baseline["closed_pnl_points"]
                                ),
                                6
                            ),

                        f"{prefix}_drawdown_delta_vs_baseline":
                            round(
                                drawdown - to_float(
                                    baseline["max_drawdown_points"]
                                ),
                                6
                            ),

                        f"{prefix}_trade_count_delta_vs_baseline":
                            trades - to_int(
                                baseline["trades"]
                            ),
                    })

            output.append(result)

    return output


# ============================================================
# 5. SIGNAL DISTRIBUTION ANALYSIS
# ============================================================

def build_signal_analysis(signal_rows):

    print("\nBuilding signal distribution analysis...")

    regime_detail = []

    totals = defaultdict(
        lambda: {
            "attempts": 0,
            "accepted": 0,
            "blocked": 0,
            "missing_adx": 0,
        }
    )

    for row in signal_rows:

        key = (
            row["instrument"],
            row["period"],
            row["experiment"],
        )

        attempts = to_int(
            row["entry_signal_attempts"]
        )

        accepted = to_int(
            row["accepted_entries"]
        )

        blocked = to_int(
            row["blocked_entries"]
        )

        missing = to_int(
            row["blocked_adx_missing"]
        )

        totals[key]["attempts"] += attempts
        totals[key]["accepted"] += accepted
        totals[key]["blocked"] += blocked
        totals[key]["missing_adx"] += missing

        regime_detail.append({

            "instrument": row["instrument"],
            "period": row["period"],
            "experiment": row["experiment"],
            "regime": row["regime"],

            "entry_signal_attempts": attempts,
            "accepted_entries": accepted,
            "blocked_entries": blocked,

            "blocked_adx_threshold":
                row["blocked_adx_threshold"],

            "blocked_adx_missing": missing,

            "accepted_percent_of_attempts":
                to_float(
                    row["accepted_percent_of_attempts"]
                ),
        })

    summary = []

    for key, values in sorted(totals.items()):

        attempts = values["attempts"]

        acceptance = (
            100 * values["accepted"] / attempts
            if attempts else 0
        )

        summary.append({

            "instrument": key[0],
            "period": key[1],
            "experiment": key[2],

            "signal_attempts": attempts,
            "accepted_entries": values["accepted"],
            "blocked_entries": values["blocked"],

            "acceptance_rate_pct":
                round(acceptance, 2),

            "missing_adx_blocks":
                values["missing_adx"],
        })

    return regime_detail, summary


# ============================================================
# 6. BLOCKED SIGNAL RISK & REWARD
# ============================================================

def build_blocked_risk_reward(blocked_rows):

    print("\nBuilding blocked signal risk/reward analysis...")

    groups = defaultdict(list)

    for row in blocked_rows:

        key = (
            row["instrument"],
            row["period"],
            row["filter_experiment"],
        )

        groups[key].append(row)

    output = []

    for key, rows in sorted(groups.items()):

        # The outcome label is the primary classification.
        # This avoids depending on undocumented status spellings.

        closed = [
            row for row in rows
            if row["baseline_trade_outcome"].strip().upper()
            in ("PROFIT", "LOSS", "BREAKEVEN")
        ]

        winners = [
            row for row in closed
            if row["baseline_trade_outcome"].strip().upper()
            == "PROFIT"
        ]

        losers = [
            row for row in closed
            if row["baseline_trade_outcome"].strip().upper()
            == "LOSS"
        ]

        breakeven = [
            row for row in closed
            if row["baseline_trade_outcome"].strip().upper()
            == "BREAKEVEN"
        ]

        open_rows = [
            row for row in rows
            if row["baseline_trade_outcome"].strip().upper()
            == "OPEN_UNREALIZED"
        ]

        winner_values = [
            to_float(row["net_points"])
            for row in winners
        ]

        loser_values = [
            to_float(row["net_points"])
            for row in losers
        ]

        closed_values = [
            to_float(row["net_points"])
            for row in closed
        ]

        gross_profit = sum(
            value for value in winner_values
            if value > 0
        )

        gross_loss = abs(sum(
            value for value in loser_values
            if value < 0
        ))

        holding_days = [
            to_float(row["holding_calendar_days"])
            for row in closed
            if row["holding_calendar_days"].strip()
        ]

        win_rate = (
            100 * len(winners) / len(closed)
            if closed else 0
        )

        open_unrealized = sum(
            to_float(row["unrealized_points"])
            for row in open_rows
        )

        output.append({

            "instrument": key[0],
            "period": key[1],
            "filter_experiment": key[2],

            "blocked_signal_rows": len(rows),

            "closed_trades": len(closed),
            "open_positions": len(open_rows),

            "winners": len(winners),
            "losers": len(losers),
            "breakeven": len(breakeven),

            "win_rate_pct":
                round(win_rate, 2),

            "average_winner_points":
                round(safe_average(winner_values), 2),

            "average_loser_points":
                round(safe_average(loser_values), 2),

            "profit_factor":
                safe_profit_factor(
                    gross_profit,
                    gross_loss
                ),

            "largest_winner_points":
                round(max(winner_values), 2)
                if winner_values else None,

            "largest_loser_points":
                round(min(loser_values), 2)
                if loser_values else None,

            "average_holding_calendar_days":
                round(safe_average(holding_days), 2)
                if holding_days else None,

            "closed_trade_net_points":
                round(sum(closed_values), 2),

            "open_unrealized_points":
                round(open_unrealized, 2),
        })

    return output


# ============================================================
# 7. BLOCKED SIGNAL SUMMARY
# ============================================================

def build_blocked_summary(summary_rows):

    output = []

    for row in summary_rows:

        output.append({

            "instrument": row["instrument"],
            "period": row["period"],
            "filter_experiment": row["filter_experiment"],

            "blocked_signals":
                to_int(row["blocked_signals"]),

            "matched_closed_trades":
                to_int(row["matched_closed_trades"]),

            "matched_open_positions":
                to_int(row["matched_open_positions"]),

            "unmatched_signals":
                to_int(row["unmatched_signals"]),

            "no_next_bar_in_period":
                to_int(row["no_next_bar_in_period"]),

            "profitable_closed_trades":
                to_int(row["profitable_closed_trades"]),

            "losing_closed_trades":
                to_int(row["losing_closed_trades"]),

            "breakeven_closed_trades":
                to_int(row["breakeven_closed_trades"]),

            "closed_trade_net_points":
                to_float(row["closed_trade_net_points"]),

            "open_position_unrealized_points":
                to_float(
                    row["open_position_unrealized_points"]
                ),
        })

    return output


# ============================================================
# 8. MARKET REGIME ATTRIBUTION DETAIL
# ============================================================

def build_regime_attribution(attribution_rows):

    output = []

    for row in attribution_rows:

        output.append({

            "instrument": row["instrument"],
            "period": row["period"],
            "experiment": row["experiment"],
            "regime": row["regime"],

            "trades": to_int(row["trades"]),
            "winning_trades": to_int(row["winning_trades"]),
            "losing_trades": to_int(row["losing_trades"]),
            "breakeven_trades": to_int(row["breakeven_trades"]),

            "win_rate_percent":
                to_float(row["win_rate_percent"]),

            "gross_profit_points":
                to_float(row["gross_profit_points"]),

            "gross_loss_points":
                to_float(row["gross_loss_points"]),

            "profit_factor":
                row["profit_factor"],

            "net_points":
                to_float(row["net_points"]),

            "average_net_points":
                to_float(row["average_net_points"]),

            "expectancy_points":
                to_float(row["expectancy_points"]),
        })

    return output


# ============================================================
# 9. MARKET REGIME COVERAGE DETAIL
# ============================================================

def build_coverage_detail(coverage_rows):

    output = []

    for row in coverage_rows:

        output.append({

            "instrument": row["instrument"],
            "period": row["period"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "regime": row["regime"],

            "daily_candles":
                to_int(row["daily_candles"]),

            "ema_9_20_current_available":
                to_int(row["ema_9_20_current_available"]),

            "ema_9_20_previous_and_current_available":
                to_int(
                    row["ema_9_20_previous_and_current_available"]
                ),

            "adx_14_available":
                to_int(row["adx_14_available"]),

            "indicator_status_ready":
                to_int(row["indicator_status_ready"]),

            "percentage_of_period_candles":
                to_float(
                    row["percentage_of_period_candles"]
                ),
        })

    return output


# ============================================================
# 10. FINAL MARKDOWN REPORT
# ============================================================

def create_markdown_report(
    comparison,
    signal_summary,
    risk_reward,
    attribution,
    coverage,
    timestamp
):

    lines = []

    lines.append(
        "# ADX Filter Robustness & Final Comparison V1"
    )

    lines.append("")

    lines.append(
        f"Generated: {datetime.now().isoformat(timespec='seconds')}"
    )

    lines.append("")

    lines.append("## 1. Research scope")

    lines.append("")

    lines.append("- Instruments: NIFTY50 and SENSEX")
    lines.append("- Periods: 2012-2019 and 2020-2026")
    lines.append("- Strategy: EMA 9/20 LONG_ONLY")
    lines.append("- Execution: NEXT_BAR_OPEN")
    lines.append("- Slippage: 5 bps")
    lines.append("- Variants: BASELINE, BLOCK_ADX_GE_20, BLOCK_ADX_GE_25")
    lines.append("- Source of regime attribution: signal candle classification")
    lines.append("- Database writes: None")
    lines.append("- Backtests rerun: No")

    lines.append("")

    lines.append("## 2. Backtest performance comparison")

    lines.append("")

    lines.append(
        "| Instrument | Period | Variant | Trades | Win % | PF | "
        "Net P&L | Max DD | DD Recovered |"
    )

    lines.append(
        "|---|---|---|---:|---:|---:|---:|---:|---|"
    )

    for row in comparison:

        for prefix, label in [
            ("baseline", "BASELINE"),
            ("adx20", "ADX 20"),
            ("adx25", "ADX 25"),
        ]:

            lines.append(
                f"| {row['instrument']} "
                f"| {row['period']} "
                f"| {label} "
                f"| {row[prefix + '_trades']} "
                f"| {row[prefix + '_win_rate_pct']:.2f} "
                f"| {row[prefix + '_profit_factor']:.3f} "
                f"| {row[prefix + '_closed_pnl_points']:.2f} "
                f"| {row[prefix + '_max_drawdown_points']:.2f} "
                f"| {row[prefix + '_drawdown_recovered']} |"
            )

    lines.append("")

    lines.append("## 3. Filter performance delta versus baseline")

    lines.append("")

    lines.append(
        "| Instrument | Period | Filter | P&L delta | "
        "Max DD delta | Trade count delta |"
    )

    lines.append(
        "|---|---|---|---:|---:|---:|"
    )

    for row in comparison:

        for prefix, label in [
            ("adx20", "ADX 20"),
            ("adx25", "ADX 25"),
        ]:

            lines.append(
                f"| {row['instrument']} "
                f"| {row['period']} "
                f"| {label} "
                f"| {row[prefix + '_pnl_delta_vs_baseline']:.2f} "
                f"| {row[prefix + '_drawdown_delta_vs_baseline']:.2f} "
                f"| {row[prefix + '_trade_count_delta_vs_baseline']} |"
            )

    lines.append("")

    lines.append("## 4. Signal acceptance analysis")

    lines.append("")

    lines.append(
        "| Instrument | Period | Variant | Attempts | Accepted | "
        "Blocked | Acceptance % |"
    )

    lines.append(
        "|---|---|---|---:|---:|---:|---:|"
    )

    for row in signal_summary:

        lines.append(
            f"| {row['instrument']} "
            f"| {row['period']} "
            f"| {row['experiment']} "
            f"| {row['signal_attempts']} "
            f"| {row['accepted_entries']} "
            f"| {row['blocked_entries']} "
            f"| {row['acceptance_rate_pct']:.2f}% |"
        )

    lines.append("")

    lines.append("## 5. Blocked signal risk/reward")

    lines.append("")

    lines.append(
        "| Instrument | Period | Filter | Closed | Winners | "
        "Losers | Win % | PF | Net Points | Avg Hold Days |"
    )

    lines.append(
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"
    )

    for row in risk_reward:

        lines.append(
            f"| {row['instrument']} "
            f"| {row['period']} "
            f"| {row['filter_experiment']} "
            f"| {row['closed_trades']} "
            f"| {row['winners']} "
            f"| {row['losers']} "
            f"| {row['win_rate_pct']:.2f}% "
            f"| {row['profit_factor']} "
            f"| {row['closed_trade_net_points']:.2f} "
            f"| {row['average_holding_calendar_days']} |"
        )

    lines.append("")

    lines.append("## 6. Market-regime attribution")

    lines.append("")

    lines.append(
        f"Regime attribution records retained: {len(attribution)}."
    )

    lines.append(
        "The detailed CSV preserves all seven market-cycle categories, "
        "including categories with zero attributed trades."
    )

    lines.append("")

    lines.append("## 7. Market-regime coverage")

    lines.append("")

    lines.append(
        f"Market-regime coverage records retained: {len(coverage)}."
    )

    lines.append(
        "Coverage and indicator availability are retained in the "
        "supporting CSV rather than inferred from trade counts."
    )

    lines.append("")

    lines.append("## 8. Research interpretation")

    lines.append("")

    lines.append(
        "Blocked-signal outcomes are matched to the baseline trade ledger. "
        "They are not actual filtered-portfolio returns."
    )

    lines.append("")

    lines.append(
        "Filtering changes the one-position-at-a-time trade sequence. "
        "Therefore, rejected baseline trades cannot simply be subtracted "
        "from baseline P&L to calculate filtered strategy P&L."
    )

    lines.append("")

    lines.append(
        "NIFTY50 and SENSEX index points should not be pooled into a "
        "single combined P&L because their point scales differ."
    )

    lines.append("")

    lines.append(
        "Small sample sizes, particularly individual period and "
        "instrument cohorts, limit the strength of conclusions."
    )

    lines.append("")

    lines.append("## 9. Final research disposition")

    lines.append("")

    lines.append(
        "**No permanent ADX threshold is selected.**"
    )

    lines.append("")

    lines.append(
        "ADX 20 and ADX 25 remain research candidates. Neither threshold "
        "has demonstrated universal superiority across both instruments "
        "and historical periods."
    )

    lines.append("")

    lines.append(
        "Any further promotion should require additional robustness "
        "testing and out-of-sample validation."
    )

    lines.append("")

    lines.append("## 10. Generated supporting files")

    lines.append("")

    lines.append(
        f"- adx_filter_robustness_comparison_{timestamp}.csv"
    )

    lines.append(
        f"- adx_filter_signal_regime_detail_{timestamp}.csv"
    )

    lines.append(
        f"- adx_filter_signal_summary_{timestamp}.csv"
    )

    lines.append(
        f"- adx_filter_blocked_risk_reward_{timestamp}.csv"
    )

    lines.append(
        f"- adx_filter_regime_attribution_detail_{timestamp}.csv"
    )

    lines.append(
        f"- adx_filter_regime_coverage_detail_{timestamp}.csv"
    )

    lines.append(
        f"- adx_filter_final_research_report_{timestamp}.md"
    )

    return "\n".join(lines) + "\n"


# ============================================================
# 11. MAIN EXECUTION
# ============================================================

def main():

    print("\n==============================================")
    print(" ADX FILTER ROBUSTNESS & FINAL COMPARISON V1")
    print("==============================================")

    print("\nMode: READ ONLY")
    print("Database writes: NONE")
    print("Backtests rerun: NO")

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    data = load_all_data()

    timestamp = get_timestamp()

    # Backtest comparison

    comparison = build_backtest_comparison(
        data["backtest"]
    )

    # Signal analysis

    signal_detail, signal_summary = build_signal_analysis(
        data["signal_distribution"]
    )

    # Blocked trade risk/reward

    risk_reward = build_blocked_risk_reward(
        data["blocked_outcomes"]
    )

    # Supporting datasets

    blocked_summary = build_blocked_summary(
        data["blocked_summary"]
    )

    attribution = build_regime_attribution(
        data["regime_attribution"]
    )

    coverage = build_coverage_detail(
        data["regime_coverage"]
    )

    # Generate filenames

    filenames = {

        "comparison":
            f"adx_filter_robustness_comparison_{timestamp}.csv",

        "signal_detail":
            f"adx_filter_signal_regime_detail_{timestamp}.csv",

        "signal_summary":
            f"adx_filter_signal_summary_{timestamp}.csv",

        "risk_reward":
            f"adx_filter_blocked_risk_reward_{timestamp}.csv",

        "blocked_summary":
            f"adx_filter_blocked_summary_{timestamp}.csv",

        "attribution":
            f"adx_filter_regime_attribution_detail_{timestamp}.csv",

        "coverage":
            f"adx_filter_regime_coverage_detail_{timestamp}.csv",

        "report":
            f"adx_filter_final_research_report_{timestamp}.md",
    }

    # Write supporting CSV files

    write_csv(
        filenames["comparison"],
        comparison
    )

    write_csv(
        filenames["signal_detail"],
        signal_detail
    )

    write_csv(
        filenames["signal_summary"],
        signal_summary
    )

    write_csv(
        filenames["risk_reward"],
        risk_reward
    )

    write_csv(
        filenames["blocked_summary"],
        blocked_summary
    )

    write_csv(
        filenames["attribution"],
        attribution
    )

    write_csv(
        filenames["coverage"],
        coverage
    )

    # Generate final Markdown report

    markdown = create_markdown_report(
        comparison,
        signal_summary,
        risk_reward,
        attribution,
        coverage,
        timestamp
    )

    report_path = REPORT_DIR / filenames["report"]

    report_path.write_text(
        markdown,
        encoding="utf-8"
    )

    print(f"Created: {report_path}")

    # Final verification

    print("\n==============================================")
    print(" FINAL OUTPUT VERIFICATION")
    print("==============================================")

    for filename in filenames.values():

        path = REPORT_DIR / filename

        if path.exists() and path.stat().st_size > 0:

            print(
                f"PASS: {filename} "
                f"({path.stat().st_size} bytes)"
            )

        else:

            raise RuntimeError(
                f"Output verification failed: {path}"
            )

    print("\n==============================================")
    print(" ADX RESEARCH REPORT COMPLETED SUCCESSFULLY")
    print("==============================================")

    print("\nGenerated output directory:")
    print(REPORT_DIR)

    print("\nNo database changes were made.")
    print("No backtests were rerun.")


if __name__ == "__main__":

    main()

