"""
Strategy 3: Structural Fair Value Gap (FVG) / Liquidity Imbalance Fill
ZERO INDICATORS USED. Pure 3-candle geometric order flow imbalance and structural fill.

Core Concept:
When smart money aggressively displaces the market, an imbalance is left where orders
were only filled on one side of the book:
- Bullish FVG: Low of Candle 3 is strictly greater than High of Candle 1.
  The unfilled liquidity zone is [High_1, Low_3].
- Bearish FVG: High of Candle 3 is strictly lower than Low of Candle 1.
  The unfilled liquidity zone is [High_3, Low_1].

Execution:
When price subsequently retraces back into the unmitigated FVG zone within W bars,
a continuation order is entered in the direction of the institutional displacement.
"""

from typing import Dict, Any, List
import numpy as np
import pandas as pd


class FairValueGapStrategy:
    """
    Zero-indicator institutional Fair Value Gap / Liquidity Imbalance strategy.
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
            displacement_min_pips: Minimum body size of Candle 2 to qualify as displacement (e.g. 8, 12, 16 pips).
            gap_min_pips: Minimum open gap size (e.g. 3, 5, 8 pips).
            max_retrace_bars: Maximum bars to wait for retest before FVG expires (e.g. 10, 15, 20).
            rr_ratio: Target Risk to Reward ratio (e.g. 1.5, 2.0, 2.5).
            max_holding_bars: Maximum trade duration.
        """
        displacement_min_pips = params.get("displacement_min_pips", 10.0)
        gap_min_pips = params.get("gap_min_pips", 4.0)
        max_retrace_bars = params.get("max_retrace_bars", 15)
        rr_ratio = params.get("rr_ratio", 2.0)
        max_holding_bars = params.get("max_holding_bars", 30)

        disp_thresh = displacement_min_pips * self.pip_size
        gap_thresh = gap_min_pips * self.pip_size

        opens = df["Open"].to_numpy()
        highs = df["High"].to_numpy()
        lows = df["Low"].to_numpy()
        closes = df["Close"].to_numpy()
        n = len(df)

        signals = pd.DataFrame(index=df.index)
        signals["signal"] = 0
        signals["sl_price"] = np.nan
        signals["tp_price"] = np.nan
        signals["max_bars"] = max_holding_bars

        sig_arr = np.zeros(n, dtype=int)
        sl_arr = np.full(n, np.nan)
        tp_arr = np.full(n, np.nan)

        # Track active unmitigated FVGs: list of dicts
        # Dict: {'type': 'BULL'/'BEAR', 'top': float, 'bottom': float, 'origin_bar': int, 'sl': float}
        active_fvgs: List[Dict[str, Any]] = []

        for i in range(2, n):
            # 1. First, check if current bar triggers a fill on an existing active FVG
            c_bar_high = highs[i]
            c_bar_low = lows[i]
            c_bar_close = closes[i]

            surviving_fvgs = []
            trade_taken = False

            for fvg in active_fvgs:
                # Expire old FVGs
                if (i - fvg["origin_bar"]) > max_retrace_bars or trade_taken:
                    continue

                if fvg["type"] == "BULL":
                    # Retrace down into the gap: Low penetrates into the gap top
                    if c_bar_low <= fvg["top"]:
                        # Gap bottom must not be closed below (invalidation check)
                        if c_bar_close >= fvg["bottom"]:
                            sl = fvg["sl"]
                            risk = c_bar_close - sl
                            if risk > (3.0 * self.pip_size):
                                sig_arr[i] = 1
                                sl_arr[i] = sl
                                tp_arr[i] = c_bar_close + (risk * rr_ratio)
                                trade_taken = True
                                continue  # Consumed
                        # If price plunged straight through bottom, invalidate
                        continue

                elif fvg["type"] == "BEAR":
                    # Retrace up into the gap: High penetrates into gap bottom
                    if c_bar_high >= fvg["bottom"]:
                        if c_bar_close <= fvg["top"]:
                            sl = fvg["sl"]
                            risk = sl - c_bar_close
                            if risk > (3.0 * self.pip_size):
                                sig_arr[i] = -1
                                sl_arr[i] = sl
                                tp_arr[i] = c_bar_close - (risk * rr_ratio)
                                trade_taken = True
                                continue
                        continue

                surviving_fvgs.append(fvg)

            active_fvgs = surviving_fvgs

            # 2. Check for formation of new FVG at bar i (using bars i-2, i-1, i)
            # Candle 1: i-2 | Candle 2: i-1 | Candle 3: i
            c1_high = highs[i - 2]
            c1_low = lows[i - 2]
            c2_open = opens[i - 1]
            c2_close = closes[i - 1]
            c2_high = highs[i - 1]
            c2_low = lows[i - 1]
            c3_high = highs[i]
            c3_low = lows[i]

            # Case A: Bullish FVG
            # Candle 2 is green displacement
            if (c2_close - c2_open) >= disp_thresh:
                # Candle 3 Low is higher than Candle 1 High
                gap_size = c3_low - c1_high
                if gap_size >= gap_thresh:
                    active_fvgs.append({
                        "type": "BULL",
                        "top": c3_low,
                        "bottom": c1_high,
                        "origin_bar": i,
                        "sl": c2_low - (2.0 * self.pip_size)
                    })

            # Case B: Bearish FVG
            # Candle 2 is red displacement
            elif (c2_open - c2_close) >= disp_thresh:
                gap_size = c1_low - c3_high
                if gap_size >= gap_thresh:
                    active_fvgs.append({
                        "type": "BEAR",
                        "top": c1_low,
                        "bottom": c3_high,
                        "origin_bar": i,
                        "sl": c2_high + (2.0 * self.pip_size)
                    })

        signals["signal"] = sig_arr
        signals["sl_price"] = sl_arr
        signals["tp_price"] = tp_arr
        return signals
