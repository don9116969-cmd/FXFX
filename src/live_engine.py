"""
FXFX 24/5 Live Multi-Strategy Portfolio Monitoring Engine
Supports:
  1. Continuous 24/5 Daemon Loop (with lightweight HTTP ping server for Render/Cloud keep-alive)
  2. Single-Run Mode (--once) for GitHub Actions cron execution
"""

import os
import sys
import time
import json
import logging
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.telegram_notifier import TelegramNotifier
from src.strategy_lab import StrategyLaboratory
from src.strategies.strategy_2_variance_ratio import VarianceRatioMeanReversionStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("LiveFXEngine")

STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "live_portfolio_state.json")

# The 8 Active Institutional Strategies
PORTFOLIO_STRATEGIES = [
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
]


# Lightweight HTTP Handler for Render / Koyeb Health Check Keep-Alive
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        res = {"status": "ok", "service": "FXFX Trading Engine", "time": datetime.now(timezone.utc).isoformat()}
        self.wfile.write(json.dumps(res).encode("utf-8"))

    def log_message(self, format, *args):
        pass  # Suppress access logs to keep terminal clean


def start_health_server(port: int = 8080):
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logger.info(f"Health-check server running on port {port}")
    server.serve_forever()


class LivePortfolioEngine:
    def __init__(self, risk_per_trade_usd: float = 100.0):
        self.notifier = TelegramNotifier()
        self.risk_per_trade_usd = risk_per_trade_usd
        self.active_trades: Dict[str, Dict[str, Any]] = self._load_state()
        self.last_bar_times: Dict[str, Any] = {}

    def _load_state(self) -> Dict[str, Dict[str, Any]]:
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading state: {e}")
        return {}

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(self.active_trades, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def fetch_live_data(self, ticker: str, period: str, interval: str) -> Optional[pd.DataFrame]:
        try:
            df = yf.download(tickers=ticker, period=period, interval=interval, auto_adjust=False, progress=False)
            if df.empty:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.rename(columns={c: c.capitalize() for c in df.columns})
            df = df.dropna(subset=["Open", "High", "Low", "Close"])
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            else:
                df.index = df.index.tz_convert("UTC")
            return df.sort_index()
        except Exception as e:
            logger.error(f"Live data fetch error for {ticker}: {e}")
            return None

    def evaluate_strategy_signals(self, strat_cfg: Dict[str, Any], df: pd.DataFrame) -> pd.DataFrame:
        stype = strat_cfg["type"]
        pip_size = 10 ** (-strat_cfg["dec"])
        params = strat_cfg["params"]

        if stype == "ORB":
            return StrategyLaboratory.strategy_london_orb(df, params, pip_size)
        elif stype == "TURTLE":
            return StrategyLaboratory.strategy_turtle_soup_liquidity(df, params, pip_size)
        elif stype == "VARIANCE_RATIO":
            s = VarianceRatioMeanReversionStrategy(pip_decimal=strat_cfg["dec"])
            return s.generate_signals(df, params)
        return pd.DataFrame()

    def process_strategy_cycle(self, strat_cfg: Dict[str, Any]):
        sid = strat_cfg["id"]
        pair = strat_cfg["pair"]
        ticker = strat_cfg["ticker"]
        tf = strat_cfg["timeframe"]
        pip_size = 10 ** (-strat_cfg["dec"])
        spread_val = strat_cfg["spread_pips"] * pip_size

        df = self.fetch_live_data(ticker, strat_cfg["period"], tf)
        if df is None or len(df) < 50:
            return

        last_closed_bar = df.iloc[-2]
        last_closed_time = df.index[-2]
        current_candle = df.iloc[-1]

        # 1. Manage Active Trade
        if sid in self.active_trades:
            trade = self.active_trades[sid]
            side = trade["side"]
            sl = trade["sl"]
            tp = trade["tp"]
            entry_price = trade["entry_price"]
            units = trade["units"]
            max_bars = trade.get("max_bars", 32)

            curr_h = current_candle["High"]
            curr_l = current_candle["Low"]
            curr_c = current_candle["Close"]

            exit_price = None
            exit_reason = None
            trade["bars_held"] = trade.get("bars_held", 0) + 1

            if side == 1:
                if curr_l <= sl:
                    exit_price = min(current_candle["Open"], sl)
                    exit_reason = "SL"
                elif curr_h >= tp:
                    exit_price = max(current_candle["Open"], tp)
                    exit_reason = "TP"
                elif trade["bars_held"] >= max_bars:
                    exit_price = curr_c
                    exit_reason = "TIMEOUT"

                if exit_price is not None:
                    actual_exit = exit_price - (spread_val / 2.0)
                    pnl = (actual_exit - entry_price) * units
                    pnl_pct = ((actual_exit - entry_price) / entry_price) * 100

                    trade.update({
                        "exit_price": actual_exit,
                        "exit_time_str": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                        "exit_reason": exit_reason,
                        "pnl": round(pnl, 2),
                        "pnl_pct": round(pnl_pct, 2)
                    })
                    logger.info(f"[{strat_cfg['name']}] EXITED ({exit_reason}) | PnL: ${pnl:.2f}")
                    self.notifier.alert_trade_exit(trade)
                    del self.active_trades[sid]
                    self._save_state()

            elif side == -1:
                if curr_h >= sl:
                    exit_price = max(current_candle["Open"], sl)
                    exit_reason = "SL"
                elif curr_l <= tp:
                    exit_price = min(current_candle["Open"], tp)
                    exit_reason = "TP"
                elif trade["bars_held"] >= max_bars:
                    exit_price = curr_c
                    exit_reason = "TIMEOUT"

                if exit_price is not None:
                    actual_exit = exit_price + (spread_val / 2.0)
                    pnl = (entry_price - actual_exit) * units
                    pnl_pct = ((entry_price - actual_exit) / entry_price) * 100

                    trade.update({
                        "exit_price": actual_exit,
                        "exit_time_str": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                        "exit_reason": exit_reason,
                        "pnl": round(pnl, 2),
                        "pnl_pct": round(pnl_pct, 2)
                    })
                    logger.info(f"[{strat_cfg['name']}] EXITED ({exit_reason}) | PnL: ${pnl:.2f}")
                    self.notifier.alert_trade_exit(trade)
                    del self.active_trades[sid]
                    self._save_state()

        # 2. Check Signals
        else:
            prev_closed = self.last_bar_times.get(sid)
            if prev_closed == last_closed_time:
                return
            self.last_bar_times[sid] = last_closed_time

            closed_df = df.iloc[:-1]
            sigs = self.evaluate_strategy_signals(strat_cfg, closed_df)
            if sigs.empty:
                return

            last_sig_row = sigs.iloc[-1]
            sig = int(last_sig_row.get("signal", 0))

            if sig in (1, -1):
                sl = float(last_sig_row["sl_price"])
                tp = float(last_sig_row["tp_price"])
                next_open = float(current_candle["Open"])

                if sig == 1:
                    entry_price = next_open + (spread_val / 2.0)
                    sl_dist = entry_price - sl
                    units = self.risk_per_trade_usd / sl_dist if sl_dist > 0 else 0
                else:
                    entry_price = next_open - (spread_val / 2.0)
                    sl_dist = sl - entry_price
                    units = self.risk_per_trade_usd / sl_dist if sl_dist > 0 else 0

                if units > 0 and sl_dist > 0:
                    trade_record = {
                        "strategy_id": sid,
                        "strategy_name": strat_cfg["name"],
                        "pair": pair,
                        "timeframe": tf,
                        "side": sig,
                        "entry_price": entry_price,
                        "sl": sl,
                        "tp": tp,
                        "units": units,
                        "rr_ratio": strat_cfg["params"].get("rr_ratio", 2.0),
                        "max_bars": strat_cfg["params"].get("max_bars", 32),
                        "bars_held": 0,
                        "entry_time_str": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                    }
                    self.active_trades[sid] = trade_record
                    self._save_state()
                    logger.info(f"[{strat_cfg['name']}] NEW ENTRY: {'BUY' if sig == 1 else 'SELL'} @ {entry_price:.5f}")
                    self.notifier.alert_trade_entry(trade_record)

    def run_single_cycle(self, process_updates: bool = True, notify_heartbeat: bool = False):
        """Processes one check cycle across all strategies and exits (for GitHub Actions)."""
        now_utc = datetime.now(timezone.utc)
        logger.info(f"Running single portfolio check cycle at {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        if process_updates:
            # Process any pending interactive button clicks or commands from user
            self.notifier.process_incoming_updates(self)

        trades_before = len(self.active_trades)
        for strat_cfg in PORTFOLIO_STRATEGIES:
            try:
                self.process_strategy_cycle(strat_cfg)
            except Exception as e:
                logger.error(f"Error checking {strat_cfg['name']}: {e}")

        logger.info("Cycle completed.")

        # Optional cycle heartbeat notification to confirm engine is alive
        should_notify = notify_heartbeat or os.getenv("NOTIFY_CYCLE", "false").lower() in ("true", "1", "yes")
        if should_notify and len(self.active_trades) == trades_before:
            now_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
            open_cnt = len(self.active_trades)
            hb_msg = (
                f"📡 <b>FXFX Live Cycle Evaluation Complete</b>\n"
                f"⏰ <code>{now_str}</code>\n"
                f"────────────────────────\n"
                f"• Strategies Scanned: <b>8 Models Active</b>\n"
                f"• Open Positions: <b>{open_cnt} Active Trades</b>\n"
                f"• Signal Status: Monitoring (London ORB, Turtle Soup, VR MR)\n"
                f"────────────────────────\n"
                f"<i>All feeds online &amp; healthy. Next check in 15 mins.</i>"
            )
            self.notifier.send_message(hb_msg)

    def run_continuous_loop(self, poll_interval: int = 60, port: int = 8080):
        """Continuous 24/5 daemon with HTTP keep-alive."""
        logger.info("=" * 70)
        logger.info("FXFX 24/5 LIVE PORTFOLIO ENGINE STARTED")
        logger.info(f"Monitoring {len(PORTFOLIO_STRATEGIES)} Institutional Strategies")
        logger.info("=" * 70)

        # Start health check server in background thread (for Render / Koyeb / Docker)
        http_thread = threading.Thread(target=start_health_server, args=(port,), daemon=True)
        http_thread.start()

        while True:
            try:
                # Handle interactive buttons in real time
                self.notifier.process_incoming_updates(self)

                now_utc = datetime.now(timezone.utc)
                is_weekend = (now_utc.weekday() == 5) or (now_utc.weekday() == 6 and now_utc.hour < 21) or (now_utc.weekday() == 4 and now_utc.hour >= 22)
                if is_weekend:
                    time.sleep(10)
                    continue

                for strat_cfg in PORTFOLIO_STRATEGIES:
                    try:
                        self.process_strategy_cycle(strat_cfg)
                    except Exception as e:
                        logger.error(f"Error in strategy {strat_cfg['name']}: {e}")

                time.sleep(poll_interval)

            except KeyboardInterrupt:
                logger.info("Stopped by user.")
                break
            except Exception as e:
                logger.error(f"Engine loop error: {e}")
                time.sleep(10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FXFX Live Engine")
    parser.add_argument("--once", action="store_true", help="Run a single evaluation cycle and exit (for GitHub Actions)")
    parser.add_argument("--notify", action="store_true", help="Send cycle summary to Telegram even if no new trades triggered")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8080")), help="Port for health check keep-alive")
    args = parser.parse_args()

    risk_env = os.getenv("RISK_PER_TRADE_USD", "").strip()
    risk_val = float(risk_env) if risk_env else 100.0
    engine = LivePortfolioEngine(risk_per_trade_usd=risk_val)

    if args.once:
        engine.run_single_cycle(notify_heartbeat=args.notify)
    else:
        engine.run_continuous_loop(poll_interval=60, port=args.port)
