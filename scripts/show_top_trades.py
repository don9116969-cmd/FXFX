"""
Extract detailed trade logs for Rank 1, 2, 3, and 4
"""

import sys
import os
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_manager import ForexDataManager
from src.backtester import ForexBacktester
from src.strategy_lab import StrategyLaboratory

dm = ForexDataManager()
lab = StrategyLaboratory()

ranks = [
    {
        "rank": 1,
        "name": "Rank 1: London ORB on EURJPY (15m)",
        "pair": "EURJPY",
        "tf": "15m",
        "dec": 2,
        "spread": 1.2,
        "strategy": lab.strategy_london_orb,
        "params": {"buffer_pips": 15.0, "rr_ratio": 1.5, "sl_at_mid": True}
    },
    {
        "rank": 2,
        "name": "Rank 2: London ORB on GBPUSD (15m)",
        "pair": "GBPUSD",
        "tf": "15m",
        "dec": 4,
        "spread": 1.0,
        "strategy": lab.strategy_london_orb,
        "params": {"buffer_pips": 12.0, "rr_ratio": 2.0, "sl_at_mid": True}
    },
    {
        "rank": 3,
        "name": "Rank 3: Turtle Soup Sweep on USDCAD (15m)",
        "pair": "USDCAD",
        "tf": "15m",
        "dec": 4,
        "spread": 1.1,
        "strategy": lab.strategy_turtle_soup_liquidity,
        "params": {"swing_lookback": 15, "buffer_pips": 5.0, "wick_ratio": 0.4, "rr_ratio": 2.0}
    },
    {
        "rank": 4,
        "name": "Rank 4: London ORB on EURUSD (15m)",
        "pair": "EURUSD",
        "tf": "15m",
        "dec": 4,
        "spread": 0.7,
        "strategy": lab.strategy_london_orb,
        "params": {"buffer_pips": 5.0, "rr_ratio": 1.5, "sl_at_mid": False}
    }
]

for r in ranks:
    print("=" * 80)
    print(f"{r['name']}")
    print(f"Parameters: {r['params']}")
    print("=" * 80)

    df = dm.load_cached_data(r["pair"], r["tf"])
    pip_size = 10 ** (-r["dec"])
    bt = ForexBacktester(pair=r["pair"], spread_pips=r["spread"], pip_decimal=r["dec"])
    split_idx = int(len(df) * 0.60)
    df_test = df.iloc[split_idx:]

    sigs = r["strategy"](df_test, r["params"], pip_size)
    res = bt.run(df_test, sigs)

    trades = res["trades"]
    m = res["metrics"]

    print(f"Total Trades: {m['Total Trades']}")
    print(f"Win Rate:     {m['Win Rate (%)']}% (Wins: {sum(1 for t in trades if t['pnl'] > 0)}, Losses: {sum(1 for t in trades if t['pnl'] < 0)})")
    print(f"Profit Factor:{m['Profit Factor']}")
    print(f"Net Profit:   ${m['Net Profit ($)']} ({m['Return (%)']}%)")
    print(f"Max Drawdown: {m['Max Drawdown (%)']}%")
    print(f"Sharpe Ratio: {m['Sharpe Ratio']}")
    print(f"Expectancy:   ${m['Expectancy ($)']} per trade")

    tdf = pd.DataFrame(trades)
    if not tdf.empty:
        tdf["Side"] = tdf["side"].map({1: "BUY", -1: "SELL"})
        tdf["Entry Time (UTC)"] = tdf["entry_time"].dt.strftime("%Y-%m-%d %H:%M")
        tdf["Exit Time (UTC)"] = tdf["exit_time"].dt.strftime("%Y-%m-%d %H:%M")
        tdf["Bars Held"] = tdf["bars_held"]
        tdf["Entry Price"] = tdf["entry_price"]
        tdf["Exit Price"] = tdf["exit_price"]
        tdf["Result"] = tdf["exit_reason"]
        tdf["PnL ($)"] = tdf["pnl"]
        tdf["Return ($)"] = tdf["PnL ($)"].apply(lambda x: f"+${x:.2f}" if x > 0 else f"-${abs(x):.2f}")

        cols = ["#", "Side", "Entry Time (UTC)", "Entry Price", "Exit Time (UTC)", "Exit Price", "Result", "Bars Held", "Return ($)"]
        tdf["#"] = range(1, len(tdf) + 1)
        print("\nComplete Trade Log:")
        print(tdf[cols].to_string(index=False))
    print("\n")
