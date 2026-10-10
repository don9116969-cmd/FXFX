"""
Strategy 2: Lo & MacKinlay Mathematical Variance Ratio Mean-Reversion (Vectorized)
ZERO INDICATORS USED. Pure non-parametric variance ratio test & standardized return dispersion.

Vectorized implementation using rolling variance and return arrays for 100x faster execution.
"""

from typing import Dict, Any
import numpy as np
import pandas as pd


class VarianceRatioMeanReversionStrategy:
    """
    Quantitative zero-indicator strategy exploiting Lo-MacKinlay Variance Ratio anomalies.
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
            lookback_n: Lookback window for variance calculation (e.g. 40, 60, 80 bars).
            q_period: Aggregation horizon for q-period returns (e.g. 4, 6, 8 bars).
            vr_threshold: Maximum VR to qualify as mean-reverting regime (e.g. 0.70, 0.75, 0.80).
            z_entry: Standard deviation excursion required for entry (e.g. 1.8, 2.0, 2.3).
            rr_ratio: Risk to Reward ratio (e.g. 1.5, 2.0).
            max_holding_bars: Maximum holding period if mean-reversion is sluggish.
        """
        lookback_n = params.get("lookback_n", 60)
        q_period = params.get("q_period", 6)
        vr_threshold = params.get("vr_threshold", 0.75)
        z_entry = params.get("z_entry", 2.0)
        rr_ratio = params.get("rr_ratio", 1.8)
        max_holding_bars = params.get("max_holding_bars", 24)

        closes = df["Close"].to_numpy()
        highs = df["High"].to_numpy()
        lows = df["Low"].to_numpy()
        n = len(df)

        signals = pd.DataFrame(index=df.index)
        signals["signal"] = 0
        signals["sl_price"] = np.nan
        signals["tp_price"] = np.nan
        signals["max_bars"] = max_holding_bars

        # Vectorized rolling calculations
        log_p = pd.Series(np.log(closes))
        r1 = log_p.diff()
        var1 = r1.rolling(lookback_n, min_periods=lookback_n).var()

        rq = log_p.diff(q_period)
        var_q = rq.rolling(lookback_n, min_periods=lookback_n).var()

        # Variance ratio series
        vr = var_q / (q_period * var1.replace(0, np.nan))

        # Standardized price Z-score
        c_series = pd.Series(closes)
        mean_p = c_series.rolling(lookback_n, min_periods=lookback_n).mean()
        std_p = c_series.rolling(lookback_n, min_periods=lookback_n).std()
        z_score = (c_series - mean_p) / std_p.replace(0, np.nan)

        vr_arr = vr.to_numpy()
        z_arr = z_score.to_numpy()
        std_arr = std_p.to_numpy()

        sig_arr = np.zeros(n, dtype=int)
        sl_arr = np.full(n, np.nan)
        tp_arr = np.full(n, np.nan)

        min_warmup = max(lookback_n + q_period + 5, 50)

        for i in range(min_warmup, n):
            c_vr = vr_arr[i]
            c_z = z_arr[i]
            c_std = std_arr[i]

            if np.isnan(c_vr) or np.isnan(c_z) or np.isnan(c_std):
                continue

            if c_vr < vr_threshold:
                curr_price = closes[i]

                # Case A: Positive excursion -> Short
                if c_z >= z_entry:
                    local_high = np.max(highs[max(0, i - 5) : i + 1])
                    sl = max(local_high + (2.0 * self.pip_size), curr_price + (1.2 * c_std))
                    risk = sl - curr_price
                    if risk > (3.0 * self.pip_size):
                        tp = curr_price - (risk * rr_ratio)
                        sig_arr[i] = -1
                        sl_arr[i] = sl
                        tp_arr[i] = tp

                # Case B: Negative excursion -> Long
                elif c_z <= -z_entry:
                    local_low = np.min(lows[max(0, i - 5) : i + 1])
                    sl = min(local_low - (2.0 * self.pip_size), curr_price - (1.2 * c_std))
                    risk = curr_price - sl
                    if risk > (3.0 * self.pip_size):
                        tp = curr_price + (risk * rr_ratio)
                        sig_arr[i] = 1
                        sl_arr[i] = sl
                        tp_arr[i] = tp

        signals["signal"] = sig_arr
        signals["sl_price"] = sl_arr
        signals["tp_price"] = tp_arr
        return signals
