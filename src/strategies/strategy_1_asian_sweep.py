"""
Strategy 1: Institutional Asian Session Liquidity Sweep (ICT Judas Swing)
ZERO INDICATORS USED. Pure microstructure, session timing, and geometric price action.

Rules:
1. Session Window: Asian range defined between 00:00 and 07:00 UTC.
2. Sweep Window: London open (07:00 to 10:30 UTC).
3. Buy-side Sweep (Short signal): Price pierces Asian High by buffer pips, but fails to
   sustain and closes back inside the range (rejection candle).
4. Sell-side Sweep (Long signal): Price pierces Asian Low by buffer pips, but fails to
   sustain and closes back inside the range (rejection candle).
5. SL: At the extreme sweep wick.
6. TP: Configurable Risk:Reward multiple (e.g. 1.5 to 3.0R) or opposite Asian range boundary.
"""

from typing import Dict, Any
import numpy as np
import pandas as pd


class AsianSessionLiquiditySweepStrategy:
    """
    Zero-indicator Institutional Asian Session Liquidity Sweep strategy.
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
            buffer_pips: Sweep penetration depth required before rejection (e.g. 5, 10, 15, 20, 25).
            rr_ratio: Target Risk to Reward ratio (e.g. 1.5, 2.0, 2.5, 3.0).
            max_holding_bars: Maximum bars to stay in trade before session exit.
            asian_start_hour: Start of Asian accumulation (default: 0).
            asian_end_hour: End of Asian accumulation (default: 7).
            sweep_end_hour: Cutoff for sweep detection (default: 11).
        """
        buffer_pips = params.get("buffer_pips", 10.0)
        rr_ratio = params.get("rr_ratio", 2.0)
        max_holding_bars = params.get("max_holding_bars", 32)
        asian_start_hour = params.get("asian_start_hour", 0)
        asian_end_hour = params.get("asian_end_hour", 7)
        sweep_end_hour = params.get("sweep_end_hour", 11)

        buffer_val = buffer_pips * self.pip_size

        signals = pd.DataFrame(index=df.index)
        signals["signal"] = 0
        signals["sl_price"] = np.nan
        signals["tp_price"] = np.nan
        signals["max_bars"] = max_holding_bars

        # Group data by UTC date
        dates = df.index.date
        unique_dates = np.unique(dates)

        for d in unique_dates:
            day_mask = (dates == d)
            day_df = df[day_mask]
            if len(day_df) < 10:
                continue

            # 1. Calculate Asian Session Range (00:00 - 07:00 UTC)
            asia_mask = (day_df.index.hour >= asian_start_hour) & (day_df.index.hour < asian_end_hour)
            asia_bars = day_df[asia_mask]
            if len(asia_bars) < 4:
                continue

            asia_high = asia_bars["High"].max()
            asia_low = asia_bars["Low"].min()
            asia_range = asia_high - asia_low

            # Filter out abnormal dead sessions (at least 10 pips range)
            if asia_range < (10 * self.pip_size):
                continue

            # 2. Evaluate London Sweep Window (07:00 to 11:00 UTC)
            sweep_mask = (day_df.index.hour >= asian_end_hour) & (day_df.index.hour < sweep_end_hour)
            sweep_bars = day_df[sweep_mask]

            traded_today = False

            for idx, row in sweep_bars.iterrows():
                if traded_today:
                    break

                o = row["Open"]
                h = row["High"]
                l = row["Low"]
                c = row["Close"]

                # Case A: Bearish Liquidity Sweep (Swept High, rejected back inside)
                if h >= (asia_high + buffer_val) and c < asia_high:
                    # Valid institutional rejection
                    sl = h + (2.0 * self.pip_size)  # 2 pip buffer above sweep wick
                    risk = sl - c
                    if risk > (3.0 * self.pip_size):
                        tp = c - (risk * rr_ratio)
                        signals.loc[idx, "signal"] = -1
                        signals.loc[idx, "sl_price"] = sl
                        signals.loc[idx, "tp_price"] = tp
                        traded_today = True

                # Case B: Bullish Liquidity Sweep (Swept Low, rejected back inside)
                elif l <= (asia_low - buffer_val) and c > asia_low:
                    sl = l - (2.0 * self.pip_size)
                    risk = c - sl
                    if risk > (3.0 * self.pip_size):
                        tp = c + (risk * rr_ratio)
                        signals.loc[idx, "signal"] = 1
                        signals.loc[idx, "sl_price"] = sl
                        signals.loc[idx, "tp_price"] = tp
                        traded_today = True

        return signals
