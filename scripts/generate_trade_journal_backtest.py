"""
Historical Trade Journal Backfill Engine for FXFX.
Runs event-driven backtests across all 8 quantitative strategies using local datasets,
generates the complete trade journal ledger, and updates:
  - data/trade_journal.csv
  - data/trade_journal.md
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from src.strategy_lab import StrategyLaboratory
from src.strategies.strategy_2_variance_ratio import VarianceRatioMeanReversionStrategy
from src.backtester import ForexBacktester
from src.journal_manager import refresh_markdown_journal

DATA_DIR = config.DATA_DIR
JOURNAL_CSV = config.JOURNAL_CSV_FILE

def run_backtest_journal_generation():
    print("=" * 70)
    print("FXFX HISTORICAL TRADE JOURNAL GENERATOR")
    print("Evaluating all 8 Quantitative Strategies on Clean Datasets...")
    print("=" * 70)

    all_trades = []

    for strat_cfg in config.PORTFOLIO_STRATEGIES:
        sid = strat_cfg["id"]
        s_name = strat_cfg["name"]
        pair = strat_cfg["pair"]
        tf = strat_cfg["timeframe"]
        dec = strat_cfg["dec"]
        pip_size = 10 ** (-dec)
        spread_pips = strat_cfg["spread_pips"]
        params = strat_cfg["params"]
        stype = strat_cfg["type"]

        # Find CSV file
        csv_filename = f"{pair}_{tf}.csv"
        csv_path = os.path.join(DATA_DIR, csv_filename)

        if not os.path.exists(csv_path):
            print(f"[SKIP] Data file {csv_filename} not found.")
            continue

        df = pd.read_csv(csv_path)
        if "Datetime" in df.columns:
            df["Datetime"] = pd.to_datetime(df["Datetime"])
            df = df.set_index("Datetime").sort_index()
        elif "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"])
            df = df.set_index("time").sort_index()
        elif "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.set_index("timestamp").sort_index()
        else:
            df.index = pd.to_datetime(df.index)

        # Standardize OHLC column names
        col_map = {c: c.capitalize() for c in df.columns}
        df = df.rename(columns=col_map)

        # Generate signals
        if stype == "ORB":
            sigs = StrategyLaboratory.strategy_london_orb(df, params, pip_size)
        elif stype == "TURTLE":
            sigs = StrategyLaboratory.strategy_turtle_soup_liquidity(df, params, pip_size)
        elif stype == "VARIANCE_RATIO":
            s = VarianceRatioMeanReversionStrategy(pip_decimal=dec)
            sigs = s.generate_signals(df, params)
        else:
            sigs = pd.DataFrame()

        if sigs.empty:
            print(f"[{s_name}] No signals generated.")
            continue

        bt = ForexBacktester(
            pair=pair,
            initial_capital=config.INITIAL_CAPITAL,
            fixed_risk_usd=config.RISK_PER_TRADE_USD,
            spread_pips=spread_pips,
            slippage_pips=config.SLIPPAGE_PIPS,
            pip_decimal=dec
        )

        res = bt.run(df, sigs)
        tr_list = res.get("trades", [])
        print(f"[{s_name}] -> {len(tr_list)} Trades Executed.")

        for t in tr_list:
            e_time = t["entry_time"]
            x_time = t["exit_time"]
            e_time_str = e_time.strftime("%Y-%m-%d %H:%M:%S UTC") if hasattr(e_time, "strftime") else str(e_time)
            x_time_str = x_time.strftime("%Y-%m-%d %H:%M:%S UTC") if hasattr(x_time, "strftime") else str(x_time)
            date_str = e_time_str[:10]

            entry_p = float(t["entry_price"])
            exit_p = float(t["exit_price"])
            side_label = "BUY" if t["side"] == 1 else "SELL"
            pnl = float(t["pnl"])
            pnl_pct = ((exit_p - entry_p) / entry_p * 100.0) if t["side"] == 1 else ((entry_p - exit_p) / entry_p * 100.0)

            all_trades.append({
                "date": date_str,
                "strategy": sid,
                "strategy_name": s_name,
                "pair": pair,
                "timeframe": tf,
                "side": side_label,
                "entry_time": e_time_str,
                "exit_time": x_time_str,
                "entry_price": round(entry_p, 5),
                "exit_price": round(exit_p, 5),
                "units": round(float(t.get("units", 0.0)), 2),
                "risk_usd": round(config.RISK_PER_TRADE_USD, 2),
                "net_pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "exit_reason": str(t.get("exit_reason", "MANUAL")),
                "bars_held": int(t.get("bars_held", 0))
            })

    if not all_trades:
        print("[ERROR] No trades produced across strategies.")
        return

    # Sort chronologically by entry timestamp
    df_journal = pd.DataFrame(all_trades)
    df_journal.sort_values(by=["entry_time"], inplace=True)
    df_journal.drop_duplicates(subset=["strategy", "pair", "entry_time"], keep="first", inplace=True)

    # Save to trade_journal.csv
    df_journal.to_csv(JOURNAL_CSV, index=False)
    print(f"\n[SAVED] {len(df_journal)} completed trades logged to {JOURNAL_CSV}")

    # Regenerate trade_journal.md
    refresh_markdown_journal()
    print(f"[SAVED] Trade Journal Markdown refreshed at {config.JOURNAL_MD_FILE}")

    # Print summary performance
    tot = len(df_journal)
    wins = len(df_journal[df_journal["net_pnl"] > 0])
    losses = len(df_journal[df_journal["net_pnl"] <= 0])
    wr = (wins / tot * 100.0) if tot > 0 else 0.0
    tot_pnl = float(df_journal["net_pnl"].sum())
    end_bal = config.INITIAL_CAPITAL + tot_pnl
    ret_pct = ((end_bal - config.INITIAL_CAPITAL) / config.INITIAL_CAPITAL) * 100.0

    print("=" * 70)
    print(f"Total Trades: {tot}")
    print(f"Win Rate: {wr:.1f}% ({wins} Wins / {losses} Losses)")
    print(f"Cumulative Net PnL: ${tot_pnl:+,.2f}")
    print(f"Final Balance: ${end_bal:,.2f} ({ret_pct:+.2f}% Return)")
    print("=" * 70)

if __name__ == "__main__":
    run_backtest_journal_generation()
