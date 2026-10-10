"""
Telegram Pairing & Test Alert Script
Run this script after sending /start to @FXFX30_bot on Telegram!
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.telegram_notifier import TelegramNotifier

notifier = TelegramNotifier()

print("=" * 70)
print("TELEGRAM BOT PAIRING WIZARD")
print(f"Bot Username: @FXFX30_bot")
print("=" * 70)

if notifier.chat_id:
    print(f"[INFO] Chat ID already configured: {notifier.chat_id}")
    print("Sending test trade alert...")
    test_trade = {
        "strategy_name": "Rank 4: London ORB (EURUSD 15m)",
        "pair": "EURUSD",
        "timeframe": "15m",
        "side": 1,
        "entry_price": 1.12427,
        "sl": 1.12150,
        "tp": 1.12842,
        "rr_ratio": 1.5,
        "entry_time_str": "2026-10-10 08:00:00 UTC"
    }
    sent = notifier.alert_trade_entry(test_trade)
    if sent:
        print("[SUCCESS] Test trade notification delivered to your Telegram!")
    else:
        print("[WARNING] Could not deliver message. Please ensure you sent /start to @FXFX30_bot.")
else:
    print("\nPlease follow these simple steps:")
    print("1. Open Telegram on your phone or PC.")
    print("2. Search for: @FXFX30_bot")
    print("3. Click 'Start' or send a message like: /start")
    print("\nWaiting for your message (listening for updates)...")

    for attempt in range(30):
        cid = notifier.auto_pair_chat_id()
        if cid:
            print(f"\n[SUCCESS] Successfully paired! Chat ID: {cid}")
            print("Check your Telegram for the confirmation message!")
            break
        time.sleep(2)
        print(".", end="", flush=True)
    else:
        print("\n[TIMEOUT] Did not receive a message. Please send /start to @FXFX30_bot and run this script again.")
