import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.telegram_notifier import run_telegram_polling_loop

if __name__ == "__main__":
    print("=" * 75)
    print("   FXFX INSTITUTIONAL FOREX BOT - INTERACTIVE TELEGRAM CONTROLLER")
    print("   Available Commands & Buttons: /status, /pnl, /today, /summary, /journal, /check")
    print("=" * 75)
    run_telegram_polling_loop()
