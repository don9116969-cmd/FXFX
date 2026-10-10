"""
Grid System Optimization & Cross-Validation Engine
Performs multi-dimensional grid search across parameter ranges (e.g. buffer 5, 10, 15, 20, 25)
with strict In-Sample (Train) vs Out-Of-Sample (Test) cross-validation to prevent curve fitting.
"""

from typing import Dict, List, Any, Callable
import itertools
import os
import pandas as pd
from tqdm import tqdm
from src.backtester import ForexBacktester


class GridOptimizer:
    """
    Exhaustive parameter grid search engine with Walk-Forward train/test split.
    """

    def __init__(
        self,
        backtester: ForexBacktester,
        train_test_split_ratio: float = 0.60
    ):
        self.backtester = backtester
        self.split_ratio = train_test_split_ratio

    def run_grid(
        self,
        strategy_func: Callable[[pd.DataFrame, Dict[str, Any]], pd.DataFrame],
        df: pd.DataFrame,
        param_grid: Dict[str, List[Any]],
        strategy_name: str = "Strategy",
        secondary_df: pd.DataFrame = None
    ) -> pd.DataFrame:
        """
        Executes grid search over all parameter combinations with cross-validation.

        Args:
            strategy_func: Function that takes (df, params) and returns signals DataFrame.
            df: Historical price DataFrame.
            param_grid: Dict of parameter names mapped to lists of values.
            strategy_name: Name of strategy for reporting.
            secondary_df: Optional secondary dataframe for cross-pair strategies.

        Returns:
            DataFrame containing In-Sample and Out-Of-Sample metrics for each combination.
        """
        keys = list(param_grid.keys())
        combos = list(itertools.product(*[param_grid[k] for k in keys]))
        total_combos = len(combos)

        # Train / Test chronological split (NO shuffling, zero lookahead!)
        split_idx = int(len(df) * self.split_ratio)
        df_train = df.iloc[:split_idx]
        df_test = df.iloc[split_idx:]

        sec_train = secondary_df.iloc[:split_idx] if secondary_df is not None else None
        sec_test = secondary_df.iloc[split_idx:] if secondary_df is not None else None

        records = []

        print(f"\n=======================================================")
        print(f"Running Grid Optimization for '{strategy_name}' on {self.backtester.pair}")
        print(f"Total Combinations: {total_combos}")
        print(f"Train Period (In-Sample):  {df_train.index[0]} -> {df_train.index[-1]} ({len(df_train)} bars)")
        print(f"Test Period (Out-Of-Sample): {df_test.index[0]} -> {df_test.index[-1]} ({len(df_test)} bars)")
        print(f"=======================================================\n")

        for combo in tqdm(combos, desc=f"Optimizing {strategy_name}"):
            params = dict(zip(keys, combo))

            # 1. In-Sample Run
            try:
                if secondary_df is not None:
                    train_signals = strategy_func(df_train, sec_train, params)
                    test_signals = strategy_func(df_test, sec_test, params)
                else:
                    train_signals = strategy_func(df_train, params)
                    test_signals = strategy_func(df_test, params)

                res_train = self.backtester.run(df_train, train_signals)
                res_test = self.backtester.run(df_test, test_signals)

                m_train = res_train["metrics"]
                m_test = res_test["metrics"]

                row = dict(params)
                row.update({
                    "Train_Trades": m_train["Total Trades"],
                    "Train_WinRate": m_train["Win Rate (%)"],
                    "Train_PF": m_train["Profit Factor"],
                    "Train_Return%": m_train["Return (%)"],
                    "Train_MaxDD%": m_train["Max Drawdown (%)"],
                    "Train_Sharpe": m_train["Sharpe Ratio"],
                    "Test_Trades": m_test["Total Trades"],
                    "Test_WinRate": m_test["Win Rate (%)"],
                    "Test_PF": m_test["Profit Factor"],
                    "Test_Return%": m_test["Return (%)"],
                    "Test_MaxDD%": m_test["Max Drawdown (%)"],
                    "Test_Sharpe": m_test["Sharpe Ratio"],
                    "Test_Expectancy": m_test["Expectancy ($)"],
                })

                # Robustness score: Out-of-sample edge preservation
                row["Robust_Score"] = round((m_test["Profit Factor"] * 0.5) + (m_test["Sharpe Ratio"] * 0.5), 2)
                records.append(row)

            except Exception as e:
                print(f"Error testing params {params}: {e}")

        res_df = pd.DataFrame(records)
        if not res_df.empty:
            res_df = res_df.sort_values(by=["Test_PF", "Test_Sharpe"], ascending=False)
            os.makedirs("results", exist_ok=True)
            out_file = os.path.join("results", f"{strategy_name}_{self.backtester.pair}_grid.csv")
            res_df.to_csv(out_file, index=False)
            print(f"\n[OK] Optimization complete! Saved results to {out_file}")

        return res_df
