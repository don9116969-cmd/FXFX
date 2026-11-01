"""
Institutional Forex Backtester Engine
Guarantees ZERO lookahead bias:
  - Signals evaluated at bar t close strictly use past info [0:t].
  - Execution occurs at bar t+1 OPEN.
  - Conservative intrabar resolution: If both SL and TP are touched in the same bar,
    SL is triggered first to prevent optimistic bias.
  - Realistic Forex spread deduction and pip calculation per currency pair.
"""

from typing import Dict, List, Any, Optional
import numpy as np
import pandas as pd
from src.metrics import calculate_performance_metrics


class ForexBacktester:
    """
    Event-driven bar-by-bar Forex backtester with realistic friction models.
    """

    def __init__(
        self,
        pair: str = "EURUSD",
        initial_capital: float = 10000.0,
        risk_per_trade_pct: float = 1.0,  # 1% equity risk per trade
        fixed_risk_usd: Optional[float] = None,
        spread_pips: float = 0.8,
        slippage_pips: float = 0.2,
        pip_decimal: int = 4,
        quote_conv_rate: Optional[float] = None
    ):
        self.pair = pair
        self.initial_capital = initial_capital
        self.risk_per_trade_pct = risk_per_trade_pct
        self.fixed_risk_usd = fixed_risk_usd
        self.spread_pips = spread_pips
        self.slippage_pips = slippage_pips
        self.pip_decimal = pip_decimal
        self.pip_size = 10 ** (-pip_decimal)

        if quote_conv_rate is not None:
            self.quote_conv_rate = quote_conv_rate
        elif "JPY" in pair:
            self.quote_conv_rate = 155.0
        elif "CAD" in pair:
            self.quote_conv_rate = 1.38
        else:
            self.quote_conv_rate = 1.0

    def run(
        self,
        df: pd.DataFrame,
        signals: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Executes backtest over historical price series.
        
        Args:
            df: Historical OHLCV DataFrame (UTC indexed).
            signals: DataFrame with columns:
                     - 'signal': 1 (Buy), -1 (Sell), 0 (Hold)
                     - 'sl_price': Proposed Stop Loss price
                     - 'tp_price': Proposed Take Profit price
                     - 'max_bars': (optional) Maximum holding period in bars
        
        Returns:
            Dict containing trade logs, equity curve, and performance metrics.
        """
        # Ensure timestamp alignment
        common_idx = df.index.intersection(signals.index)
        if len(common_idx) < 10:
            raise ValueError(f"Insufficient overlapping bars between data ({len(df)}) and signals ({len(signals)})")

        df = df.loc[common_idx]
        signals = signals.loc[common_idx]

        opens = df["Open"].to_numpy()
        highs = df["High"].to_numpy()
        lows = df["Low"].to_numpy()
        closes = df["Close"].to_numpy()
        timestamps = df.index

        sig_arr = signals["signal"].to_numpy()
        sl_arr = signals["sl_price"].to_numpy() if "sl_price" in signals else np.full(len(df), np.nan)
        tp_arr = signals["tp_price"].to_numpy() if "tp_price" in signals else np.full(len(df), np.nan)
        max_bars_arr = signals["max_bars"].to_numpy() if "max_bars" in signals else np.full(len(df), np.nan)

        total_friction = (self.spread_pips + self.slippage_pips) * self.pip_size

        equity = self.initial_capital
        equity_records = [equity] * len(df)
        trades: List[Dict[str, Any]] = []

        active_trade: Optional[Dict[str, Any]] = None

        n_bars = len(df)

        for i in range(n_bars - 1):
            curr_bar_time = timestamps[i]
            next_bar_time = timestamps[i + 1]

            # 1. Manage Active Trade on Bar i
            if active_trade is not None:
                side = active_trade["side"]
                sl = active_trade["sl"]
                tp = active_trade["tp"]
                entry_price = active_trade["entry_price"]
                units = active_trade["units"]
                bars_held = i - active_trade["entry_bar_idx"]

                h = highs[i]
                l = lows[i]
                o = opens[i]
                c = closes[i]

                exit_price = None
                exit_reason = None

                if side == 1:  # Long
                    sl_hit = l <= sl
                    tp_hit = h >= tp if tp is not None else False

                    # Conservative: if both hit in the same bar, assume SL hit first
                    if sl_hit and tp_hit:
                        exit_price = min(o, sl)
                        exit_reason = "SL"
                    elif sl_hit:
                        exit_price = min(o, sl)
                        exit_reason = "SL"
                    elif tp_hit:
                        exit_price = max(o, tp)
                        exit_reason = "TP"
                    elif active_trade.get("max_bars") and bars_held >= active_trade["max_bars"]:
                        exit_price = c
                        exit_reason = "TIMEOUT"

                    if exit_price is not None:
                        # Account for exit spread/slippage
                        actual_exit = exit_price - (total_friction / 2.0)
                        raw_pnl = (actual_exit - entry_price) * units
                        pnl = raw_pnl / self.quote_conv_rate
                        equity += pnl

                        active_trade.update({
                            "exit_time": curr_bar_time,
                            "exit_price": round(actual_exit, 5),
                            "pnl": round(pnl, 2),
                            "exit_reason": exit_reason,
                            "bars_held": bars_held
                        })
                        trades.append(active_trade)
                        active_trade = None

                elif side == -1:  # Short
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
                    elif active_trade.get("max_bars") and bars_held >= active_trade["max_bars"]:
                        exit_price = c
                        exit_reason = "TIMEOUT"

                    if exit_price is not None:
                        # Account for exit spread/slippage
                        actual_exit = exit_price + (total_friction / 2.0)
                        raw_pnl = (entry_price - actual_exit) * units
                        pnl = raw_pnl / self.quote_conv_rate
                        equity += pnl

                        active_trade.update({
                            "exit_time": curr_bar_time,
                            "exit_price": round(actual_exit, 5),
                            "pnl": round(pnl, 2),
                            "exit_reason": exit_reason,
                            "bars_held": bars_held
                        })
                        trades.append(active_trade)
                        active_trade = None

            # 2. Process Entry Signals from Bar i -> Execute at Bar i+1 OPEN
            # Strictly NO lookahead: signal generated using closed bar i prices
            if active_trade is None and i < n_bars - 1:
                sig = sig_arr[i]
                if sig in (1, -1):
                    proposed_sl = sl_arr[i]
                    proposed_tp = tp_arr[i] if not np.isnan(tp_arr[i]) else None
                    max_b = max_bars_arr[i] if not np.isnan(max_bars_arr[i]) else None

                    # Execution at Bar i+1 Open
                    next_open = opens[i + 1]

                    if sig == 1:
                        entry_price = next_open + (total_friction / 2.0)
                        if not np.isnan(proposed_sl) and proposed_sl < entry_price:
                            sl_dist = entry_price - proposed_sl
                            friction_buffer = total_friction / 2.0
                            effective_sl_dist = sl_dist + friction_buffer
                            risk_usd = self.fixed_risk_usd if self.fixed_risk_usd else equity * (self.risk_per_trade_pct / 100.0)
                            risk_in_quote = risk_usd * self.quote_conv_rate
                            units = risk_in_quote / effective_sl_dist if effective_sl_dist > 0 else 0
                            
                            active_trade = {
                                "pair": self.pair,
                                "side": 1,
                                "entry_time": next_bar_time,
                                "entry_bar_idx": i + 1,
                                "entry_price": round(entry_price, 5),
                                "sl": proposed_sl,
                                "tp": proposed_tp,
                                "units": units,
                                "max_bars": max_b
                            }
                    elif sig == -1:
                        entry_price = next_open - (total_friction / 2.0)
                        if not np.isnan(proposed_sl) and proposed_sl > entry_price:
                            sl_dist = proposed_sl - entry_price
                            friction_buffer = total_friction / 2.0
                            effective_sl_dist = sl_dist + friction_buffer
                            risk_usd = self.fixed_risk_usd if self.fixed_risk_usd else equity * (self.risk_per_trade_pct / 100.0)
                            risk_in_quote = risk_usd * self.quote_conv_rate
                            units = risk_in_quote / effective_sl_dist if effective_sl_dist > 0 else 0

                            active_trade = {
                                "pair": self.pair,
                                "side": -1,
                                "entry_time": next_bar_time,
                                "entry_bar_idx": i + 1,
                                "entry_price": round(entry_price, 5),
                                "sl": proposed_sl,
                                "tp": proposed_tp,
                                "units": units,
                                "max_bars": max_b
                            }

            equity_records[i] = equity

        equity_records[-1] = equity
        equity_series = pd.Series(equity_records, index=timestamps, name="Equity")

        metrics = calculate_performance_metrics(
            trades=trades,
            equity_curve=equity_series,
            initial_capital=self.initial_capital
        )

        return {
            "metrics": metrics,
            "trades": trades,
            "equity_curve": equity_series
        }
