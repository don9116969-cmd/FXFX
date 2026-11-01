"""
Unified 8-Strategy Portfolio Simulator (2024-2026 MT5 Data)
Simulates all 8 strategies operating together in real-time under:
  - $20,000 initial capital
  - $100 risk per trade (0.5% risk)
  - Max 4 concurrent open trades limit across the entire portfolio
  - Realistic spread + slippage + friction buffer + JPY/CAD conversion
  - Bar-by-bar chronological execution (Zero lookahead bias)
"""

import os
import sys
import json
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy_lab import StrategyLaboratory
from src.metrics import calculate_performance_metrics

PAIR_SPECS = {
    "EURUSD": {"dec": 4, "spread": 0.7, "conv": 1.0, "pip": 0.0001},
    "GBPUSD": {"dec": 4, "spread": 1.0, "conv": 1.0, "pip": 0.0001},
    "AUDUSD": {"dec": 4, "spread": 0.9, "conv": 1.0, "pip": 0.0001},
    "USDJPY": {"dec": 2, "spread": 1.0, "conv": 155.0, "pip": 0.01},
    "EURJPY": {"dec": 2, "spread": 1.2, "conv": 155.0, "pip": 0.01},
    "GBPJPY": {"dec": 2, "spread": 1.6, "conv": 155.0, "pip": 0.01},
    "USDCAD": {"dec": 4, "spread": 1.1, "conv": 1.38, "pip": 0.0001},
}

