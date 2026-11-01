"""
Automated Trade Journal Manager & Ledger Engine for FXFX Institutional Trading Bot.
Manages:
1. data/live_portfolio_state.json - Tracks in-flight open positions.
2. data/trade_journal.csv - Single source of truth for all completed Forex trades.
3. data/trade_journal.md - Live formatted Markdown journal showing active positions, performance stats, and trade ledger.
"""

import os
import sys
import json
from datetime import datetime, timezone
import pandas as pd
from typing import Dict, Any, Optional

from config import config
from src.git_sync import git_sync_push

DATA_DIR = config.DATA_DIR
STATE_FILE = config.STATE_FILE
JOURNAL_CSV = config.JOURNAL_CSV_FILE
JOURNAL_MD = config.JOURNAL_MD_FILE

def load_active_trades() -> Dict[str, Any]:
    """Loads current live active in-flight positions."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}

def save_active_trades(active_trades: Dict[str, Any]):
    """Persists active positions to live_portfolio_state.json and refreshes markdown journal."""
    os.makedirs(DATA_DIR, exist_ok=True)
    clean_trades = {}
    for k, v in active_trades.items():
        if v is not None:
            c = dict(v)
            if "entry_time" in c and hasattr(c["entry_time"], "isoformat"):
                c["entry_time"] = c["entry_time"].isoformat()
            clean_trades[k] = c
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(clean_trades, f, indent=2, default=str)
    except Exception as e:
        print(f"[WARN] Failed to write active trades state: {e}")

    refresh_markdown_journal(active_trades=clean_trades)

def log_trade_to_journal(trade: Dict[str, Any], sync_git: bool = True):
    """
    Appends a closed trade to trade_journal.csv without duplicates,
    regenerates trade_journal.md, and pushes updates to GitHub.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    df_j = pd.DataFrame()
    if os.path.exists(JOURNAL_CSV):
        try:
            df_j = pd.read_csv(JOURNAL_CSV)
        except Exception:
            df_j = pd.DataFrame()

    entry_t = str(trade.get("entry_time_str", trade.get("entry_time", "")))
    strat_id = str(trade.get("strategy_id", ""))
    pair = str(trade.get("pair", ""))
    date_val = str(entry_t)[:10] if entry_t else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Deduplication check
    if not df_j.empty and "date" in df_j.columns and "entry_time" in df_j.columns and "strategy" in df_j.columns:
        dup = df_j[
            (df_j["date"].astype(str) == date_val) &
            (df_j["strategy"] == strat_id) &
            (df_j["pair"] == pair) &
            (df_j["entry_time"].astype(str) == entry_t)
        ]
        if not dup.empty:
            return  # Already logged

    side_label = "BUY" if trade.get("side") == 1 else "SELL"
    pnl = float(trade.get("pnl", 0.0))
    pnl_pct = float(trade.get("pnl_pct", 0.0))
    entry_p = float(trade.get("entry_price", 0.0))
    exit_p = float(trade.get("exit_price", 0.0))
    units = float(trade.get("units", 0.0))

    row = {
        "date": date_val,
        "strategy": strat_id,
        "strategy_name": str(trade.get("strategy_name", strat_id)),
        "pair": pair,
        "timeframe": str(trade.get("timeframe", "15m")),
        "side": side_label,
        "entry_time": entry_t,
        "exit_time": str(trade.get("exit_time_str", trade.get("exit_time", ""))),
        "entry_price": round(entry_p, 5),
        "exit_price": round(exit_p, 5),
        "units": round(units, 2),
        "risk_usd": round(float(trade.get("risk_usd", config.RISK_PER_TRADE_USD)), 2),
        "net_pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "exit_reason": str(trade.get("exit_reason", "MANUAL")),
        "bars_held": int(trade.get("bars_held", 0))
    }

    df_j = pd.concat([df_j, pd.DataFrame([row])], ignore_index=True)
    df_j.sort_values(by=["date", "entry_time"], inplace=True)
    df_j.to_csv(JOURNAL_CSV, index=False)

    refresh_markdown_journal()

    if sync_git:
        git_sync_push(f"Trade closed: {pair} {side_label} PnL: ${pnl:+,.2f}")

