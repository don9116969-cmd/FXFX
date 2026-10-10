"""
Multi-Year Historical Forex Data Manager
Provides unified access to:
  - Intraday & Hourly datasets cached in parquet
  - Deep 5-10 year archives via HistData M1 downloads resampled to any candle interval (M5, M15, H1, etc.)
"""

import os
import zipfile
import glob
from typing import Dict, Optional
import pandas as pd
from histdata import download_hist_data

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


class ForexDataManager:
    """
    Manages loading, caching, downloading, and resampling of multi-year Forex data.
    """

    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)

    def load_cached_data(self, pair: str, interval: str = "15m") -> Optional[pd.DataFrame]:
        """Loads cached Parquet or CSV dataset."""
        parquet_path = os.path.join(self.data_dir, f"{pair}_{interval}.parquet")
        csv_path = os.path.join(self.data_dir, f"{pair}_{interval}.csv")

        if os.path.exists(parquet_path):
            df = pd.read_parquet(parquet_path)
            return df
        elif os.path.exists(csv_path):
            df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            return df
        return None

    def fetch_multi_year_histdata(
        self,
        pair: str,
        start_year: int = 2020,
        end_year: int = 2024,
        resample_interval: str = "15min"
    ) -> pd.DataFrame:
        """
        Downloads 1-minute historical data for specified years from HistData,
        merges them, resamples into target candle timeframe, and caches to Parquet.
        """
        pair_lower = pair.lower()
        dfs = []

        raw_dir = os.path.join(self.data_dir, "histdata_raw")
        os.makedirs(raw_dir, exist_ok=True)

        for year in range(start_year, end_year + 1):
            year_str = str(year)
            # Check if zip already downloaded
            expected_zip_pattern = os.path.join(raw_dir, f"*{pair_lower.upper()}*{year_str}*.zip")
            matching_zips = glob.glob(expected_zip_pattern)

            zip_file = None
            if matching_zips:
                zip_file = matching_zips[0]
            else:
                try:
                    print(f"Downloading {pair} M1 for year {year}...")
                    zip_file = download_hist_data(
                        year=year_str,
                        month=None,
                        pair=pair_lower,
                        time_frame="M1",
                        platform="ASCII",
                        output_directory=raw_dir
                    )
                except Exception as e:
                    print(f"HistData download error for {pair} {year}: {e}")
                    continue

            if zip_file and os.path.exists(zip_file):
                try:
                    with zipfile.ZipFile(zip_file, "r") as z:
                        for filename in z.namelist():
                            if filename.endswith(".csv"):
                                with z.open(filename) as f:
                                    # Format: YYYYMMDD HHMMSS;Open;High;Low;Close;Vol
                                    ydf = pd.read_csv(f, sep=";", header=None, names=["Datetime", "Open", "High", "Low", "Close", "Volume"])
                                    ydf["Datetime"] = pd.to_datetime(ydf["Datetime"], format="%Y%m%d %H%M%S", utc=True)
                                    ydf = ydf.set_index("Datetime")
                                    dfs.append(ydf)
                except Exception as e:
                    print(f"Error parsing zip {zip_file}: {e}")

        if not dfs:
            raise ValueError(f"Could not load any data for {pair} from {start_year} to {end_year}")

        combined = pd.concat(dfs).sort_index()
        combined = combined[~combined.index.duplicated(keep="first")]

        # Resample to desired timeframe
        resampled = combined.resample(resample_interval).agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum"
        }).dropna()

        # Cache resampled dataframe
        cached_out = os.path.join(self.data_dir, f"{pair}_{resample_interval}_multiyear.parquet")
        resampled.to_parquet(cached_out)
        print(f"Saved {len(resampled)} bars of {resample_interval} data from {resampled.index[0]} to {resampled.index[-1]} -> {cached_out}")
        return resampled
