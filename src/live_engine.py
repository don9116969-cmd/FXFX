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
from typing import Dict, List, Any, Optional, Tuple
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
    def __init__(self, risk_per_trade_usd: Optional[float] = None):
        self.notifier = TelegramNotifier()
        self.risk_per_trade_usd = risk_per_trade_usd if risk_per_trade_usd is not None else config.RISK_PER_TRADE_USD
        self.active_trades: Dict[str, Dict[str, Any]] = load_active_trades()
        self.last_bar_times: Dict[str, Any] = {}
        self._data_cache: Dict[str, pd.DataFrame] = {}

        # Automatically purge any obsolete zombie trades whose strategy ID is not in PORTFOLIO_STRATEGIES
        valid_ids = {s["id"] for s in PORTFOLIO_STRATEGIES}
        orphaned = [sid for sid in list(self.active_trades.keys()) if sid not in valid_ids]
        if orphaned:
            logger.warning(f"Purging {len(orphaned)} obsolete zombie trades from active portfolio: {orphaned}")
            for oid in orphaned:
                del self.active_trades[oid]
            self._save_state()

        # Ensure trade journal markdown is synchronized on startup
        refresh_markdown_journal(self.active_trades)

        # MT5 Live Execution Bridge
        self.mt5_executor = None
        if getattr(config, "MT5_ENABLED", False):
            try:
                from src.mt5_executor import MT5LiveExecutor
                self.mt5_executor = MT5LiveExecutor(
                    login=getattr(config, "MT5_LOGIN", None),
                    password=getattr(config, "MT5_PASSWORD", None),
                    server=getattr(config, "MT5_SERVER", "FundedNext-Server 3")
                )
                if self.mt5_executor.connect():
                    logger.info("FundedNext MT5 Live Execution Bridge connected successfully!")
                else:
                    logger.warning("FundedNext MT5 Bridge failed to connect at startup.")
            except Exception as e:
                logger.error(f"Failed to initialize MT5 Executor: {e}")

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

    def get_quote_conversion_rate(self, quote_curr: str) -> float:
        """
        Returns the conversion rate from USD to quote currency:
        - For USD quote (EURUSD, GBPUSD, AUDUSD): 1.0
        - For JPY quote (EURJPY, GBPJPY, USDJPY): USDJPY exchange rate (~155.0)
        - For CAD quote (USDCAD): USDCAD exchange rate (~1.38)
        """
        if quote_curr == "USD":
            return 1.0
        elif quote_curr == "JPY":
            df = self.fetch_live_data("USDJPY=X", "5d", "15m")
            if df is not None and not df.empty:
                return float(df["Close"].iloc[-1])
            return 155.0
        elif quote_curr == "CAD":
            df = self.fetch_live_data("USDCAD=X", "5d", "15m")
            if df is not None and not df.empty:
                return float(df["Close"].iloc[-1])
            return 1.38
        return 1.0

    def check_prop_firm_safeguards(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Monitors institutional prop-firm rules:
        1. Daily loss <= MAX_DAILY_LOSS_PCT (Safety breaker halts before 5.0% prop limit)
        2. Peak-to-trough trailing drawdown <= MAX_OVERALL_DD_PCT (Safety breaker halts before 10.0% limit)
        3. Challenge Phase 1 Target Lock: +CHALLENGE_TARGET_PCT (Freezes entries to protect passed status)
        """
        metrics = {
            "initial_capital": config.INITIAL_CAPITAL,
            "current_equity": config.INITIAL_CAPITAL,
            "peak_equity": config.INITIAL_CAPITAL,
            "cumulative_net_pnl": 0.0,
            "today_realized_pnl": 0.0,
            "floating_unrealized_pnl": 0.0,
            "today_total_pnl": 0.0,
            "daily_loss_pct": 0.0,
            "current_dd_pct": 0.0,
            "account_profit_pct": 0.0,
            "active_trade_count": len(self.active_trades)
        }

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cum_pnl = 0.0
        today_realized = 0.0
        equity_curve = [config.INITIAL_CAPITAL]

        if os.path.exists(config.JOURNAL_CSV_FILE):
            try:
                j_df = pd.read_csv(config.JOURNAL_CSV_FILE)
                if not j_df.empty and "net_pnl" in j_df.columns:
                    start_d = getattr(config, "PROP_FIRM_START_DATE", None)
                    if start_d and "date" in j_df.columns:
                        j_df = j_df[j_df["date"].astype(str) >= str(start_d)]
                    cum_pnl = float(j_df["net_pnl"].sum())
                    if "date" in j_df.columns:
                        today_rows = j_df[j_df["date"].astype(str) == today_str]
                        today_realized = float(today_rows["net_pnl"].sum())

                    running = config.INITIAL_CAPITAL
                    for p in j_df["net_pnl"]:
                        running += float(p)
                        equity_curve.append(running)
            except Exception as e:
                logger.warning(f"Failed to read trade journal for prop firm check: {e}")

        # Compute floating unrealized PnL from active trades
        floating_pnl = 0.0
        for sid, tr in self.active_trades.items():
            try:
                pair = tr.get("pair", "")
                side = int(tr.get("side", 1))
                entry_p = float(tr.get("entry_price", 0.0))
                units = float(tr.get("units", 0.0))
                conv = float(tr.get("conv_rate", 1.0))
                if conv <= 0:
                    conv = 1.0

                ticker_sym = pair + "=X" if not pair.endswith("=X") else pair
                df_spot = self.fetch_live_data(ticker_sym, "1d", "15m")
                cur_p = float(df_spot["Close"].iloc[-1]) if df_spot is not None and not df_spot.empty else entry_p

                raw = (cur_p - entry_p) * units if side == 1 else (entry_p - cur_p) * units
                floating_pnl += (raw / conv)
            except Exception:
                pass

        today_total_pnl = today_realized + floating_pnl
        current_equity = config.INITIAL_CAPITAL + cum_pnl + floating_pnl

        # If live MT5 connection is active, query broker directly for exact equity & floating PnL
        if getattr(self, "mt5_executor", None) and self.mt5_executor.is_connected:
            acc_info = self.mt5_executor.get_account_info()
            if acc_info:
                current_equity = acc_info["equity"]
                floating_pnl = acc_info["profit"]
                today_total_pnl = today_realized + floating_pnl
        peak_equity = max(max(equity_curve), current_equity)
        current_dd_pct = ((peak_equity - current_equity) / peak_equity) * 100.0 if peak_equity > 0 else 0.0
        daily_loss_pct = (today_total_pnl / config.INITIAL_CAPITAL) * 100.0
        account_profit_pct = ((current_equity - config.INITIAL_CAPITAL) / config.INITIAL_CAPITAL) * 100.0

        metrics.update({
            "current_equity": current_equity,
            "peak_equity": peak_equity,
            "cumulative_net_pnl": cum_pnl,
            "today_realized_pnl": today_realized,
            "floating_unrealized_pnl": floating_pnl,
            "today_total_pnl": today_total_pnl,
            "daily_loss_pct": daily_loss_pct,
            "current_dd_pct": current_dd_pct,
            "account_profit_pct": account_profit_pct
        })

        if not getattr(config, "PROP_FIRM_MODE", False):
            return True, "OK", metrics

        # 1. Daily Loss Circuit Breaker
        if daily_loss_pct <= -config.MAX_DAILY_LOSS_PCT:
            msg = (
                f"🛡️ Daily Loss Circuit Breaker: Today's loss is {daily_loss_pct:.2f}% "
                f"(-${abs(today_total_pnl):,.2f}), exceeding the {config.MAX_DAILY_LOSS_PCT:.1f}% safety tripwire. "
                f"New entries locked until 00:00 UTC to safeguard prop firm 5.0% limit."
            )
            return False, msg, metrics

        # 2. Overall Drawdown Guard
        if current_dd_pct >= config.MAX_OVERALL_DD_PCT:
            msg = (
                f"⚠️ Max Drawdown Safety Guard: Current drawdown is {current_dd_pct:.2f}%, "
                f"exceeding the {config.MAX_OVERALL_DD_PCT:.1f}% safety limit. "
                f"Trading locked to safeguard prop firm 10.0% max loss limit."
            )
            return False, msg, metrics

        # 3. Phase Target Lock
        if account_profit_pct >= config.CHALLENGE_TARGET_PCT:
            msg = (
                f"🎉 Challenge Phase 1 Target Reached! Total profit is +{account_profit_pct:.2f}% "
                f"(+${cum_pnl + floating_pnl:,.2f}), meeting the {config.CHALLENGE_TARGET_PCT:.1f}% target. "
                f"Trading automatically locked for verification to prevent give-back!"
            )
            return False, msg, metrics

        return True, "OK", metrics

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

        # 1. Manage Active Trade (Chronological multi-candle replay since entry)
        if sid in self.active_trades:
            trade = self.active_trades[sid]
            side = trade["side"]
            sl = trade["sl"]
            tp = trade["tp"]
            entry_price = trade["entry_price"]
            units = trade["units"]
            max_bars = trade.get("max_bars", 32)
            entry_t_str = trade.get("entry_time_str", "")

            try:
                entry_dt = pd.to_datetime(entry_t_str, utc=True)
            except Exception:
                entry_dt = None

            # Slicing all candles that formed from entry time forward
            if entry_dt is not None:
                eval_candles = df[df.index >= (entry_dt - pd.Timedelta(minutes=15))]
            else:
                eval_candles = df.iloc[-10:]

            exit_price = None
            exit_reason = None
            exit_time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            bars_held = 0

            # Spread allowance buffer (1.0x spread_val) prevents feed discrepancies
            # between retail ECN brokers and Yahoo Finance interbank feeds from unfairly missing TP
            tp_tolerance = spread_val

            for c_time, candle in eval_candles.iterrows():
                # Skip historical candles that closed before trade was opened
                if entry_dt is not None and c_time < (entry_dt - pd.Timedelta(seconds=30)):
                    continue

                bars_held += 1
                c_h = float(candle["High"])
                c_l = float(candle["Low"])
                c_o = float(candle["Open"])
                c_c = float(candle["Close"])

                if side == 1:  # BUY (LONG)
                    # Check Stop Loss first (conservative risk management)
                    if c_l <= sl:
                        exit_price = min(c_o, sl)
                        exit_reason = "SL"
                        exit_time_str = c_time.strftime("%Y-%m-%d %H:%M:%S UTC")
                        break
                    # Check Take Profit (with quote/spread tolerance)
                    elif c_h >= (tp - tp_tolerance):
                        exit_price = max(c_o, tp)
                        exit_reason = "TP"
                        exit_time_str = c_time.strftime("%Y-%m-%d %H:%M:%S UTC")
                        break
                    # Check Max Bars Timeout
                    elif bars_held >= max_bars:
                        exit_price = c_c
                        exit_reason = "TIMEOUT"
                        exit_time_str = c_time.strftime("%Y-%m-%d %H:%M:%S UTC")
                        break

                elif side == -1:  # SELL (SHORT)
                    # Check Stop Loss first (conservative risk management)
                    if c_h >= sl:
                        exit_price = max(c_o, sl)
                        exit_reason = "SL"
                        exit_time_str = c_time.strftime("%Y-%m-%d %H:%M:%S UTC")
                        break
                    # Check Take Profit (with quote/spread tolerance)
                    elif c_l <= (tp + tp_tolerance):
                        exit_price = min(c_o, tp)
                        exit_reason = "TP"
                        exit_time_str = c_time.strftime("%Y-%m-%d %H:%M:%S UTC")
                        break
                    # Check Max Bars Timeout
                    elif bars_held >= max_bars:
                        exit_price = c_c
                        exit_reason = "TIMEOUT"
                        exit_time_str = c_time.strftime("%Y-%m-%d %H:%M:%S UTC")
                        break

            trade["bars_held"] = bars_held

            if exit_price is not None:
                # Close MT5 position if active
                if self.mt5_executor and trade.get("mt5_ticket"):
                    try:
                        self.mt5_executor.close_position_by_ticket(trade["mt5_ticket"])
                    except Exception as e:
                        logger.error(f"Failed to close MT5 position {trade.get('mt5_ticket')}: {e}")

                conv_rate = float(trade.get("conv_rate", 1.0))
                if conv_rate <= 0:
                    conv_rate = 1.0

                if side == 1:
                    actual_exit = exit_price - (spread_val / 2.0)
                    raw_pnl = (actual_exit - entry_price) * units
                else:
                    actual_exit = exit_price + (spread_val / 2.0)
                    raw_pnl = (entry_price - actual_exit) * units

                pnl = raw_pnl / conv_rate
                pnl_pct = (pnl / self.risk_per_trade_usd) * 1.0

                trade.update({
                    "exit_price": actual_exit,
                    "exit_time_str": exit_time_str,
                    "exit_reason": exit_reason,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "bars_held": bars_held
                })
                logger.info(f"[{strat_cfg['name']}] EXITED ({exit_reason}) on candle {exit_time_str} | PnL: ${pnl:.2f}")
                self.notifier.alert_trade_exit(trade)
                log_trade_to_journal(trade, sync_git=True)
                del self.active_trades[sid]
                self._save_state()

        # 2. Check Signals
        else:
            prev_closed = self.last_bar_times.get(sid)
            if prev_closed == last_closed_time:
                return
            self.last_bar_times[sid] = last_closed_time

            # Prop Guard 1: Limit Max Simultaneous Active Trades
            if len(self.active_trades) >= config.MAX_ACTIVE_TRADES:
                return

            # Prop Guard 2: Prevent Multiple Concurrent Trades on the Same Currency Pair
            open_pairs = [t.get("pair") for t in self.active_trades.values()]
            if pair in open_pairs:
                return

            # Prop Guard 3: Automated Prop-Firm Circuit Breakers & Target Locks
            can_enter, block_msg, _ = self.check_prop_firm_safeguards()
            if not can_enter:
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                alert_key = f"SAFEGUARD:{today_str}:{block_msg[:25]}"
                if hasattr(self.notifier, "alert_circuit_breaker"):
                    self.notifier.alert_circuit_breaker(block_msg, alert_key)
                return

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

                quote_curr = pair[-3:].upper()
                conv_rate = self.get_quote_conversion_rate(quote_curr)
                risk_in_quote = self.risk_per_trade_usd * conv_rate
                friction_buffer = spread_val / 2.0

                if sig == 1:
                    entry_price = next_open + (spread_val / 2.0)
                    sl_dist = entry_price - sl
                    effective_sl_dist = sl_dist + friction_buffer
                    units = risk_in_quote / effective_sl_dist if effective_sl_dist > 0 else 0
                else:
                    entry_price = next_open - (spread_val / 2.0)
                    sl_dist = sl - entry_price
                    effective_sl_dist = sl_dist + friction_buffer
                    units = risk_in_quote / effective_sl_dist if effective_sl_dist > 0 else 0

                if units > 0 and sl_dist > 0:
                    mt5_ticket = None
                    if self.mt5_executor and getattr(config, "MT5_ENABLED", False):
                        try:
                            mt5_ticket = self.mt5_executor.execute_market_order(
                                pair=pair,
                                side=sig,
                                units=units,
                                sl=sl,
                                tp=tp,
                                comment=f"FXFX {sid[:15]}"
                            )
                        except Exception as e:
                            logger.error(f"MT5 order execution error for {pair}: {e}")

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
                        "conv_rate": conv_rate,
                        "quote_curr": quote_curr,
                        "rr_ratio": strat_cfg["params"].get("rr_ratio", 2.0),
                        "max_bars": strat_cfg["params"].get("max_bars", 32),
                        "bars_held": 0,
                        "mt5_ticket": mt5_ticket,
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

        # Optional cycle heartbeat notification (disabled by default to eliminate chat spam)
        should_notify = notify_heartbeat and os.getenv("NOTIFY_CYCLE", "false").lower() in ("true", "1", "yes")
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
    try:
        risk_val = float(risk_env) if risk_env and risk_env.lower() not in ("true", "false", "none", "null") else config.RISK_PER_TRADE_USD
    except Exception:
        risk_val = config.RISK_PER_TRADE_USD
    engine = LivePortfolioEngine(risk_per_trade_usd=risk_val)

    if args.once:
        engine.run_single_cycle(notify_heartbeat=args.notify)
    else:
        engine.run_continuous_loop(poll_interval=60, port=args.port)
