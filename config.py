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

    # Strategy Portfolio Definitions (100% 15-Minute Champion Quantitative Models)
    PORTFOLIO_STRATEGIES: List[Dict[str, Any]] = field(default_factory=lambda: [
        {
            "id": "strat_1_eurusd_orb",
            "name": "Rank 1: London ORB (EURUSD 15m)",
            "pair": "EURUSD",
            "ticker": "EURUSD=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 4,
            "spread_pips": 0.7,
            "type": "ORB",
            "params": {"buffer_pips": 2.0, "rr_ratio": 2.0, "sl_at_mid": False, "max_bars": 36}
        },
        {
            "id": "strat_2_eurjpy_turtle",
            "name": "Rank 2: Turtle Soup Sweep (EURJPY 15m)",
            "pair": "EURJPY",
            "ticker": "EURJPY=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 2,
            "spread_pips": 1.2,
            "type": "TURTLE",
            "params": {"swing_lookback": 30, "buffer_pips": 2.0, "wick_ratio": 0.6, "rr_ratio": 2.0, "max_bars": 36}
        },
        {
            "id": "strat_3_gbpjpy_turtle",
            "name": "Rank 3: Turtle Soup Sweep (GBPJPY 15m)",
            "pair": "GBPJPY",
            "ticker": "GBPJPY=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 2,
            "spread_pips": 1.6,
            "type": "TURTLE",
            "params": {"swing_lookback": 40, "buffer_pips": 2.0, "wick_ratio": 0.5, "rr_ratio": 2.0, "max_bars": 20}
        },
        {
            "id": "strat_4_gbpusd_orb",
            "name": "Rank 4: London ORB (GBPUSD 15m)",
            "pair": "GBPUSD",
            "ticker": "GBPUSD=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 4,
            "spread_pips": 1.0,
            "type": "ORB",
            "params": {"buffer_pips": 5.0, "rr_ratio": 3.0, "sl_at_mid": True, "max_bars": 36}
        },
        {
            "id": "strat_5_audusd_turtle",
            "name": "Rank 5: Turtle Soup Sweep (AUDUSD 15m)",
            "pair": "AUDUSD",
            "ticker": "AUDUSD=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 4,
            "spread_pips": 0.9,
            "type": "TURTLE",
            "params": {"swing_lookback": 12, "buffer_pips": 2.0, "wick_ratio": 0.4, "rr_ratio": 2.5, "max_bars": 20}
        },
        {
            "id": "strat_6_usdcad_turtle",
            "name": "Rank 6: Turtle Soup Sweep (USDCAD 15m)",
            "pair": "USDCAD",
            "ticker": "USDCAD=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 4,
            "spread_pips": 1.1,
            "type": "TURTLE",
            "params": {"swing_lookback": 12, "buffer_pips": 5.0, "wick_ratio": 0.6, "rr_ratio": 2.0, "max_bars": 36}
        },
        {
            "id": "strat_7_audusd_orb",
            "name": "Rank 7: London ORB (AUDUSD 15m)",
            "pair": "AUDUSD",
            "ticker": "AUDUSD=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 4,
            "spread_pips": 0.9,
            "type": "ORB",
            "params": {"buffer_pips": 2.0, "rr_ratio": 1.5, "sl_at_mid": True, "max_bars": 28}
        },
        {
            "id": "strat_8_usdjpy_orb",
            "name": "Rank 8: London ORB (USDJPY 15m)",
            "pair": "USDJPY",
            "ticker": "USDJPY=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 2,
            "spread_pips": 1.0,
            "type": "ORB",
            "params": {"buffer_pips": 12.0, "rr_ratio": 2.0, "sl_at_mid": True, "max_bars": 36}
        }
    ])

config = TradingConfig()
