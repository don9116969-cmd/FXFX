"""
FXFX Manual Trade Diagnostic & Signal Audit Tool
Checks live market data and audits whether any signals were triggered recently
across all 8 institutional strategies.
"""

import os
import sys
from datetime import datetime, timezone, timedelta
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.live_engine import LivePortfolioEngine, PORTFOLIO_STRATEGIES


def main():
    print("=" * 75)
    print("  FXFX INSTITUTIONAL PORTFOLIO - MANUAL SIGNAL & TRADE AUDIT")
    print(f"  Current UTC Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 75)

    engine = LivePortfolioEngine()

    # 1. Check current saved state
    print("\n[1] ACTIVE POSITIONS IN STATE FILE (data/live_portfolio_state.json):")
    if not engine.active_trades:
        print("  -> Currently 0 open trades in portfolio state.")
    else:
        for sid, t in engine.active_trades.items():
            side_str = "BUY" if t["side"] == 1 else "SELL"
            print(f"  -> [{t.get('strategy_name', sid)}] {t['pair']} {side_str} @ {t['entry_price']} | SL: {t['sl']} | TP: {t['tp']} | Entered: {t.get('entry_time_str')}")

    # 2. Audit recent market candles & signals
    print("\n[2] AUDITING RECENT SIGNALS ACROSS ALL 8 STRATEGIES:")
    total_signals_last_48h = 0
    now_utc = datetime.now(timezone.utc)
    cutoff_48h = now_utc - timedelta(hours=48)

    for strat in PORTFOLIO_STRATEGIES:
        sid = strat["id"]
        name = strat["name"]
        ticker = strat["ticker"]
        tf = strat["timeframe"]
        period = strat["period"]

        print(f"\n--- Strategy: {name} ---")
        print(f"  Pair: {strat['pair']} ({ticker}) | Timeframe: {tf} | Period: {period}")

        df = engine.fetch_live_data(ticker, period, tf)
        if df is None or len(df) < 50:
            print(f"  [ERROR] Could not fetch live data from Yahoo Finance (length: {0 if df is None else len(df)})")
            continue

        latest_bar_time = df.index[-1]
        last_closed_time = df.index[-2]
        latest_close = df.iloc[-1]["Close"]
        print(f"  [DATA OK] Fetched {len(df)} candles.")
        print(f"  Last closed candle : {last_closed_time.strftime('%Y-%m-%d %H:%M UTC')} (Close: {df.iloc[-2]['Close']:.5f})")
        print(f"  Current forming bar: {latest_bar_time.strftime('%Y-%m-%d %H:%M UTC')} (Current: {latest_close:.5f})")

        # Evaluate signals over entire historical window
        sigs = engine.evaluate_strategy_signals(strat, df.iloc[:-1])
        if sigs is None or sigs.empty:
            print("  [WARN] Strategy returned empty dataframe.")
            continue

        non_zero = sigs[sigs["signal"] != 0]
        recent_signals = non_zero[non_zero.index >= cutoff_48h]

        print(f"  Signals in past 10 days : {len(non_zero)}")
        print(f"  Signals in past 48 hours: {len(recent_signals)}")

        if len(recent_signals) > 0:
            total_signals_last_48h += len(recent_signals)
            for sig_time, row in recent_signals.iterrows():
                side_str = "[BUY]" if row["signal"] == 1 else "[SELL]"
                print(f"    * SIGNAL: {sig_time.strftime('%Y-%m-%d %H:%M UTC')} | {side_str} | SL: {row['sl_price']:.5f} | TP: {row['tp_price']:.5f}")
        elif len(non_zero) > 0:
            last_sig_time = non_zero.index[-1]
            last_sig_row = non_zero.iloc[-1]
            side_str = "[BUY]" if last_sig_row["signal"] == 1 else "[SELL]"
            print(f"    (Most recent signal was on {last_sig_time.strftime('%Y-%m-%d %H:%M UTC')}: {side_str})")
        else:
            print("    (No signals met strict entry rules in this entire 10-day period)")

        # Specifically check if the latest closed candle triggered
        latest_sig = int(sigs.iloc[-1].get("signal", 0))
        if latest_sig != 0:
            print(f"  [!] ACTIVE TRIGGER ON LATEST CLOSED CANDLE ({last_closed_time})! Signal = {latest_sig}")
        else:
            print(f"  Latest closed candle status: No entry signal.")

    print("\n" + "=" * 75)
    print(f"  AUDIT SUMMARY: {total_signals_last_48h} total signals fired in the past 48 hours.")
    print("=" * 75)


if __name__ == "__main__":
    main()
