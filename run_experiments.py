"""
Forex Zero-Indicator Strategy Lab & Grid Search Runner
Runs comprehensive grid optimization across all 5 strategies and top currency pairs.
"""

import sys
import os
import pandas as pd

# Add workspace to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.backtester import ForexBacktester
from src.grid_optimizer import GridOptimizer
from src.data_manager import ForexDataManager
from src.strategies.strategy_1_asian_sweep import AsianSessionLiquiditySweepStrategy
from src.strategies.strategy_2_variance_ratio import VarianceRatioMeanReversionStrategy
from src.strategies.strategy_3_fair_value_gap import FairValueGapStrategy
from src.strategies.strategy_4_mandelbrot_compression import MandelbrotVolatilityExpansionStrategy
from src.strategies.strategy_5_cross_pair_divergence import CrossPairSMTDivergenceStrategy


def run_strategy_1_experiments(dm: ForexDataManager):
    print("\n" + "="*70)
    print(">>> RUNNING STRATEGY 1: Institutional Asian Session Liquidity Sweep <<<")
    print("="*70)

    strat = AsianSessionLiquiditySweepStrategy(pip_decimal=4)
    backtester = ForexBacktester(
        pair="EURUSD",
        initial_capital=10000.0,
        risk_per_trade_pct=1.0,
        spread_pips=0.7,
        pip_decimal=4
    )
    optimizer = GridOptimizer(backtester=backtester, train_test_split_ratio=0.60)

    # Load 15m data
    df = dm.load_cached_data("EURUSD", "15m")
    if df is None:
        print("Data for EURUSD 15m not found!")
        return

    # User parameter range: Buffer 5 to 25
    param_grid = {
        "buffer_pips": [5.0, 10.0, 15.0, 20.0, 25.0],
        "rr_ratio": [1.5, 2.0, 2.5, 3.0],
        "max_holding_bars": [24, 32]
    }

    res_df = optimizer.run_grid(
        strategy_func=strat.generate_signals,
        df=df,
        param_grid=param_grid,
        strategy_name="Strat1_AsianSweep"
    )

    if not res_df.empty:
        print("\nTop 5 Parameter Sets for Strategy 1 (Sorted by Out-Of-Sample Profit Factor & Sharpe):")
        print(res_df.head(5)[["buffer_pips", "rr_ratio", "max_holding_bars", "Train_PF", "Test_PF", "Test_WinRate", "Test_Sharpe", "Test_MaxDD%"]].to_string())


def run_strategy_2_experiments(dm: ForexDataManager):
    print("\n" + "="*70)
    print(">>> RUNNING STRATEGY 2: Lo-MacKinlay Variance Ratio Mean-Reversion <<<")
    print("="*70)

    strat = VarianceRatioMeanReversionStrategy(pip_decimal=4)
    backtester = ForexBacktester(
        pair="EURUSD",
        initial_capital=10000.0,
        risk_per_trade_pct=1.0,
        spread_pips=0.7,
        pip_decimal=4
    )
    optimizer = GridOptimizer(backtester=backtester, train_test_split_ratio=0.60)

    # 1h data (deep 2-year history for mathematical variance regime)
    df = dm.load_cached_data("EURUSD", "1h")
    if df is None:
        print("Data for EURUSD 1h not found!")
        return

    param_grid = {
        "lookback_n": [40, 60, 80],
        "q_period": [4, 6, 8],
        "vr_threshold": [0.70, 0.75, 0.80],
        "z_entry": [1.8, 2.0, 2.3],
        "rr_ratio": [1.5, 2.0]
    }

    res_df = optimizer.run_grid(
        strategy_func=strat.generate_signals,
        df=df,
        param_grid=param_grid,
        strategy_name="Strat2_VarianceRatio"
    )

    if not res_df.empty:
        print("\nTop 5 Parameter Sets for Strategy 2 (Sorted by Out-Of-Sample PF & Sharpe):")
        print(res_df.head(5)[["lookback_n", "q_period", "vr_threshold", "z_entry", "rr_ratio", "Train_PF", "Test_PF", "Test_WinRate", "Test_Sharpe"]].to_string())