def run_portfolio_simulation(strategies_list: List[Dict[str, Any]], initial_capital: float = 20000.0, risk_per_trade: float = 100.0, max_active: int = 4):
    print("Loading 3-year market data for all pairs...")
    dfs = {}
    signals = {}
    
    for s in strategies_list:
        pair = s["pair"]
        if pair not in dfs:
            dfs[pair] = pd.read_parquet(f"data/{pair}_MT5_15m.parquet")
        
        df = dfs[pair]
        spec = PAIR_SPECS[pair]
        stype = s["type"]
        params = s["params"]
        
        if stype == "ORB":
            sig = StrategyLaboratory.strategy_london_orb(df, params, pip_size=spec["pip"])
        elif stype == "TURTLE":
            sig = StrategyLaboratory.strategy_turtle_soup_liquidity(df, params, pip_size=spec["pip"])
        else:
            raise ValueError(f"Unknown type {stype}")
            
        signals[s["id"]] = sig

    # Find common unified timeline (15m bars across 3 years)
    all_timestamps = sorted(list(dfs["EURUSD"].index))
    
    equity = initial_capital
    active_positions: Dict[str, Dict[str, Any]] = {}
    completed_trades: List[Dict[str, Any]] = []
    equity_curve = []
    
    print(f"Replaying portfolio across {len(all_timestamps)} chronological 15m bars...")
    
    for i, curr_time in enumerate(all_timestamps):
        # 1. Check exits for all active positions
        closed_ids = []
        for strat_id, pos in active_positions.items():
            pair = pos["pair"]
            spec = PAIR_SPECS[pair]
            df = dfs[pair]
            
            if curr_time not in df.index:
                continue
                
            bar = df.loc[curr_time]
            h = bar["High"]
            l = bar["Low"]
            o = bar["Open"]
            c = bar["Close"]
            
            side = pos["side"]
            sl = pos["sl"]
            tp = pos["tp"]
            entry_price = pos["entry_price"]
            units = pos["units"]
            bars_held = pos["bars_held"] + 1
            pos["bars_held"] = bars_held
            
            total_friction = (spec["spread"] + 0.2) * spec["pip"]
            exit_price = None
            exit_reason = None
            
            if side == 1:
                sl_hit = l <= sl
                tp_hit = h >= tp if tp is not None else False
                if sl_hit and tp_hit:
                    exit_price = min(o, sl)
                    exit_reason = "SL"
                elif sl_hit:
                    exit_price = min(o, sl)
                    exit_reason = "SL"
                elif tp_hit:
                    exit_price = max(o, tp)
                    exit_reason = "TP"
                elif pos.get("max_bars") and bars_held >= pos["max_bars"]:
                    exit_price = c
                    exit_reason = "TIMEOUT"
                    
                if exit_price is not None:
                    actual_exit = exit_price - (total_friction / 2.0)
                    raw_pnl = (actual_exit - entry_price) * units
                    pnl = raw_pnl / spec["conv"]
                    equity += pnl
                    pos.update({
                        "exit_time": curr_time,
                        "exit_price": round(actual_exit, 5),
                        "pnl": round(pnl, 2),
                        "exit_reason": exit_reason
                    })
                    completed_trades.append(pos)
                    closed_ids.append(strat_id)
                    
            elif side == -1:
                sl_hit = h >= sl
                tp_hit = l <= tp if tp is not None else False
                if sl_hit and tp_hit:
                    exit_price = max(o, sl)
                    exit_reason = "SL"
                elif sl_hit:
                    exit_price = max(o, sl)
                    exit_reason = "SL"
                elif tp_hit:
                    exit_price = min(o, tp)
                    exit_reason = "TP"
                elif pos.get("max_bars") and bars_held >= pos["max_bars"]:
                    exit_price = c
                    exit_reason = "TIMEOUT"
                    
                if exit_price is not None:
                    actual_exit = exit_price + (total_friction / 2.0)
                    raw_pnl = (entry_price - actual_exit) * units
                    pnl = raw_pnl / spec["conv"]
                    equity += pnl
                    pos.update({
                        "exit_time": curr_time,
                        "exit_price": round(actual_exit, 5),
                        "pnl": round(pnl, 2),
                        "exit_reason": exit_reason
                    })
                    completed_trades.append(pos)
                    closed_ids.append(strat_id)
                    
        for cid in closed_ids:
            del active_positions[cid]

        # 2. Check entries triggered by bar i-1 (executed at bar i open)
        if i > 0 and len(active_positions) < max_active:
            prev_time = all_timestamps[i - 1]
            for s in strategies_list:
                strat_id = s["id"]
                if strat_id in active_positions:
                    continue  # already has active position in this strategy
                if len(active_positions) >= max_active:
                    break     # portfolio capacity reached
                    
                pair = s["pair"]
                spec = PAIR_SPECS[pair]
                sig_df = signals[strat_id]
                
                if prev_time not in sig_df.index:
                    continue
                    
                prev_sig = sig_df.loc[prev_time]
                sig_val = int(prev_sig["signal"])
                if sig_val in (1, -1):
                    df = dfs[pair]
                    if curr_time not in df.index:
                        continue
                    curr_open = df.loc[curr_time, "Open"]
                    total_friction = (spec["spread"] + 0.2) * spec["pip"]
                    prop_sl = float(prev_sig["sl_price"])
                    prop_tp = float(prev_sig["tp_price"]) if not np.isnan(prev_sig["tp_price"]) else None
                    max_b = int(prev_sig["max_bars"]) if not np.isnan(prev_sig["max_bars"]) else 32
                    
                    if sig_val == 1:
                        entry_price = curr_open + (total_friction / 2.0)
                        if prop_sl < entry_price:
                            sl_dist = entry_price - prop_sl
                            effective_sl_dist = sl_dist + (total_friction / 2.0)
                            risk_in_quote = risk_per_trade * spec["conv"]
                            units = risk_in_quote / effective_sl_dist if effective_sl_dist > 0 else 0
                            active_positions[strat_id] = {
                                "strat_id": strat_id,
                                "name": s["name"],
                                "pair": pair,
                                "side": 1,
                                "entry_time": curr_time,
                                "entry_price": round(entry_price, 5),
                                "sl": prop_sl,
                                "tp": prop_tp,
                                "units": units,
                                "bars_held": 0,
                                "max_bars": max_b
                            }
                    elif sig_val == -1:
                        entry_price = curr_open - (total_friction / 2.0)
                        if prop_sl > entry_price:
                            sl_dist = prop_sl - entry_price
                            effective_sl_dist = sl_dist + (total_friction / 2.0)
                            risk_in_quote = risk_per_trade * spec["conv"]
                            units = risk_in_quote / effective_sl_dist if effective_sl_dist > 0 else 0
                            active_positions[strat_id] = {
                                "strat_id": strat_id,
                                "name": s["name"],
                                "pair": pair,
                                "side": -1,
                                "entry_time": curr_time,
                                "entry_price": round(entry_price, 5),
                                "sl": prop_sl,
                                "tp": prop_tp,
                                "units": units,
                                "bars_held": 0,
                                "max_bars": max_b
                            }

        equity_curve.append(equity)

    eq_series = pd.Series(equity_curve, index=all_timestamps, name="Portfolio_Equity")
    metrics = calculate_performance_metrics(completed_trades, eq_series, initial_capital=initial_capital)
    
    return {
        "metrics": metrics,
        "trades": completed_trades,
        "equity_curve": eq_series
    }

if __name__ == "__main__":
    from config import config
    res = run_portfolio_simulation(config.PORTFOLIO_STRATEGIES, initial_capital=config.INITIAL_CAPITAL, risk_per_trade=config.RISK_PER_TRADE_USD, max_active=config.MAX_ACTIVE_TRADES)
    print("\nCURRENT PORTFOLIO SIMULATION RESULTS:")
    for k, v in res["metrics"].items():
        print(f"  {k}: {v}")

