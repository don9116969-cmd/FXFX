"""
FXFX 24/5 Live Multi-Strategy Portfolio Monitoring Engine
Supports:
  1. Continuous 24/5 Daemon Loop (with lightweight HTTP ping server for Render/Cloud keep-alive)
  2. Single-Run Mode (--once) for GitHub Actions cron execution
  3. Integrated Trade Journaling (CSV & Markdown Ledger)
  4. Real-Time Interactive Telegram Controller Daemon
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

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config, TradingConfig
from src.telegram_notifier import TelegramNotifier, start_interactive_bot_daemon
from src.journal_manager import load_active_trades, save_active_trades, log_trade_to_journal, refresh_markdown_journal
from src.git_sync import git_sync_push
from src.strategy_lab import StrategyLaboratory
from src.strategies.strategy_2_variance_ratio import VarianceRatioMeanReversionStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("LiveFXEngine")

STATE_FILE = config.STATE_FILE
PORTFOLIO_STRATEGIES = config.PORTFOLIO_STRATEGIES


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
        self.active_trades: Dict[str, Dict[str, Any]] = load_active_trades()
        self.last_bar_times: Dict[str, Any] = {}
        self._data_cache: Dict[str, pd.DataFrame] = {}
        # Ensure trade journal markdown is synchronized on startup
        refresh_markdown_journal(self.active_trades)

    def _save_state(self):
        """Persists active positions to live_portfolio_state.json and refreshes trade_journal.md."""
        save_active_trades(self.active_trades)

    def fetch_live_data(self, ticker: str, period: str, interval: str) -> Optional[pd.DataFrame]:
        """
        Robust live data fetcher using yf.Ticker.history with automatic retries and per-cycle caching.
        Eliminates 'NoneType' object is not subscriptable crashes.
        """
        cache_key = f"{ticker}_{period}_{interval}"
        if cache_key in self._data_cache:
            return self._data_cache[cache_key].copy()

        # Primary robust method: Ticker.history
        for attempt in range(3):
            try:
                t = yf.Ticker(ticker)
                df = t.history(period=period, interval=interval)
                if df is not None and not df.empty and len(df) >= 30:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    df = df.rename(columns={c: c.capitalize() for c in df.columns})
                    df = df.dropna(subset=["Open", "High", "Low", "Close"])
                    if df.index.tz is None:
                        df.index = df.index.tz_localize("UTC")
                    else:
                        df.index = df.index.tz_convert("UTC")
                    df = df.sort_index()
                    self._data_cache[cache_key] = df
                    return df.copy()
            except Exception:
                time.sleep(1)

        # Fallback method: yf.download
        try:
            df = yf.download(tickers=ticker, period=period, interval=interval, auto_adjust=False, progress=False)
            if df is not None and not df.empty and len(df) >= 30:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.rename(columns={c: c.capitalize() for c in df.columns})
                df = df.dropna(subset=["Open", "High", "Low", "Close"])
                if df.index.tz is None:
                    df.index = df.index.tz_localize("UTC")
                else:
                    df.index = df.index.tz_convert("UTC")
                df = df.sort_index()
                self._data_cache[cache_key] = df
                return df.copy()
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
                    # Dispatch deduplicated alert
                    self.notifier.alert_trade_exit(trade)
                    # Log to trade journal CSV & Markdown ledger
                    log_trade_to_journal(trade, sync_git=True)
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
                    # Dispatch deduplicated alert
                    self.notifier.alert_trade_exit(trade)
                    # Log to trade journal CSV & Markdown ledger
                    log_trade_to_journal(trade, sync_git=True)
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
                        "risk_usd": self.risk_per_trade_usd,
                        "rr_ratio": strat_cfg["params"].get("rr_ratio", 2.0),
                        "max_bars": strat_cfg["params"].get("max_bars", 32),
                        "bars_held": 0,
                        "entry_time_str": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                    }
                    self.active_trades[sid] = trade_record
                    self._save_state()
                    logger.info(f"[{strat_cfg['name']}] NEW ENTRY: {'BUY' if sig == 1 else 'SELL'} @ {entry_price:.5f}")
                    # Dispatch deduplicated alert
                    self.notifier.alert_trade_entry(trade_record)
                    git_sync_push(f"Trade Entry: {pair} {'BUY' if sig == 1 else 'SELL'} @ {entry_price:.5f}")

    def run_single_cycle(self, process_updates: bool = True, notify_heartbeat: bool = False):
        """Processes one check cycle across all strategies and exits (for GitHub Actions)."""
        now_utc = datetime.now(timezone.utc)
        logger.info(f"Running single portfolio check cycle at {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        self._data_cache.clear()
        if process_updates:
            # Process any pending interactive button clicks or commands from user
            self.notifier.process_incoming_updates(self)

        trades_before = len(self.active_trades)
        for strat_cfg in PORTFOLIO_STRATEGIES:
            try:
                self.process_strategy_cycle(strat_cfg)
            except Exception as e:
                logger.error(f"Error checking {strat_cfg['name']}: {e}")

        # Process any updates that arrived while cycle was executing
        if process_updates:
            self.notifier.process_incoming_updates(self)

        # Refresh trade journal markdown table
        refresh_markdown_journal(self.active_trades)
        logger.info("Cycle completed.")

        # Optional cycle heartbeat notification
        should_notify = notify_heartbeat or os.getenv("NOTIFY_CYCLE", "false").lower() in ("true", "1", "yes")
        if should_notify and len(self.active_trades) == trades_before:
            now_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
            open_cnt = len(self.active_trades)
            hb_msg = (
                f"📡 *FXFX 15-Minute Cycle Evaluation Complete*\n"
                f"⏰ `{now_str}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• Strategies Scanned: *8 Champion Models (100% 15m)*\n"
                f"• Active In-Flight Trades: *{open_cnt} Open Positions*\n"
                f"• Signal Engine: Scanning London ORB & Turtle Soup sweeps\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"ℹ️ *All market feeds healthy. Next candle scan in 15 mins.*"
            )
            self.notifier.send_message(hb_msg)

        if process_updates:
            # Final drain of any user clicks that occurred during notification dispatch
            self.notifier.process_incoming_updates(self)

    def run_continuous_loop(self, poll_interval: int = 60, port: int = 8080):
        """Continuous 24/5 daemon with HTTP keep-alive and background Telegram bot listener."""
        logger.info("=" * 70)
        logger.info("FXFX 24/5 LIVE PORTFOLIO ENGINE STARTED")
        logger.info(f"Monitoring {len(PORTFOLIO_STRATEGIES)} Institutional Strategies")
        logger.info("=" * 70)

        # Start health check server in background thread (for Render / Koyeb / Docker)
        http_thread = threading.Thread(target=start_health_server, args=(port,), daemon=True)
        http_thread.start()

        # Start interactive Telegram polling daemon in background thread (<0.2s button response)
        bot_thread, stop_event = start_interactive_bot_daemon(self)

        while True:
            try:
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
                if stop_event:
                    stop_event.set()
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
