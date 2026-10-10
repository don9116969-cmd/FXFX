"""
Strategy 4: Mandelbrot Heavy-Tailed Volatility Contraction & Quantile Expansion Breakout (Vectorized)
ZERO INDICATORS USED. Pure mathematical quantile distribution & Mandelbrot volatility clustering.

Vectorized implementation using rolling quantiles for high-speed parameter grid evaluation.
"""

from typing import Dict, Any
import numpy as np
import pandas as pd


class MandelbrotVolatilityExpansionStrategy:
    """
    Zero-indicator Mandelbrot Volatility Contraction & Quantile Expansion Strategy.
    """

    def __init__(self, pip_decimal: int = 4):
        self.pip_decimal = pip_decimal
        self.pip_size = 10 ** (-pip_decimal)

    def generate_signals(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any]
    ) -> pd.DataFrame:
        """
        Generates trading signals.

        Params:
            compression_lookback_bars: Lookback to evaluate range compression (e.g. 16, 24, 32 bars).
            quantile_threshold: Percentile threshold for compression (e.g. 0.15, 0.20, 0.25).
            buffer_pips: Breakout penetration buffer past the compression boundary (e.g. 5, 10, 15, 20 pips).
            rr_ratio: Target Risk to Reward ratio (e.g. 2.0, 2.5, 3.0).
            max_holding_bars: Maximum trade duration.
        """
        lookback_bars = params.get("compression_lookback_bars", 20)
        quantile_thresh = params.get("quantile_threshold", 0.25)
        buffer_pips = params.get("buffer_pips", 10.0)
        rr_ratio = params.get("rr_ratio", 2.2)
        max_holding_bars = params.get("max_holding_bars", 36)

        buffer_val = buffer_pips * self.pip_size

        highs = df["High"].to_numpy()
        lows = df["Low"].to_numpy()
        closes = df["Close"].to_numpy()
        n = len(df)

        signals = pd.DataFrame(index=df.index)
        signals["signal"] = 0
        signals["sl_price"] = np.nan
        signals["tp_price"] = np.nan
        signals["max_bars"] = max_holding_bars

        # Vectorized rolling calculations
        r_series = pd.Series(highs - lows)
        hist_window = lookback_bars * 3
        q_series = r_series.rolling(hist_window, min_periods=hist_window).quantile(quantile_thresh)
        recent_mean = r_series.rolling(lookback_bars, min_periods=lookback_bars).mean()

        h_series = pd.Series(highs)
        l_series = pd.Series(lows)
        comp_high = h_series.rolling(lookback_bars, min_periods=lookback_bars).max()
        comp_low = l_series.rolling(lookback_bars, min_periods=lookback_bars).min()

        q_arr = q_series.to_numpy()
        mean_arr = recent_mean.to_numpy()
        ch_arr = comp_high.to_numpy()
        cl_arr = comp_low.to_numpy()

        sig_arr = np.zeros(n, dtype=int)
        sl_arr = np.full(n, np.nan)
        tp_arr = np.full(n, np.nan)

        min_warmup = hist_window + 5

        for i in range(min_warmup, n):
            c_q = q_arr[i]
            c_mean = mean_arr[i]
            c_ch = ch_arr[i]
            c_cl = cl_arr[i]

            if np.isnan(c_q) or np.isnan(c_mean):
                continue

            # Is current range compressed below quantile threshold?
            if c_mean <= c_q:
                compress_mid = (c_ch + c_cl) / 2.0
                c_close = closes[i]

                # Case A: Bullish Expansion Breakout
                if c_close >= (c_ch + buffer_val):
                    sl = compress_mid
                    risk = c_close - sl
                    if risk > (4.0 * self.pip_size):
                        sig_arr[i] = 1
                        sl_arr[i] = sl
                        tp_arr[i] = c_close + (risk * rr_ratio)

                # Case B: Bearish Expansion Breakout
                elif c_close <= (c_cl - buffer_val):
                    sl = compress_mid
                    risk = sl - c_close
                    if risk > (4.0 * self.pip_size):
                        sig_arr[i] = -1
                        sl_arr[i] = sl
                        tp_arr[i] = c_close - (risk * rr_ratio)

        signals["signal"] = sig_arr
        signals["sl_price"] = sl_arr
        signals["tp_price"] = tp_arr
        return signals
