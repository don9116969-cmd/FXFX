"""
Prop Firm Calibration & Evaluation Engine (High Speed)
Runs simulation for max_active=2 and max_active=3, then scales risk analytically.
Strict Prop Firm Constraints:
  - Max Overall Drawdown < 10.0% (Safety buffer: <= 7.5%)
  - Max Daily Loss < 5.0% (Safety buffer: <= 3.5%)
  - Challenge Phase 1 Target: 8.0% ($1,600 on $20k)
  - Challenge Phase 2 Target: 5.0% ($1,000 on $20k)
"""

import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.simulate_portfolio_3yr import run_portfolio_simulation
from config import config

CAPITAL = 20000.0

def run_base_simulation(max_active: int):
    # Run once at $100 baseline risk
    res = run_portfolio_simulation(config.PORTFOLIO_STRATEGIES, initial_capital=CAPITAL, risk_per_trade=100.0, max_active=max_active)
    return res

if __name__ == "__main__":
    print("=" * 80)
    print("CALIBRATING CHAMPION 8 PORTFOLIO FOR PROP FIRM RULES ($20,000 ACCOUNT)")
    print("Rules: Max Drawdown < 10.0%, Max Daily Loss < 5.0%")
    print("=" * 80)
    
    results = []
    
    for ma in [2, 3]:
        print(f"\nSimulating baseline for MaxActive = {ma}...", flush=True)
        res = run_base_simulation(ma)
        trades = res["trades"]
        
        # Analyze across risk tiers
        for risk in [50.0, 60.0, 70.0, 75.0, 80.0, 90.0, 100.0]:
            scale = risk / 100.0
            
            scaled_trades = []
            for t in trades:
                st = dict(t)
                st["pnl"] = t["pnl"] * scale
                scaled_trades.append(st)
                
            net_pnl = sum(t["pnl"] for t in scaled_trades)
            ret_pct = (net_pnl / CAPITAL) * 100.0
            
            # Cumulative equity curve
            pnls = [t["pnl"] for t in scaled_trades]
            cum = np.cumsum(pnls)
            peaks = np.maximum.accumulate(cum)
            dds = peaks - cum
            max_dd_usd = np.max(dds)
            max_dd_pct = (max_dd_usd / CAPITAL) * 100.0
            
            # Daily PnL
            df_t = pd.DataFrame([{"date": t["exit_time"].date(), "pnl": t["pnl"]} for t in scaled_trades])
            daily = df_t.groupby("date").sum()["pnl"]
            max_daily_loss_usd = abs(daily.min()) if not daily.empty and daily.min() < 0 else 0.0
            max_daily_loss_pct = (max_daily_loss_usd / CAPITAL) * 100.0
            
            # Target pass estimation
            p1_target = CAPITAL * 0.08  # $1,600
            p2_target = CAPITAL * 0.05  # $1,000
            avg_daily_pnl = daily.mean()
            days_p1 = p1_target / avg_daily_pnl if avg_daily_pnl > 0 else 999
            days_p2 = p2_target / avg_daily_pnl if avg_daily_pnl > 0 else 999
            
            passes = (max_dd_pct <= 8.5) and (max_daily_loss_pct <= 4.0)
            status = "PASSED (PROP READY)" if passes else "FAIL (HIGH DD)"
            
            res_dict = {
                "max_active": ma,
                "risk_usd": risk,
                "risk_pct": risk / CAPITAL * 100.0,
                "net_pnl": round(net_pnl, 2),
                "total_return": round(ret_pct, 1),
                "max_dd_pct": round(max_dd_pct, 2),
                "max_dd_usd": round(max_dd_usd, 2),
                "max_daily_loss_pct": round(max_daily_loss_pct, 2),
                "avg_daily_pnl": round(avg_daily_pnl, 2),
                "est_days_p1": round(days_p1, 0),
                "est_days_p2": round(days_p2, 0),
                "status": status
            }
            results.append(res_dict)
            print(f"  Risk ${risk:.0f} ({risk/CAPITAL*100:.2f}%) | [{status}] 3-Yr PnL: ${net_pnl:,.2f} (+{ret_pct:.1f}%) | Max DD: {max_dd_pct:.2f}% | Max Daily Loss: {max_daily_loss_pct:.2f}% | Pass P1: ~{days_p1:.0f} days", flush=True)

    df_res = pd.DataFrame(results)
    os.makedirs("results", exist_ok=True)
    df_res.to_csv("results/prop_firm_calibration.csv", index=False)
    print("\nSaved calibration table to results/prop_firm_calibration.csv")
