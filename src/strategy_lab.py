"""
Forex Strategy Research Laboratory (Vectorized)
High-speed automated discovery engine for high-alpha zero-indicator FX models.
"""

import sys
import os
from typing import Dict, List, Any
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_manager import ForexDataManager
from src.backtester import ForexBacktester
from src.metrics import calculate_performance_metrics


class StrategyLaboratory:
    """
    Automated discovery engine for high-alpha zero-indicator FX models.
    """

    def __init__(self):
        self.dm = ForexDataManager()

    # =========================================================================
    # CANDIDATE MODEL A: Institutional Turtle Soup / Liquidity Wick Rejection
    # =========================================================================
    @staticmethod
    def strategy_turtle_soup_liquidity(
        df: pd.DataFrame,
        params: Dict[str, Any],
        pip_size: float = 0.0001
    ) -> pd.DataFrame:
        swing_lookback = params.get("swing_lookback", 20)
        buffer_pips = params.get("buffer_pips", 5.0)
        wick_ratio = params.get("wick_ratio", 0.45)
        rr_ratio = params.get("rr_ratio", 2.2)
        max_bars = params.get("max_bars", 28)

        buffer_val = buffer_pips * pip_size

        highs = df["High"].to_numpy()
        lows = df["Low"].to_numpy()
        opens = df["Open"].to_numpy()
        closes = df["Close"].to_numpy()
        n = len(df)

        signals = pd.DataFrame(index=df.index)
        signals["signal"] = 0
        signals["sl_price"] = np.nan
        signals["tp_price"] = np.nan
        signals["max_bars"] = max_bars

        # Pre-calculate rolling extremes vectorially
        h_series = pd.Series(highs)
        l_series = pd.Series(lows)
        prior_highs = h_series.shift(1).rolling(swing_lookback, min_periods=swing_lookback).max().to_numpy()
        prior_lows = l_series.shift(1).rolling(swing_lookback, min_periods=swing_lookback).min().to_numpy()

        c_ranges = highs - lows
        upper_wicks = highs - np.maximum(opens, closes)
        lower_wicks = np.minimum(opens, closes) - lows

        sig_arr = np.zeros(n, dtype=int)
        sl_arr = np.full(n, np.nan)
        tp_arr = np.full(n, np.nan)

        warmup = swing_lookback + 5

        for i in range(warmup, n):
            c_range = c_ranges[i]
            if c_range < (4.0 * pip_size):
                continue

            p_high = prior_highs[i]
            p_low = prior_lows[i]
            if np.isnan(p_high) or np.isnan(p_low):
                continue

            c_h = highs[i]
            c_l = lows[i]
            c_c = closes[i]

            # Bearish Turtle Soup (Sweep prior high + rejection wick)
            if c_h >= (p_high + buffer_val) and c_c < p_high:
                if (upper_wicks[i] / c_range) >= wick_ratio:
                    sl = c_h + (2.0 * pip_size)
                    risk = sl - c_c
                    if risk > (4.0 * pip_size):
                        sig_arr[i] = -1
                        sl_arr[i] = sl
                        tp_arr[i] = c_c - (risk * rr_ratio)

            # Bullish Turtle Soup (Sweep prior low + rejection wick)
            elif c_l <= (p_low - buffer_val) and c_c > p_low:
                if (lower_wicks[i] / c_range) >= wick_ratio:
                    sl = c_l - (2.0 * pip_size)
                    risk = c_c - sl
                    if risk > (4.0 * pip_size):
                        sig_arr[i] = 1
                        sl_arr[i] = sl
                        tp_arr[i] = c_c + (risk * rr_ratio)

        signals["signal"] = sig_arr
        signals["sl_price"] = sl_arr
        signals["tp_price"] = tp_arr
        return signals

    # =========================================================================
    # CANDIDATE MODEL B: London Opening Range Breakout (London ORB)
    # =========================================================================
    @staticmethod
    def strategy_london_orb(
        df: pd.DataFrame,
        params: Dict[str, Any],
        pip_size: float = 0.0001
    ) -> pd.DataFrame:
        buffer_pips = params.get("buffer_pips", 5.0)
        rr_ratio = params.get("rr_ratio", 2.0)
        max_bars = params.get("max_bars", 32)
        sl_at_mid = params.get("sl_at_mid", True)
        asia_min_pips = params.get("asia_min_range_pips", 8.0)
        asia_max_pips = params.get("asia_max_range_pips", 65.0)

        buffer_val = buffer_pips * pip_size

        signals = pd.DataFrame(index=df.index)
        signals["signal"] = 0
        signals["sl_price"] = np.nan
        signals["tp_price"] = np.nan
        signals["max_bars"] = max_bars

        dates = df.index.date
        hours = df.index.hour
        highs = df["High"].to_numpy()
        lows = df["Low"].to_numpy()
        closes = df["Close"].to_numpy()
        n = len(df)

        sig_arr = np.zeros(n, dtype=int)
        sl_arr = np.full(n, np.nan)
        tp_arr = np.full(n, np.nan)

        day_diff = np.where(dates[1:] != dates[:-1])[0] + 1
        day_starts = np.concatenate(([0], day_diff))
        day_ends = np.concatenate((day_diff, [n]))

        for s, e in zip(day_starts, day_ends):
            if e - s < 10:
                continue
            h_slice = hours[s:e]
            asia_idx = np.where((h_slice >= 0) & (h_slice < 7))[0]
            if len(asia_idx) < 4:
                continue
            asia_h = np.max(highs[s + asia_idx])
            asia_l = np.min(lows[s + asia_idx])
            asia_range = asia_h - asia_l
            if asia_range < (asia_min_pips * pip_size) or asia_range > (asia_max_pips * pip_size):
                continue
            asia_mid = (asia_h + asia_l) / 2.0

            london_idx = np.where((h_slice >= 7) & (h_slice < 11))[0]
            for li in london_idx:
                idx = s + li
                c = closes[idx]
                if c >= (asia_h + buffer_val):
                    sl = asia_mid if sl_at_mid else (asia_h - (4.0 * pip_size))
                    risk = c - sl
                    if risk > (4.0 * pip_size):
                        sig_arr[idx] = 1
                        sl_arr[idx] = sl
                        tp_arr[idx] = c + (risk * rr_ratio)
                        break
                elif c <= (asia_l - buffer_val):
                    sl = asia_mid if sl_at_mid else (asia_l + (4.0 * pip_size))
                    risk = sl - c
                    if risk > (4.0 * pip_size):
                        sig_arr[idx] = -1
                        sl_arr[idx] = sl
                        tp_arr[idx] = c - (risk * rr_ratio)
                        break

        signals["signal"] = sig_arr
        signals["sl_price"] = sl_arr
        signals["tp_price"] = tp_arr
        return signals

    # =========================================================================
    # CANDIDATE MODEL C: Parkinson Volatility Contraction Breakout
    # =========================================================================
    @staticmethod
    def strategy_parkinson_volatility_breakout(
        df: pd.DataFrame,
        params: Dict[str, Any],
        pip_size: float = 0.0001
    ) -> pd.DataFrame:
        vol_window = params.get("vol_window", 24)
        quantile_thresh = params.get("quantile_thresh", 0.15)
        buffer_pips = params.get("buffer_pips", 5.0)
        rr_ratio = params.get("rr_ratio", 2.2)
        max_bars = params.get("max_bars", 36)

        buffer_val = buffer_pips * pip_size

        highs = df["High"].to_numpy()
        lows = df["Low"].to_numpy()
        closes = df["Close"].to_numpy()
        n = len(df)

        signals = pd.DataFrame(index=df.index)
        signals["signal"] = 0
        signals["sl_price"] = np.nan
        signals["tp_price"] = np.nan
        signals["max_bars"] = max_bars

        hl_ratio = np.log(highs / np.maximum(lows, 1e-8))
        factor = 1.0 / (4.0 * np.log(2.0))
        parkinson_raw = factor * (hl_ratio ** 2)
        rolling_parkinson = np.sqrt(pd.Series(parkinson_raw).rolling(vol_window).mean())

        q_history = rolling_parkinson.rolling(vol_window * 3).quantile(quantile_thresh)
        comp_high = pd.Series(highs).rolling(vol_window).max()
        comp_low = pd.Series(lows).rolling(vol_window).min()

        pv_arr = rolling_parkinson.to_numpy()
        q_arr = q_history.to_numpy()
        ch_arr = comp_high.to_numpy()
        cl_arr = comp_low.to_numpy()

        sig_arr = np.zeros(n, dtype=int)
        sl_arr = np.full(n, np.nan)
        tp_arr = np.full(n, np.nan)

        warmup = vol_window * 3 + 5

        for i in range(warmup, n):
            c_pv = pv_arr[i]
            c_q = q_arr[i]

            if np.isnan(c_pv) or np.isnan(c_q):
                continue

            if c_pv <= c_q:
                c_ch = ch_arr[i]
                c_cl = cl_arr[i]
                c_mid = (c_ch + c_cl) / 2.0
                c = closes[i]

                if c >= (c_ch + buffer_val):
                    sl = c_mid
                    risk = c - sl
                    if risk > (4.0 * pip_size):
                        sig_arr[i] = 1
                        sl_arr[i] = sl
                        tp_arr[i] = c + (risk * rr_ratio)

                elif c <= (c_cl - buffer_val):
                    sl = c_mid
                    risk = sl - c
                    if risk > (4.0 * pip_size):
                        sig_arr[i] = -1
                        sl_arr[i] = sl
                        tp_arr[i] = c - (risk * rr_ratio)

        signals["signal"] = sig_arr
        signals["sl_price"] = sl_arr
        signals["tp_price"] = tp_arr
        return signals
