"""
Telegram Notification Engine for FXFX
Sends rich institutional trading alerts for entries, exits, TPs, and SLs.
Includes automatic Chat ID pairing on /start.
"""

import os
import json
import logging
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("TelegramNotifier")


class TelegramNotifier:
    """
    Manages Telegram bot communication and trading alerts.
    """

    def __init__(self, env_path: str = ".env"):
        self.env_path = env_path
        load_dotenv(env_path, override=True)
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "8921977032:AAGtcA7uiuGNYAvWQYMtnjjj0wZL06ByWH4")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Sends a message to the registered chat_id."""
        if not self.chat_id:
            logger.warning("Telegram Chat ID not set! Send /start to @FXFX30_bot first.")
            return False

        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read())
                return res_data.get("ok", False)
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def auto_pair_chat_id(self) -> Optional[str]:
        """
        Polls getUpdates to detect the user's Chat ID when they message /start to the bot.
        Saves the detected Chat ID into the .env file.
        """
        try:
            url = f"{self.base_url}/getUpdates"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
                if data.get("ok") and data.get("result"):
                    for update in reversed(data["result"]):
                        message = update.get("message", {})
                        chat = message.get("chat", {})
                        cid = str(chat.get("id", ""))
                        first_name = chat.get("first_name", "Trader")
                        username = chat.get("username", "")

                        if cid:
                            self.chat_id = cid
                            self._save_chat_id_to_env(cid)
                            print(f"[OK] Paired with User: {first_name} (@{username}) | Chat ID: {cid}")
                            # Send welcome notification
                            welcome_msg = (
                                f"🚀 <b>FXFX Institutional Engine Connected!</b>\n\n"
                                f"👤 <b>Trader:</b> {first_name}\n"
                                f"🆔 <b>Chat ID:</b> <code>{cid}</code>\n"
                                f"📊 <b>Active Strategies:</b> 8 Portfolio Models\n"
                                f"⚡ <b>Mode:</b> Live Signal & Execution Alerts Active 24/5\n\n"
                                f"<i>You will receive instant alerts for Entries, Take Profits, Stop Losses, and Session Exits.</i>"
                            )
                            self.send_message(welcome_msg)
                            return cid
            return None
        except Exception as e:
            logger.error(f"Error checking Telegram updates: {e}")
            return None

    def _save_chat_id_to_env(self, chat_id: str):
        """Updates TELEGRAM_CHAT_ID in .env."""
        try:
            lines = []
            found = False
            if os.path.exists(self.env_path):
                with open(self.env_path, "r") as f:
                    lines = f.readlines()

            new_lines = []
            for line in lines:
                if line.startswith("TELEGRAM_CHAT_ID="):
                    new_lines.append(f"TELEGRAM_CHAT_ID={chat_id}\n")
                    found = True
                else:
                    new_lines.append(line)

            if not found:
                new_lines.append(f"TELEGRAM_CHAT_ID={chat_id}\n")

            with open(self.env_path, "w") as f:
                f.writelines(new_lines)
            load_dotenv(self.env_path, override=True)
        except Exception as e:
            logger.error(f"Could not save chat_id to .env: {e}")

    # =========================================================================
    # TRADE ALERT FORMATTERS
    # =========================================================================
    def alert_trade_entry(self, trade: Dict[str, Any]):
        """Alerts when a new trade is executed."""
        side_icon = "🟢 BUY (LONG)" if trade["side"] == 1 else "🔴 SELL (SHORT)"
        msg = (
            f"⚡ <b>FXFX NEW TRADE EXECUTED</b>\n"
            f"────────────────────────\n"
            f"🎯 <b>Strategy:</b> <code>{trade.get('strategy_name', 'Quant Model')}</code>\n"
            f"💱 <b>Pair:</b> <b>{trade['pair']}</b> ({trade.get('timeframe', '15m')})\n"
            f"📊 <b>Direction:</b> {side_icon}\n"
            f"💰 <b>Entry Price:</b> <code>{trade['entry_price']:.5f}</code>\n"
            f"🛑 <b>Stop Loss:</b> <code>{trade['sl']:.5f}</code>\n"
            f"🎯 <b>Take Profit:</b> <code>{trade['tp']:.5f}</code>\n"
            f"⚖️ <b>Risk:Reward:</b> <code>1:{trade.get('rr_ratio', 2.0):.1f}</code>\n"
            f"⏰ <b>Fill Time (UTC):</b> {trade.get('entry_time_str', 'Now')}\n"
            f"────────────────────────\n"
            f"🔒 <i>Zero-Indicator Microstructure Edge Active</i>"
        )
        self.send_message(msg)

    def alert_trade_exit(self, trade: Dict[str, Any]):
        """Alerts when a trade is closed (TP, SL, or Timeout)."""
        pnl = trade.get("pnl", 0.0)
        pnl_pct = trade.get("pnl_pct", 0.0)
        reason = trade.get("exit_reason", "MANUAL")

        if reason == "TP":
            header = "🎯 <b>TAKE PROFIT HIT (+WIN)</b>"
            pnl_str = f"<b>+${pnl:.2f} (+{pnl_pct:.2f}%)</b>"
            icon = "✅"
        elif reason == "SL":
            header = "🛑 <b>STOP LOSS TRIGGERED (-LOSS)</b>"
            pnl_str = f"<b>-${abs(pnl):.2f} ({pnl_pct:.2f}%)</b>"
            icon = "❌"
        else:
            header = "⏱️ <b>SESSION TIMEOUT EXIT</b>"
            sign = "+" if pnl >= 0 else "-"
            pnl_str = f"<b>{sign}${abs(pnl):.2f}</b>"
            icon = "⏳"

        msg = (
            f"{header}\n"
            f"────────────────────────\n"
            f"💱 <b>Pair:</b> <b>{trade['pair']}</b>\n"
            f"🎯 <b>Strategy:</b> <code>{trade.get('strategy_name', 'Quant Model')}</code>\n"
            f"🚪 <b>Exit Price:</b> <code>{trade['exit_price']:.5f}</code>\n"
            f"{icon} <b>Realized PnL:</b> {pnl_str}\n"
            f"⌛ <b>Holding Time:</b> {trade.get('bars_held', 0)} bars\n"
            f"⏰ <b>Exit Time (UTC):</b> {trade.get('exit_time_str', 'Now')}\n"
            f"────────────────────────"
        )
        self.send_message(msg)
