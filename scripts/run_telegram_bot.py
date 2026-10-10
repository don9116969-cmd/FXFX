"""
Interactive Telegram Bot Listener
Runs a continuous listener to respond to button taps in real time (Active Trades, Profits, Specs, etc.).
"""

import sys
import os
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.telegram_notifier import TelegramNotifier
from src.live_engine import LivePortfolioEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TelegramBotServer")


def main():
    notifier = TelegramNotifier()
    engine = LivePortfolioEngine()

    print("=" * 70)
    print("FXFX INTERACTIVE TELEGRAM BOT LISTENER STARTED")
    print(f"Bot Username: @FXFX30_bot | Chat ID: {notifier.chat_id}")
    print("Responding to: 📊 Active Trades, 📈 Profits, ⚡ Check Now, etc.")
    print("=" * 70)

    # Send menu dashboard to user on launch
    notifier.send_message(
        "🎛 <b>FXFX Interactive Control Panel Online</b>\n\n"
        "Tap any button below to check your portfolio, live trades, or performance:",
        reply_markup=notifier.get_keyboard_markup()
    )

    while True:
        try:
            notifier.process_incoming_updates(engine)
            time.sleep(2)
        except KeyboardInterrupt:
            print("\nStopped bot listener.")
            break
        except Exception as e:
            logger.error(f"Listener error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
