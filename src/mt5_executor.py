"""
FundedNext / Institutional MT5 Live Execution Bridge for FXFX
Connects directly to MetaTrader 5 on Windows to:
1. Initialize MT5 terminal connection
2. Authenticate to FundedNext-Server3
3. Calculate precision lot sizing (1.00 lot = 100,000 units)
4. Execute Market Buy/Sell orders with automated SL, TP, and Magic Number
5. Track and close active positions upon strategy exit signals
"""

import os
import sys
import logging
from typing import Dict, Any, Optional
import MetaTrader5 as mt5

logger = logging.getLogger("MT5Executor")

class MT5LiveExecutor:
    def __init__(self, login: Optional[int] = None, password: Optional[str] = None, server: Optional[str] = None):
        self.login = login
        self.password = password
        self.server = server or "FundedNext-Server3"
        self.is_connected = False
        self.magic_number = 998877

    def connect(self) -> bool:
        """Initializes connection to MT5 terminal and verifies account authentication."""
        path = "C:/Program Files/MetaTrader 5/terminal64.exe"
        if not mt5.initialize(path=path):
            logger.error(f"MT5 initialize failed: {mt5.last_error()}")
            return False

        term_info = mt5.terminal_info()
        logger.info(f"MT5 Terminal connected: {term_info.connected}, Build: {term_info.build}")

        if self.login and self.password:
            authorized = mt5.login(login=int(self.login), password=str(self.password), server=str(self.server))
            if not authorized:
                logger.error(f"Failed to log into MT5 account {self.login} on {self.server}: {mt5.last_error()}")
                return False
            logger.info(f"Successfully authenticated to FundedNext MT5 Account {self.login}!")

        acc_info = mt5.account_info()
        if acc_info:
            logger.info(f"FundedNext Account active: Login {acc_info.login} | Balance: ${acc_info.balance:,.2f} {acc_info.currency} | Leverage: 1:{acc_info.leverage}")
            self.is_connected = True
            return True

        return False

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        """Retrieves live account balance, equity, margin, and free margin directly from MT5."""
        if not self.is_connected:
            if not self.connect():
                return None
        acc = mt5.account_info()
        if acc:
            return {
                "login": acc.login,
                "name": acc.name,
                "server": acc.server,
                "balance": float(acc.balance),
                "equity": float(acc.equity),
                "profit": float(acc.profit),
                "margin": float(acc.margin),
                "margin_free": float(acc.margin_free),
                "currency": str(acc.currency),
                "leverage": int(acc.leverage)
            }
        return None

    def get_symbol_name(self, pair: str) -> str:
        """Resolves symbol name (some brokers use EURUSD, EURUSD.raw, EURUSDm, etc.)."""
        candidates = [pair, f"{pair}.raw", f"{pair}.pro", f"{pair}m", f"{pair}+"]
        for sym in candidates:
            info = mt5.symbol_info(sym)
            if info is not None and info.visible:
                return sym
            elif info is not None:
                mt5.symbol_select(sym, True)
                return sym
        return pair

    def execute_market_order(self, pair: str, side: int, units: float, sl: float, tp: float, comment: str = "FXFX Algo") -> Optional[int]:
        """
        Executes a live market BUY or SELL order on FundedNext MT5.
        side = 1 for BUY, -1 for SELL.
        Returns MT5 order ticket if successful.
        """
        if not self.is_connected:
            if not self.connect():
                logger.error("Cannot execute trade: MT5 not connected.")
                return None

        symbol = self.get_symbol_name(pair)
        mt5.symbol_select(symbol, True)
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.error(f"Failed to fetch tick for {symbol}")
            return None

        # Convert units to lots (100,000 units = 1.00 lot)
        lots = round(units / 100000.0, 2)
        sym_info = mt5.symbol_info(symbol)
        min_lot = sym_info.volume_min if sym_info else 0.01
        step_lot = sym_info.volume_step if sym_info else 0.01
        max_lot = sym_info.volume_max if sym_info else 100.0
        lots = max(min_lot, min(max_lot, round(lots / step_lot) * step_lot))
        lots = round(lots, 2)

        order_type = mt5.ORDER_TYPE_BUY if side == 1 else mt5.ORDER_TYPE_SELL
        price = tick.ask if side == 1 else tick.bid
        dec = sym_info.digits if sym_info else (2 if "JPY" in pair else 4)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lots),
            "type": order_type,
            "price": float(round(price, dec)),
            "sl": float(round(sl, dec)),
            "tp": float(round(tp, dec)) if tp else 0.0,
            "deviation": 20,
            "magic": self.magic_number,
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # Try IOC first, fallback to FOK or RETURN if broker rejects filling mode
        result = mt5.order_send(request)
        if result and result.retcode != mt5.TRADE_RETCODE_DONE:
            request["type_filling"] = mt5.ORDER_FILLING_FOK
            result = mt5.order_send(request)
        if result and result.retcode != mt5.TRADE_RETCODE_DONE:
            request["type_filling"] = mt5.ORDER_FILLING_RETURN
            result = mt5.order_send(request)

        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"MT5 ORDER EXECUTED! Ticket: {result.order} | {symbol} {'BUY' if side==1 else 'SELL'} {lots} lots @ {result.price}")
            return result.order
        else:
            err = result.comment if result else mt5.last_error()
            logger.error(f"MT5 order failed for {symbol}: {err}")
            return None

    def close_position_by_ticket(self, ticket: int) -> bool:
        """Closes an active position on MT5 by ticket number."""
        if not self.is_connected:
            self.connect()

        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            logger.warning(f"Position ticket {ticket} not found in open positions.")
            return True  # Already closed

        p = pos[0]
        close_type = mt5.ORDER_TYPE_SELL if p.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(p.symbol)
        price = tick.bid if p.type == mt5.ORDER_TYPE_BUY else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": p.symbol,
            "volume": p.volume,
            "type": close_type,
            "price": price,
            "deviation": 20,
            "magic": self.magic_number,
            "comment": "FXFX Close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Position {ticket} successfully closed on MT5.")
            return True
        return False

    def shutdown(self):
        """Disconnects cleanly from MT5."""
        mt5.shutdown()
        self.is_connected = False

