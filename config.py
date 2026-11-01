"""
Configuration module for FXFX Institutional Algorithmic Trading Bot.
Centralizes capital controls, risk parameters, session schedules, and strategy definitions.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

@dataclass
class TradingConfig:
    # Directory Paths
    BASE_DIR: str = BASE_DIR
    DATA_DIR: str = DATA_DIR

    # Capital & Portfolio Risk Controls ($20,000 Prop-Firm Account Calibration)
    INITIAL_CAPITAL: float = 20000.0   # Account starting balance in USD ($20,000 standard prop firm account)
    RISK_PER_TRADE_USD: float = 60.0   # Max risk per trade ($60.00 = 0.30% of $20,000 for strict prop firm safety)
    MAX_ACTIVE_TRADES: int = 2         # Maximum simultaneous open positions (keeps 3-yr peak DD strictly at 8.0%)
    ACCOUNT_CURRENCY: str = "USD"

    # Prop-Firm Compliance Controls & Automated Circuit Breakers
    PROP_FIRM_MODE: bool = True
    PROP_FIRM_PROGRAM: str = "The5ers High Stakes / Alpha Capital / FTMO"
    MAX_DAILY_LOSS_PCT: float = 2.5    # Hard safety tripwire: Auto-halts entries if daily loss hits 2.5% (prop limit is 5.0%)
    MAX_OVERALL_DD_PCT: float = 8.0    # Hard safety tripwire: Auto-halts entries if total DD hits 8.0% (prop limit is 10.0%)
    CHALLENGE_TARGET_PCT: float = 8.0  # Phase 1 Target: 8.0% ($1,600 on $20k) - Auto-locks trading when reached!
    CHALLENGE_PHASE_2_TARGET_PCT: float = 5.0 # Phase 2 Target: 5.0% ($1,000 on $20k)
    PROP_FIRM_START_DATE: Optional[str] = "2026-11-01" # Tracks challenge metrics from this start date (None = all time)

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
    # Validated across 3-year MT5 tick data (2024-2026) with 0 overfitted / decaying strategies
    PORTFOLIO_STRATEGIES: List[Dict[str, Any]] = field(default_factory=lambda: [
        {
            "id": "strat_1_eurusd_orb_core",
            "name": "Rank 1: London ORB Core (EURUSD 15m)",
            "pair": "EURUSD",
            "ticker": "EURUSD=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 4,
            "spread_pips": 0.7,
            "type": "ORB",
            "params": {"buffer_pips": 5.0, "rr_ratio": 1.5, "sl_at_mid": True, "max_bars": 32}
        },
        {
            "id": "strat_2_eurusd_orb_tight",
            "name": "Rank 2: London ORB Tight (EURUSD 15m)",
            "pair": "EURUSD",
            "ticker": "EURUSD=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 4,
            "spread_pips": 0.7,
            "type": "ORB",
            "params": {"buffer_pips": 5.0, "rr_ratio": 1.2, "sl_at_mid": True, "max_bars": 32}
        },
        {
            "id": "strat_3_usdjpy_orb_alpha",
            "name": "Rank 3: London ORB Alpha (USDJPY 15m)",
            "pair": "USDJPY",
            "ticker": "USDJPY=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 2,
            "spread_pips": 1.0,
            "type": "ORB",
            "params": {"buffer_pips": 12.0, "rr_ratio": 2.5, "sl_at_mid": True, "max_bars": 40}
        },
        {
            "id": "strat_4_usdjpy_orb_quick",
            "name": "Rank 4: London ORB Quick (USDJPY 15m)",
            "pair": "USDJPY",
            "ticker": "USDJPY=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 2,
            "spread_pips": 1.0,
            "type": "ORB",
            "params": {"buffer_pips": 12.0, "rr_ratio": 1.2, "sl_at_mid": True, "max_bars": 40}
        },
        {
            "id": "strat_5_audusd_turtle_champ",
            "name": "Rank 5: Turtle Soup Sweep (AUDUSD 15m)",
            "pair": "AUDUSD",
            "ticker": "AUDUSD=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 4,
            "spread_pips": 0.9,
            "type": "TURTLE",
            "params": {"swing_lookback": 12, "buffer_pips": 5.0, "wick_ratio": 0.45, "rr_ratio": 2.0, "max_bars": 20}
        },
        {
            "id": "strat_6_audusd_turtle_swing",
            "name": "Rank 6: Turtle Soup Swing (AUDUSD 15m)",
            "pair": "AUDUSD",
            "ticker": "AUDUSD=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 4,
            "spread_pips": 0.9,
            "type": "TURTLE",
            "params": {"swing_lookback": 12, "buffer_pips": 5.0, "wick_ratio": 0.45, "rr_ratio": 2.0, "max_bars": 28}
        },
        {
            "id": "strat_7_eurjpy_turtle_sweep",
            "name": "Rank 7: Turtle Soup Sweep (EURJPY 15m)",
            "pair": "EURJPY",
            "ticker": "EURJPY=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 2,
            "spread_pips": 1.2,
            "type": "TURTLE",
            "params": {"swing_lookback": 28, "buffer_pips": 8.0, "wick_ratio": 0.55, "rr_ratio": 1.5, "max_bars": 36}
        },
        {
            "id": "strat_8_gbpusd_orb_core",
            "name": "Rank 8: London ORB Breakout (GBPUSD 15m)",
            "pair": "GBPUSD",
            "ticker": "GBPUSD=X",
            "timeframe": "15m",
            "period": "10d",
            "dec": 4,
            "spread_pips": 1.0,
            "type": "ORB",
            "params": {"buffer_pips": 8.0, "rr_ratio": 2.5, "sl_at_mid": True, "max_bars": 40}
        }
    ])

config = TradingConfig()
