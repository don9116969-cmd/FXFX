"""
Configuration module for FXFX Institutional Algorithmic Trading Bot.
Centralizes capital controls, risk parameters, session schedules, and strategy definitions.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

@dataclass
class TradingConfig:
    # Directory Paths
    BASE_DIR: str = BASE_DIR
    DATA_DIR: str = DATA_DIR

    # Capital & Portfolio Risk Controls ($10,000 Starting Budget)
    INITIAL_CAPITAL: float = 10000.0   # Account starting balance in USD
    RISK_PER_TRADE_USD: float = 100.0  # Max risk per trade ($100 = 1.0% of portfolio)
    MAX_ACTIVE_TRADES: int = 4         # Maximum simultaneous open positions
    ACCOUNT_CURRENCY: str = "USD"

    # Execution & Frictional Costs (Institutional ECN Spread + Slippage Modeling)
    SLIPPAGE_PIPS: float = 0.2         # 0.2 pips estimated execution slippage
    SPREAD_PIPS: Dict[str, float] = field(default_factory=lambda: {
        "EURUSD": 0.7,
        "GBPUSD": 1.0,
        "EURJPY": 1.2,
        "USDCAD": 1.1,
        "AUDUSD": 0.9,
        "NZDUSD": 1.2,
        "USDCHF": 1.1,
        "GBPJPY": 1.6
    })

    # Pip Decimals (Standard 4 decimals for majors, 2 decimals for JPY pairs)
    PIP_DECIMALS: Dict[str, int] = field(default_factory=lambda: {
        "EURUSD": 4,
        "GBPUSD": 4,
        "EURJPY": 2,
        "USDCAD": 4,
        "AUDUSD": 4,
        "NZDUSD": 4,
        "USDCHF": 4,
        "GBPJPY": 2
    })

    # Market Timing & Session Definitions (UTC)
    ASIAN_SESSION_START: str = "00:00"
    ASIAN_SESSION_END: str = "06:45"
    LONDON_ORB_TRIGGER: str = "07:00"
    LONDON_SESSION_END: str = "15:00"
    NEW_YORK_SESSION_START: str = "13:00"
    NEW_YORK_SESSION_END: str = "21:00"

    # File Paths
    STATE_FILE: str = os.path.join(DATA_DIR, "live_portfolio_state.json")
    JOURNAL_CSV_FILE: str = os.path.join(DATA_DIR, "trade_journal.csv")
    JOURNAL_MD_FILE: str = os.path.join(DATA_DIR, "trade_journal.md")
    SENT_ALERTS_FILE: str = os.path.join(DATA_DIR, "sent_alerts.json")
    OFFSET_FILE: str = os.path.join(DATA_DIR, "telegram_offset.txt")

    # Strategy Portfolio Definitions (The 8 Out-Of-Sample Quant Models)
    PORTFOLIO_STRATEGIES: List[Dict[str, Any]] = field(default_factory=lambda: [
        {
            "id": "strat_1_eurjpy_orb",
            "name": "Rank 1: London ORB (EURJPY 15m)",
            "pair": "EURJPY",
            "ticker": "EURJPY=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 2,
            "spread_pips": 1.2,
            "type": "ORB",
            "params": {"buffer_pips": 15.0, "rr_ratio": 1.5, "sl_at_mid": True, "max_bars": 32}
        },
        {
            "id": "strat_2_gbpusd_orb",
            "name": "Rank 2: London ORB (GBPUSD 15m)",
            "pair": "GBPUSD",
            "ticker": "GBPUSD=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 4,
            "spread_pips": 1.0,
            "type": "ORB",
            "params": {"buffer_pips": 12.0, "rr_ratio": 2.0, "sl_at_mid": True, "max_bars": 32}
        },
        {
            "id": "strat_3_usdcad_turtle",
            "name": "Rank 3: Turtle Soup Sweep (USDCAD 15m)",
            "pair": "USDCAD",
            "ticker": "USDCAD=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 4,
            "spread_pips": 1.1,
            "type": "TURTLE",
            "params": {"swing_lookback": 15, "buffer_pips": 5.0, "wick_ratio": 0.4, "rr_ratio": 2.0, "max_bars": 28}
        },
        {
            "id": "strat_4_eurusd_orb",
            "name": "Rank 4: London ORB (EURUSD 15m)",
            "pair": "EURUSD",
            "ticker": "EURUSD=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 4,
            "spread_pips": 0.7,
            "type": "ORB",
            "params": {"buffer_pips": 5.0, "rr_ratio": 1.5, "sl_at_mid": False, "max_bars": 32}
        },
        {
            "id": "strat_5_eurjpy_turtle",
            "name": "Rank 5: Turtle Soup Sweep (EURJPY 15m)",
            "pair": "EURJPY",
            "ticker": "EURJPY=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 2,
            "spread_pips": 1.2,
            "type": "TURTLE",
            "params": {"swing_lookback": 40, "buffer_pips": 5.0, "wick_ratio": 0.6, "rr_ratio": 2.0, "max_bars": 28}
        },
        {
            "id": "strat_6_eurusd_orb_tight",
            "name": "Rank 6: London ORB Tight (EURUSD 15m)",
            "pair": "EURUSD",
            "ticker": "EURUSD=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 4,
            "spread_pips": 0.7,
            "type": "ORB",
            "params": {"buffer_pips": 3.0, "rr_ratio": 1.5, "sl_at_mid": False, "max_bars": 32}
        },
        {
            "id": "strat_7_usdcad_turtle_tight",
            "name": "Rank 7: Turtle Soup Tight (USDCAD 15m)",
            "pair": "USDCAD",
            "ticker": "USDCAD=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 4,
            "spread_pips": 1.1,
            "type": "TURTLE",
            "params": {"swing_lookback": 25, "buffer_pips": 3.0, "wick_ratio": 0.6, "rr_ratio": 2.0, "max_bars": 28}
        },
        {
            "id": "strat_8_eurusd_variance_ratio",
            "name": "Rank 8: Variance Ratio MR (EURUSD 1h)",
            "pair": "EURUSD",
            "ticker": "EURUSD=X",
            "timeframe": "1h",
            "period": "60d",
            "dec": 4,
            "spread_pips": 0.7,
            "type": "VARIANCE_RATIO",
            "params": {"lookback_n": 40, "q_period": 4, "vr_threshold": 0.80, "z_entry": 2.3, "rr_ratio": 2.0, "max_holding_bars": 24}
        }
    ])

config = TradingConfig()
