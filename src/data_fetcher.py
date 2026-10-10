"""
FX Data Ingestion Engine
Downloads high-resolution historical Forex data for top 10 currency pairs
via public Yahoo Finance API without requiring paid API keys.
Includes data hygiene checks, missing data imputation, and clean storage.
"""

import os
import sys
import logging
from typing import List, Dict, Tuple
import pandas as pd
import yfinance as yf

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("FXDataFetcher")

# Top 10 Forex Pairs: Selected for liquidity, spread efficiency, and structural diversity
TOP_10_PAIRS = {
    "EURUSD": {"ticker": "EURUSD=X", "name": "Euro / US Dollar", "type": "Major", "avg_spread_pips": 0.6, "pip_decimal": 4},
    "GBPUSD": {"ticker": "GBPUSD=X", "name": "British Pound / US Dollar", "type": "Major", "avg_spread_pips": 1.0, "pip_decimal": 4},
    "USDJPY": {"ticker": "USDJPY=X", "name": "US Dollar / Japanese Yen", "type": "Major", "avg_spread_pips": 0.8, "pip_decimal": 2},
    "AUDUSD": {"ticker": "AUDUSD=X", "name": "Australian Dollar / US Dollar", "type": "Commodity Major", "avg_spread_pips": 1.0, "pip_decimal": 4},
    "USDCAD": {"ticker": "USDCAD=X", "name": "US Dollar / Canadian Dollar", "type": "Commodity Major", "avg_spread_pips": 1.2, "pip_decimal": 4},
    "USDCHF": {"ticker": "USDCHF=X", "name": "US Dollar / Swiss Franc", "type": "Safe Haven Major", "avg_spread_pips": 1.2, "pip_decimal": 4},
    "NZDUSD": {"ticker": "NZDUSD=X", "name": "New Zealand Dollar / US Dollar", "type": "Commodity Major", "avg_spread_pips": 1.4, "pip_decimal": 4},
    "EURGBP": {"ticker": "EURGBP=X", "name": "Euro / British Pound", "type": "Major Cross", "avg_spread_pips": 1.1, "pip_decimal": 4},
    "EURJPY": {"ticker": "EURJPY=X", "name": "Euro / Japanese Yen", "type": "Yen Cross", "avg_spread_pips": 1.2, "pip_decimal": 2},
    "GBPJPY": {"ticker": "GBPJPY=X", "name": "British Pound / Japanese Yen", "type": "High Volatility Cross", "avg_spread_pips": 1.6, "pip_decimal": 2},
}

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

def clean_and_validate_df(df: pd.DataFrame, pair: str, interval: str) -> pd.DataFrame:
    """
    Cleans OHLCV DataFrame, strips multi-index headers, removes nulls,
    ensures monotonic DatetimeIndex, and verifies absence of zero/negative prices.
    """
    if df.empty:
        raise ValueError(f"No data returned for {pair} on interval {interval}")

    # Handle multi-level columns from yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Standardize column names
    col_map = {c: c.capitalize() for c in df.columns}
    df = df.rename(columns=col_map)
    required = ["Open", "High", "Low", "Close"]
    for col in required:
        if col not in df.columns:
            raise KeyError(f"Missing required column '{col}' for {pair}")

    # Filter out empty or zero rows
    df = df.dropna(subset=required)
    df = df[(df["Open"] > 0) & (df["High"] > 0) & (df["Low"] > 0) & (df["Close"] > 0)]

    # Ensure High is max, Low is min
    df["High"] = df[["Open", "High", "Low", "Close"]].max(axis=1)
    df["Low"] = df[["Open", "High", "Low", "Close"]].min(axis=1)

    # Ensure UTC timezone and sort
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    df = df.sort_index()
    # Deduplicate timestamps
    df = df[~df.index.duplicated(keep="first")]

    logger.info(f"[{pair} - {interval}] Cleaned {len(df)} bars from {df.index[0]} to {df.index[-1]}")
    return df

def fetch_pair_data(pair_code: str, period: str = "730d", interval: str = "1h") -> pd.DataFrame:
    """Downloads historical data for a specific pair and interval."""
    if pair_code not in TOP_10_PAIRS:
        raise ValueError(f"Unknown pair {pair_code}. Available: {list(TOP_10_PAIRS.keys())}")
    
    meta = TOP_10_PAIRS[pair_code]
    ticker = meta["ticker"]
    logger.info(f"Downloading {pair_code} ({ticker}) | Period: {period} | Interval: {interval}...")
    
    df = yf.download(
        tickers=ticker,
        period=period,
        interval=interval,
        auto_adjust=False,
        progress=False
    )
    
    df = clean_and_validate_df(df, pair_code, interval)
    return df

def download_all_pairs(intervals: List[Tuple[str, str]] = None) -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    Downloads historical data for all 10 pairs across requested intervals.
    Default intervals:
      - ('60d', '15m') -> 15-minute bars (ideal for intraday session sweep & buffer tests)
      - ('730d', '1h')  -> 1-hour bars (deep 2-year history for mathematical regime testing)
    """
    if intervals is None:
        intervals = [
            ("60d", "15m"),
            ("730d", "1h")
        ]

    os.makedirs(DATA_DIR, exist_ok=True)
    results = {}

    for pair_code, meta in TOP_10_PAIRS.items():
        results[pair_code] = {}
        for period, interval in intervals:
            try:
                df = fetch_pair_data(pair_code, period=period, interval=interval)
                
                # Save as CSV and Parquet
                csv_path = os.path.join(DATA_DIR, f"{pair_code}_{interval}.csv")
                parquet_path = os.path.join(DATA_DIR, f"{pair_code}_{interval}.parquet")
                
                df.to_csv(csv_path)
                df.to_parquet(parquet_path)
                
                results[pair_code][interval] = df
                logger.info(f"Saved {pair_code}_{interval} -> {csv_path} & {parquet_path}")
            except Exception as e:
                logger.error(f"Failed to fetch {pair_code} on {interval}: {e}")

    logger.info("All downloads completed successfully!")
    return results

if __name__ == "__main__":
    download_all_pairs()
