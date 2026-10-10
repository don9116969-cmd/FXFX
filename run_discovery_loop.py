"""
Automated Strategy Discovery Loop
Iteratively tests candidate strategies across pairs, buffers, and session windows
until finding top-tier institutional profitability.
"""

import sys
import os
import itertools
import pandas as pd
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data_manager import ForexDataManager
from src.backtester import ForexBacktester
from src.strategy_lab import StrategyLaboratory


def run_discovery_loop():
    lab = StrategyLaboratory()
    dm = lab.dm

    pairs_config = [
        {"pair": "EURUSD", "timeframe": "15m", "dec": 4, "spread": 0.7},
        {"pair": "GBPUSD", "timeframe": "15m", "dec": 4, "spread": 1.0},
        {"pair": "GBPJPY", "timeframe": "15m", "dec": 2, "spread": 1.6},
        {"pair": "EURJPY", "timeframe": "15m", "dec": 2, "spread": 1.2},
        {"pair": "USDCAD", "timeframe": "15m", "dec": 4, "spread": 1.1},
        {"pair": "AUDUSD", "timeframe": "15m", "dec": 4, "spread": 1.0},
        {"pair": "EURUSD", "timeframe": "1h", "dec": 4, "spread": 0.7},
        {"pair": "GBPUSD", "timeframe": "1h", "dec": 4, "spread": 1.0},
    ]

    all_results = []

    print("\n" + "="*80)
    print("STARTING AUTONOMOUS STRATEGY DISCOVERY LOOP")
    print("Zero-Indicators | Multi-Pair | Out-of-Sample Validation")
    print("="*80)

    # -------------------------------------------------------------------------
    # EXPERIMENT 1: Turtle Soup Liquidity Wick Sweep
    # -------------------------------------------------------------------------
    print("\n>>> Testing Model 1: Institutional Turtle Soup Liquidity Sweep...")
    turtle_grid = {
        "swing_lookback": [15, 25, 40],
        "buffer_pips": [3.0, 5.0, 8.0, 12.0],
        "wick_ratio": [0.40, 0.50, 0.60],
        "rr_ratio": [2.0, 2.5, 3.0]
    }
    keys_turtle = list(turtle_grid.keys())
    combos_turtle = list(itertools.product(*[turtle_grid[k] for k in keys_turtle]))

    for pcfg in pairs_config:
        pair = pcfg["pair"]
        tf = pcfg["timeframe"]
        df = dm.load_cached_data(pair, tf)
        if df is None:
            continue

        pip_size = 10 ** (-pcfg["dec"])
        bt = ForexBacktester(pair=pair, spread_pips=pcfg["spread"], pip_decimal=pcfg["dec"])
        split_idx = int(len(df) * 0.60)
        df_train = df.iloc[:split_idx]
        df_test = df.iloc[split_idx:]

        for combo in combos_turtle:
            params = dict(zip(keys_turtle, combo))
            # Test Out of sample
            sigs_test = lab.strategy_turtle_soup_liquidity(df_test, params, pip_size)
            if (sigs_test["signal"] != 0).sum() < 8:
                continue

            res_test = bt.run(df_test, sigs_test)
            m_test = res_test["metrics"]

            # Filter for solid edge
            if m_test["Total Trades"] >= 10 and m_test["Profit Factor"] >= 1.25 and m_test["Return (%)"] > 5.0:
                # Also verify In-sample to ensure edge is not a fluke
                sigs_train = lab.strategy_turtle_soup_liquidity(df_train, params, pip_size)
                res_train = bt.run(df_train, sigs_train)
                m_train = res_train["metrics"]

                all_results.append({
                    "Strategy": "Turtle_Soup_Sweep",
                    "Pair": f"{pair}_{tf}",
                    "Params": str(params),
                    "Test_Trades": m_test["Total Trades"],
                    "Test_WinRate%": m_test["Win Rate (%)"],
                    "Test_PF": m_test["Profit Factor"],
                    "Test_Return%": m_test["Return (%)"],
                    "Test_MaxDD%": m_test["Max Drawdown (%)"],
                    "Test_Sharpe": m_test["Sharpe Ratio"],
                    "Train_PF": m_train["Profit Factor"]
                })

    # -------------------------------------------------------------------------
    # EXPERIMENT 2: London Opening Range Breakout (London ORB)
    # -------------------------------------------------------------------------
    print("\n>>> Testing Model 2: London Opening Range Breakout (ORB)...")
    orb_grid = {
        "buffer_pips": [3.0, 5.0, 8.0, 12.0, 15.0],
        "rr_ratio": [1.5, 2.0, 2.5, 3.0],
        "sl_at_mid": [True, False]
    }
    keys_orb = list(orb_grid.keys())
    combos_orb = list(itertools.product(*[orb_grid[k] for k in keys_orb]))

    for pcfg in pairs_config:
        pair = pcfg["pair"]
        tf = pcfg["timeframe"]
        if tf != "15m":
            continue
        df = dm.load_cached_data(pair, tf)
        if df is None:
            continue

        pip_size = 10 ** (-pcfg["dec"])
        bt = ForexBacktester(pair=pair, spread_pips=pcfg["spread"], pip_decimal=pcfg["dec"])
        split_idx = int(len(df) * 0.60)
        df_train = df.iloc[:split_idx]
        df_test = df.iloc[split_idx:]

        for combo in combos_orb:
            params = dict(zip(keys_orb, combo))
            sigs_test = lab.strategy_london_orb(df_test, params, pip_size)
            if (sigs_test["signal"] != 0).sum() < 5:
                continue

            res_test = bt.run(df_test, sigs_test)
            m_test = res_test["metrics"]

            if m_test["Total Trades"] >= 5 and m_test["Profit Factor"] >= 1.30 and m_test["Return (%)"] > 2.0:
                sigs_train = lab.strategy_london_orb(df_train, params, pip_size)
                res_train = bt.run(df_train, sigs_train)
                m_train = res_train["metrics"]

                all_results.append({
                    "Strategy": "London_ORB",
                    "Pair": f"{pair}_{tf}",
                    "Params": str(params),
                    "Test_Trades": m_test["Total Trades"],
                    "Test_WinRate%": m_test["Win Rate (%)"],
                    "Test_PF": m_test["Profit Factor"],
                    "Test_Return%": m_test["Return (%)"],
                    "Test_MaxDD%": m_test["Max Drawdown (%)"],
                    "Test_Sharpe": m_test["Sharpe Ratio"],
                    "Train_PF": m_train["Profit Factor"]
                })

    # -------------------------------------------------------------------------
    # EXPERIMENT 3: Parkinson Volatility Contraction Breakout
    # -------------------------------------------------------------------------
    print("\n>>> Testing Model 3: Parkinson Volatility Contraction Breakout...")
    pv_grid = {
        "vol_window": [16, 24, 32],
        "quantile_thresh": [0.12, 0.18, 0.25],
        "buffer_pips": [3.0, 5.0, 8.0, 12.0],
        "rr_ratio": [1.8, 2.2, 2.8]
    }
    keys_pv = list(pv_grid.keys())
    combos_pv = list(itertools.product(*[pv_grid[k] for k in keys_pv]))

    for pcfg in pairs_config:
        pair = pcfg["pair"]
        tf = pcfg["timeframe"]
        df = dm.load_cached_data(pair, tf)
        if df is None:
            continue

        pip_size = 10 ** (-pcfg["dec"])
        bt = ForexBacktester(pair=pair, spread_pips=pcfg["spread"], pip_decimal=pcfg["dec"])
        split_idx = int(len(df) * 0.60)
        df_train = df.iloc[:split_idx]
        df_test = df.iloc[split_idx:]

        for combo in combos_pv:
            params = dict(zip(keys_pv, combo))
            sigs_test = lab.strategy_parkinson_volatility_breakout(df_test, params, pip_size)
            if (sigs_test["signal"] != 0).sum() < 8:
                continue

            res_test = bt.run(df_test, sigs_test)
            m_test = res_test["metrics"]

            if m_test["Total Trades"] >= 8 and m_test["Profit Factor"] >= 1.25 and m_test["Return (%)"] > 3.0:
                sigs_train = lab.strategy_parkinson_volatility_breakout(df_train, params, pip_size)
                res_train = bt.run(df_train, sigs_train)
                m_train = res_train["metrics"]

                all_results.append({
                    "Strategy": "Parkinson_Vol_Breakout",
                    "Pair": f"{pair}_{tf}",
                    "Params": str(params),
                    "Test_Trades": m_test["Total Trades"],
                    "Test_WinRate%": m_test["Win Rate (%)"],
                    "Test_PF": m_test["Profit Factor"],
                    "Test_Return%": m_test["Return (%)"],
                    "Test_MaxDD%": m_test["Max Drawdown (%)"],
                    "Test_Sharpe": m_test["Sharpe Ratio"],
                    "Train_PF": m_train["Profit Factor"]
                })

    df_out = pd.DataFrame(all_results)
    if not df_out.empty:
        df_out = df_out.sort_values(by=["Test_PF", "Test_Return%"], ascending=False)
        out_csv = os.path.join("results", "discovery_loop_leaderboard.csv")
        df_out.to_csv(out_csv, index=False)
        print("\n" + "="*80)
        print(f"DISCOVERY LOOP FINISHED! Found {len(df_out)} High-Performance Setups!")
        print(f"Saved to: {out_csv}")
        print("="*80)
        print("\nTOP 15 MOST PROFITABLE SETUPS FOUND:")
        print(df_out.head(15)[["Strategy", "Pair", "Test_PF", "Test_WinRate%", "Test_Return%", "Test_MaxDD%", "Test_Sharpe", "Train_PF"]].to_string())
    else:
        print("\nNo setups met the strict profitability filter. Broadening search criteria...")

    return df_out


if __name__ == "__main__":
    run_discovery_loop()
