import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from src.strategy_lab import StrategyLaboratory
from src.backtester import ForexBacktester

champion_strats = [
    {
        "id": "strat_1_eurusd_orb",
        "name": "Rank 1: London ORB (EURUSD 15m)",
        "pair": "EURUSD",
        "dec": 4,
        "spread_pips": 0.7,
        "type": "ORB",
        "params": {"buffer_pips": 2.0, "rr_ratio": 2.0, "sl_at_mid": False, "max_bars": 36}
    },
    {
        "id": "strat_2_eurjpy_turtle",
        "name": "Rank 2: Turtle Soup Sweep (EURJPY 15m)",
        "pair": "EURJPY",
        "dec": 2,
        "spread_pips": 1.2,
        "type": "TURTLE",
        "params": {"swing_lookback": 30, "buffer_pips": 2.0, "wick_ratio": 0.6, "rr_ratio": 2.0, "max_bars": 36}
    },
    {
        "id": "strat_3_gbpjpy_turtle",
        "name": "Rank 3: Turtle Soup Sweep (GBPJPY 15m)",
        "pair": "GBPJPY",
        "dec": 2,
        "spread_pips": 1.6,
        "type": "TURTLE",
        "params": {"swing_lookback": 40, "buffer_pips": 2.0, "wick_ratio": 0.5, "rr_ratio": 2.0, "max_bars": 20}
    },
    {
        "id": "strat_4_gbpusd_orb",
        "name": "Rank 4: London ORB (GBPUSD 15m)",
        "pair": "GBPUSD",
        "dec": 4,
        "spread_pips": 1.0,
        "type": "ORB",
        "params": {"buffer_pips": 5.0, "rr_ratio": 3.0, "sl_at_mid": True, "max_bars": 36}
    },
    {
        "id": "strat_5_audusd_turtle",
        "name": "Rank 5: Turtle Soup Sweep (AUDUSD 15m)",
        "pair": "AUDUSD",
        "dec": 4,
        "spread_pips": 0.9,
        "type": "TURTLE",
        "params": {"swing_lookback": 12, "buffer_pips": 2.0, "wick_ratio": 0.4, "rr_ratio": 2.5, "max_bars": 20}
    },
    {
        "id": "strat_6_usdcad_turtle",
        "name": "Rank 6: Turtle Soup Sweep (USDCAD 15m)",
        "pair": "USDCAD",
        "dec": 4,
        "spread_pips": 1.1,
        "type": "TURTLE",
        "params": {"swing_lookback": 12, "buffer_pips": 5.0, "wick_ratio": 0.6, "rr_ratio": 2.0, "max_bars": 36}
    },
    {
        "id": "strat_7_audusd_orb",
        "name": "Rank 7: London ORB (AUDUSD 15m)",
        "pair": "AUDUSD",
        "dec": 4,
        "spread_pips": 0.9,
        "type": "ORB",
        "params": {"buffer_pips": 2.0, "rr_ratio": 1.5, "sl_at_mid": True, "max_bars": 28}
    },
    {
        "id": "strat_8_usdjpy_orb",
        "name": "Rank 8: London ORB (USDJPY 15m)",
        "pair": "USDJPY",
        "dec": 2,
        "spread_pips": 1.0,
        "type": "ORB",
        "params": {"buffer_pips": 12.0, "rr_ratio": 2.0, "sl_at_mid": True, "max_bars": 36}
    }
]

def main():
    total_pnl = 0.0
    total_trades = 0
    total_wins = 0

    print("=" * 85)
    print("CHAMPION 100% 15-MINUTE STRATEGY PORTFOLIO BACKTEST (JULY - OCT 2026)")
    print("=" * 85)

    for s in champion_strats:
        pair = s['pair']
        data_path = os.path.join(config.DATA_DIR, f"{pair}_15m.csv")
        if not os.path.exists(data_path):
            print(f"File missing: {data_path}")
            continue

        df = pd.read_csv(data_path)
        col_map = {c: c.capitalize() for c in df.columns}
        df = df.rename(columns=col_map)
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        df = df.set_index('Datetime').sort_index()
        pip_size = 10 ** (-s['dec'])

        if s['type'] == 'ORB':
            sigs = StrategyLaboratory.strategy_london_orb(df, s['params'], pip_size)
        else:
            sigs = StrategyLaboratory.strategy_turtle_soup_liquidity(df, s['params'], pip_size)

        bt = ForexBacktester(
            pair=pair,
            initial_capital=10000.0,
            fixed_risk_usd=100.0,
            spread_pips=s['spread_pips'],
            slippage_pips=0.2,
            pip_decimal=s['dec']
        )
        res = bt.run(df, sigs)
        trades = res.get('trades', [])
        pnl = sum(t['pnl'] for t in trades)
        wins = sum(1 for t in trades if t['pnl'] > 0)
        wr = (wins / len(trades) * 100.0) if trades else 0.0

        print(f"{s['name']:<44} | Trades: {len(trades):<3} | WinRate: {wr:5.1f}% | PnL: ${pnl:+8.2f} ({pnl/10000*100:+5.2f}%)")
        total_pnl += pnl
        total_trades += len(trades)
        total_wins += wins

    print("=" * 85)
    overall_wr = (total_wins / total_trades * 100.0) if total_trades else 0.0
    ret_pct = total_pnl / 10000.0 * 100.0
    print(f"TOTAL 15m PORTFOLIO: Trades: {total_trades} | Win Rate: {overall_wr:.1f}% | Combined PnL: +${total_pnl:,.2f} (+{ret_pct:.2f}%)")
    print("=" * 85)

if __name__ == "__main__":
    main()