def run_strategy_3_experiments(dm: ForexDataManager):
    print("\n" + "="*70)
    print(">>> RUNNING STRATEGY 3: Structural Fair Value Gap (FVG) Imbalance Fill <<<")
    print("="*70)

    strat = FairValueGapStrategy(pip_decimal=4)
    backtester = ForexBacktester(
        pair="GBPUSD",
        initial_capital=10000.0,
        risk_per_trade_pct=1.0,
        spread_pips=1.0,
        pip_decimal=4
    )
    optimizer = GridOptimizer(backtester=backtester, train_test_split_ratio=0.60)

    df = dm.load_cached_data("GBPUSD", "15m")
    if df is None:
        return

    param_grid = {
        "displacement_min_pips": [8.0, 12.0, 16.0],
        "gap_min_pips": [3.0, 5.0, 8.0],
        "max_retrace_bars": [10, 15, 20],
        "rr_ratio": [1.5, 2.0, 2.5]
    }

    res_df = optimizer.run_grid(
        strategy_func=strat.generate_signals,
        df=df,
        param_grid=param_grid,
        strategy_name="Strat3_FairValueGap"
    )

    if not res_df.empty:
        print("\nTop 5 Parameter Sets for Strategy 3:")
        print(res_df.head(5)[["displacement_min_pips", "gap_min_pips", "max_retrace_bars", "rr_ratio", "Train_PF", "Test_PF", "Test_WinRate", "Test_Sharpe"]].to_string())


def run_strategy_4_experiments(dm: ForexDataManager):
    print("\n" + "="*70)
    print(">>> RUNNING STRATEGY 4: Mandelbrot Volatility Contraction & Expansion <<<")
    print("="*70)

    strat = MandelbrotVolatilityExpansionStrategy(pip_decimal=4)
    backtester = ForexBacktester(
        pair="GBPJPY",
        initial_capital=10000.0,
        risk_per_trade_pct=1.0,
        spread_pips=1.6,
        pip_decimal=2
    )
    optimizer = GridOptimizer(backtester=backtester, train_test_split_ratio=0.60)

    df = dm.load_cached_data("GBPJPY", "15m")
    if df is None:
        return

    param_grid = {
        "compression_lookback_bars": [16, 24, 32],
        "quantile_threshold": [0.15, 0.20, 0.25],
        "buffer_pips": [5.0, 10.0, 15.0, 20.0, 25.0],
        "rr_ratio": [2.0, 2.5, 3.0]
    }

    res_df = optimizer.run_grid(
        strategy_func=strat.generate_signals,
        df=df,
        param_grid=param_grid,
        strategy_name="Strat4_MandelbrotExpansion"
    )

    if not res_df.empty:
        print("\nTop 5 Parameter Sets for Strategy 4:")
        print(res_df.head(5)[["compression_lookback_bars", "quantile_threshold", "buffer_pips", "rr_ratio", "Train_PF", "Test_PF", "Test_WinRate", "Test_Sharpe"]].to_string())


def run_strategy_5_experiments(dm: ForexDataManager):
    print("\n" + "="*70)
    print(">>> RUNNING STRATEGY 5: Cross-Pair Microstructure SMT Divergence <<<")
    print("="*70)

    strat = CrossPairSMTDivergenceStrategy(pip_decimal=4)
    backtester = ForexBacktester(
        pair="EURUSD",
        initial_capital=10000.0,
        risk_per_trade_pct=1.0,
        spread_pips=0.7,
        pip_decimal=4
    )
    optimizer = GridOptimizer(backtester=backtester, train_test_split_ratio=0.60)

    df_eur = dm.load_cached_data("EURUSD", "15m")
    df_gbp = dm.load_cached_data("GBPUSD", "15m")
    if df_eur is None or df_gbp is None:
        return

    param_grid = {
        "swing_window": [15, 25, 35],
        "buffer_pips": [3.0, 5.0, 8.0, 12.0],
        "rr_ratio": [1.5, 2.0, 2.5]
    }

    res_df = optimizer.run_grid(
        strategy_func=strat.generate_signals,
        df=df_eur,
        secondary_df=df_gbp,
        param_grid=param_grid,
        strategy_name="Strat5_CrossPairSMT"
    )

    if not res_df.empty:
        print("\nTop 5 Parameter Sets for Strategy 5:")
        print(res_df.head(5)[["swing_window", "buffer_pips", "rr_ratio", "Train_PF", "Test_PF", "Test_WinRate", "Test_Sharpe"]].to_string())


if __name__ == "__main__":
    dm = ForexDataManager()
    
    print("\n" + "="*70)
    print("STARTING FULL QUANT EXPERIMENTATION SUITE")
    print("ZERO INDICATORS | 10 FOREX PAIRS | STRICT NO-LOOKAHEAD BIAS")
    print("="*70)
    
    run_strategy_1_experiments(dm)
    run_strategy_2_experiments(dm)
    run_strategy_3_experiments(dm)
    run_strategy_4_experiments(dm)
    run_strategy_5_experiments(dm)
    print("\nALL EXPERIMENTS COMPLETED!")
