"""
Quantitative Performance Metrics Module
Calculates risk-adjusted performance metrics, drawdowns, and trade statistics.
"""

from typing import List, Dict, Any
import numpy as np
import pandas as pd


def calculate_performance_metrics(
    trades: List[Dict[str, Any]],
    equity_curve: pd.Series,
    initial_capital: float = 10000.0,
    risk_free_rate: float = 0.04
) -> Dict[str, Any]:
    """
    Computes comprehensive trading metrics.
    
    Args:
        trades: List of completed trade dictionaries.
        equity_curve: Datetime-indexed Series of account equity values.
        initial_capital: Starting balance.
        risk_free_rate: Annualized risk-free rate (e.g. 0.04 for 4%).
    
    Returns:
        Dict of quantitative performance metrics.
    """
    if not trades or equity_curve.empty or len(equity_curve) < 2:
        return {
            "Total Trades": 0,
            "Win Rate (%)": 0.0,
            "Profit Factor": 0.0,
            "Net Profit ($)": 0.0,
            "Return (%)": 0.0,
            "Max Drawdown (%)": 0.0,
            "Sharpe Ratio": 0.0,
            "Sortino Ratio": 0.0,
            "Expectancy ($)": 0.0,
            "Avg Win ($)": 0.0,
            "Avg Loss ($)": 0.0,
            "Win / Loss Ratio": 0.0,
            "Max Consecutive Losses": 0,
        }

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    
    total_trades = len(trades)
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / total_trades) * 100 if total_trades > 0 else 0.0
    
    total_gross_profit = sum(wins) if wins else 0.0
    total_gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = (total_gross_profit / total_gross_loss) if total_gross_loss > 0 else (999.0 if total_gross_profit > 0 else 0.0)
    
    net_profit = sum(pnls)
    final_equity = equity_curve.iloc[-1]
    total_return_pct = ((final_equity - initial_capital) / initial_capital) * 100
    
    # Drawdown series
    running_max = equity_curve.cummax()
    drawdown_series = (equity_curve - running_max) / running_max
    max_drawdown_pct = abs(drawdown_series.min()) * 100 if not drawdown_series.empty else 0.0

    # Daily or periodic returns for Sharpe & Sortino
    resampled_equity = equity_curve.resample("1D").last().ffill().dropna()
    if len(resampled_equity) > 2:
        daily_returns = resampled_equity.pct_change().dropna()
        trading_days = 252
        rf_daily = risk_free_rate / trading_days
        excess_returns = daily_returns - rf_daily
        
        std_dev = daily_returns.std()
        if std_dev > 1e-8:
            sharpe_ratio = (excess_returns.mean() / std_dev) * np.sqrt(trading_days)
        else:
            sharpe_ratio = 0.0
            
        downside_returns = daily_returns[daily_returns < 0]
        downside_std = downside_returns.std()
        if downside_std > 1e-8:
            sortino_ratio = (excess_returns.mean() / downside_std) * np.sqrt(trading_days)
        else:
            sortino_ratio = 0.0
    else:
        sharpe_ratio = 0.0
        sortino_ratio = 0.0

    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = abs(np.mean(losses)) if losses else 0.0
    win_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    
    # Mathematical Expectancy = (Win_Prob * Avg_Win) - (Loss_Prob * Avg_Loss)
    win_prob = win_count / total_trades if total_trades > 0 else 0.0
    loss_prob = loss_count / total_trades if total_trades > 0 else 0.0
    expectancy = (win_prob * avg_win) - (loss_prob * avg_loss)
    
    # Consecutive losses
    max_consecutive_losses = 0
    current_consecutive_losses = 0
    for p in pnls:
        if p < 0:
            current_consecutive_losses += 1
            if current_consecutive_losses > max_consecutive_losses:
                max_consecutive_losses = current_consecutive_losses
        else:
            current_consecutive_losses = 0

    return {
        "Total Trades": total_trades,
        "Win Rate (%)": round(win_rate, 2),
        "Profit Factor": round(profit_factor, 2),
        "Net Profit ($)": round(net_profit, 2),
        "Return (%)": round(total_return_pct, 2),
        "Max Drawdown (%)": round(max_drawdown_pct, 2),
        "Sharpe Ratio": round(sharpe_ratio, 2),
        "Sortino Ratio": round(sortino_ratio, 2),
        "Expectancy ($)": round(expectancy, 2),
        "Avg Win ($)": round(avg_win, 2),
        "Avg Loss ($)": round(avg_loss, 2),
        "Win / Loss Ratio": round(win_loss_ratio, 2),
        "Max Consecutive Losses": max_consecutive_losses,
    }
