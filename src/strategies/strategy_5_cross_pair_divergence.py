"""
Strategy 5: Cross-Pair Microstructure Lead-Lag & Relative Strength Divergence (SMT Divergence)
ZERO INDICATORS USED. Pure multi-asset geometric swing coordinates and liquidity failure.

Microstructure Logic:
Correlated pairs sharing the quote currency (e.g. EUR/USD and GBP/USD) reflect identical
macro USD flows. When one pair sweeps a structural swing high (Higher High) while the
correlated pair fails to confirm (Lower High), institutional divergence is confirmed:
- The breakout was an engineered liquidity hunt.
- Reversal short is initiated on the sweeping asset.

Inverse for Long:
- Primary pair sweeps structural Low (Lower Low).
- Correlated pair holds above prior Low (Higher Low).
- Reversal long is initiated on the primary asset.
"""

from typing import Dict, Any
import numpy as np
import pandas as pd


class CrossPairSMTDivergenceStrategy:
    """
    Zero-indicator cross-asset microstructure divergence strategy.
    """

    def __init__(self, pip_decimal: int = 4):
        self.pip_decimal = pip_decimal
        self.pip_size = 10 ** (-pip_decimal)

    def generate_signals(
        self,
        df_primary: pd.DataFrame,
        df_correlated: pd.DataFrame,
        params: Dict[str, Any]
    ) -> pd.DataFrame:
        """
        Generates trading signals for df_primary by cross-referencing df_correlated.

        Params:
            swing_window: Lookback window to define structural swing high/low (e.g. 15, 25, 40 bars).
            buffer_pips: Sweep penetration buffer required (e.g. 3, 5, 8 pips).
            rr_ratio: Target Risk to Reward ratio (e.g. 1.8, 2.2, 2.5).
            max_holding_bars: Maximum trade duration.
        """
        swing_window = params.get("swing_window", 20)
        buffer_pips = params.get("buffer_pips", 5.0)
        rr_ratio = params.get("rr_ratio", 2.0)
        max_holding_bars = params.get("max_holding_bars", 30)

        buffer_val = buffer_pips * self.pip_size

        # Synchronize timestamps
        common_idx = df_primary.index.intersection(df_correlated.index)
        p_df = df_primary.loc[common_idx]
        c_df = df_correlated.loc[common_idx]

        p_highs = p_df["High"].to_numpy()
        p_lows = p_df["Low"].to_numpy()
        p_closes = p_df["Close"].to_numpy()

        c_highs = c_df["High"].to_numpy()
        c_lows = c_df["Low"].to_numpy()
        n = len(p_df)

        signals = pd.DataFrame(index=common_idx)
        signals["signal"] = 0
        signals["sl_price"] = np.nan
        signals["tp_price"] = np.nan
        signals["max_bars"] = max_holding_bars

        sig_arr = np.zeros(n, dtype=int)
        sl_arr = np.full(n, np.nan)
        tp_arr = np.full(n, np.nan)

        min_warmup = swing_window * 2

        for i in range(min_warmup, n):
            # Prior structural swing extremes: [i - swing_window * 2 : i - 5]
            prior_p_high = np.max(p_highs[i - (swing_window * 2) : i - 3])
            prior_p_low = np.min(p_lows[i - (swing_window * 2) : i - 3])

            prior_c_high = np.max(c_highs[i - (swing_window * 2) : i - 3])
            prior_c_low = np.min(c_lows[i - (swing_window * 2) : i - 3])

            # Current local extremes: [i - 3 : i + 1]
            curr_p_high = np.max(p_highs[i - 2 : i + 1])
            curr_p_low = np.min(p_lows[i - 2 : i + 1])

            curr_c_high = np.max(c_highs[i - 2 : i + 1])
            curr_c_low = np.min(c_lows[i - 2 : i + 1])

            # Case A: Bearish SMT Divergence
            # Primary makes Higher High (swept prior high + buffer)
            # BUT Correlated makes Lower High (fails to sweep)
            if (curr_p_high >= prior_p_high + buffer_val) and (curr_c_high < prior_c_high):
                # Primary candle must show rejection wick (close below sweep high)
                if p_closes[i] < curr_p_high:
                    sl = curr_p_high + (2.0 * self.pip_size)
                    risk = sl - p_closes[i]
                    if risk > (3.0 * self.pip_size):
                        sig_arr[i] = -1
                        sl_arr[i] = sl
                        tp_arr[i] = p_closes[i] - (risk * rr_ratio)

            # Case B: Bullish SMT Divergence
            # Primary makes Lower Low (swept prior low - buffer)
            # BUT Correlated makes Higher Low (fails to break)
            elif (curr_p_low <= prior_p_low - buffer_val) and (curr_c_low > prior_c_low):
                if p_closes[i] > curr_p_low:
                    sl = curr_p_low - (2.0 * self.pip_size)
                    risk = p_closes[i] - sl
                    if risk > (3.0 * self.pip_size):
                        sig_arr[i] = 1
                        sl_arr[i] = sl
                        tp_arr[i] = p_closes[i] + (risk * rr_ratio)

        signals["signal"] = sig_arr
        signals["sl_price"] = sl_arr
        signals["tp_price"] = tp_arr
        return signals