def refresh_markdown_journal(active_trades: Optional[Dict[str, Any]] = None):
    """
    Regenerates data/trade_journal.md with:
    1. 🟢 Live Active Open Positions (In-Flight)
    2. 📊 Live Trading Performance Summary
    3. 📜 Complete Chronological Trade Ledger
    """
    now_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if active_trades is None:
        active_trades = load_active_trades()

    active_rows = []
    for sid, pos in active_trades.items():
        if pos:
            pair = pos.get("pair", "")
            s_name = pos.get("strategy_name", sid)
            side = "🟢 BUY" if pos.get("side") == 1 else "🔴 SELL"
            entry_p = float(pos.get("entry_price", 0.0))
            tp = float(pos.get("tp", 0.0))
            sl = float(pos.get("sl", 0.0))
            bars = pos.get("bars_held", 0)
            entry_t = str(pos.get("entry_time_str", pos.get("entry_time", "")))

            active_rows.append({
                "strategy": s_name,
                "pair": pair,
                "side": side,
                "entry_time": entry_t,
                "entry_price": f"{entry_p:.5f}",
                "tp": f"{tp:.5f}",
                "sl": f"{sl:.5f}",
                "bars_held": f"{bars} bars",
                "status": "🟢 ACTIVE / IN-PROGRESS"
            })

    # Read closed trades ledger
    df_j = pd.DataFrame()
    if os.path.exists(JOURNAL_CSV):
        try:
            df_j = pd.read_csv(JOURNAL_CSV)
            if not df_j.empty and "date" in df_j.columns and "entry_time" in df_j.columns:
                df_j.sort_values(by=["date", "entry_time"], ascending=[False, False], inplace=True)
        except Exception:
            df_j = pd.DataFrame()

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(JOURNAL_MD, "w", encoding="utf-8") as f:
        f.write("# 📈 Live Forex Trading Journal & Institutional Execution Log\n\n")
        f.write(f"*Last Updated: {now_utc_str}*\n\n")
        f.write("---\n\n")

        # 1. Active Positions Section
        f.write("## 🟢 Live Active Open Positions (In-Flight)\n\n")
        if active_rows:
            f.write("| Strategy | Pair | Direction | Entry Time | Entry Price | Take Profit | Stop Loss | Bars Held | Status |\n")
            f.write("|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n")
            for ar in active_rows:
                f.write(f"| **{ar['strategy']}** | `{ar['pair']}` | {ar['side']} | {ar['entry_time']} | `{ar['entry_price']}` | `{ar['tp']}` | `{ar['sl']}` | {ar['bars_held']} | `{ar['status']}` |\n")
            f.write("\n")
        else:
            f.write("> ℹ️ **No active open positions currently in-flight.**  \n")
            max_dep = config.MAX_ACTIVE_TRADES * config.RISK_PER_TRADE_USD
            f.write(f"> *Risk deployed: $0.00 / ${max_dep:,.2f} Max ({config.MAX_ACTIVE_TRADES} trades @ ${config.RISK_PER_TRADE_USD:,.2f}) | Bot is actively scanning 15m market candles across all 8 quantitative models.*  \n\n")

        f.write("---\n\n")

        # 2. Performance Summary Section
        f.write("## 📊 Live Trading Performance Summary\n\n")
        tot = len(df_j) if not df_j.empty else 0
        wins = len(df_j[df_j["net_pnl"] > 0]) if not df_j.empty and "net_pnl" in df_j.columns else 0
        losses = len(df_j[df_j["net_pnl"] <= 0]) if not df_j.empty and "net_pnl" in df_j.columns else 0
        wr = (wins / tot * 100.0) if tot > 0 else 0.0
        tot_pnl = float(df_j["net_pnl"].sum()) if not df_j.empty and "net_pnl" in df_j.columns else 0.0
        starting_cap = config.INITIAL_CAPITAL
        current_bal = starting_cap + tot_pnl
        ret_pct = ((current_bal - starting_cap) / starting_cap) * 100.0

        pnl_str = f"+${tot_pnl:,.2f}" if tot_pnl >= 0 else f"-${abs(tot_pnl):,.2f}"
        ret_str = f"+{ret_pct:.2f}%" if ret_pct >= 0 else f"{ret_pct:.2f}%"

        f.write(f"- **Starting Portfolio Capital**: USD ${starting_cap:,.2f}\n")
        f.write(f"- **Total Executed Trades**: {tot}\n")
        f.write(f"- **Win Rate**: **{wr:.1f}%** ({wins} Wins / {losses} Losses)\n")
        f.write(f"- **Net Realized PnL**: **{pnl_str}**\n")
        f.write(f"- **Current Account Balance**: **USD ${current_bal:,.2f}** ({ret_str} Return)\n")
        risk_p = (config.RISK_PER_TRADE_USD / config.INITIAL_CAPITAL) * 100.0
        f.write(f"- **Risk Control**: Strictly ${config.RISK_PER_TRADE_USD:,.2f} per trade ({risk_p:.1f}% portfolio risk cap)\n\n")

        f.write("---\n\n")

        # 3. Complete Historical Trade Ledger
        f.write("## 📜 Complete Historical Trade Ledger\n\n")
        if not df_j.empty:
            f.write("| Date | Strategy | Pair | Side | Entry Time | Exit Time | Entry P | Exit P | Net PnL | Reason | Bars |\n")
            f.write("|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n")
            for _, r in df_j.iterrows():
                net_val = float(r["net_pnl"])
                badge = f"**+${net_val:.2f}**" if net_val > 0 else f"**-${abs(net_val):.2f}**"
                side_icon = "🟢 BUY" if r["side"] == "BUY" else "🔴 SELL"
                f.write(f"| {r['date']} | {r.get('strategy_name', r['strategy'])} | `{r['pair']}` | {side_icon} | {r['entry_time']} | {r['exit_time']} | {float(r['entry_price']):.5f} | {float(r['exit_price']):.5f} | {badge} | `{r['exit_reason']}` | {r.get('bars_held', 0)} |\n")
            f.write("\n")
        else:
            f.write("*No closed trades logged yet. Bot is scanning live markets.*\n\n")
