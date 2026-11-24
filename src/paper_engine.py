"""Two local paper books driven by read-only OANDA practice data."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import math
import os
from pathlib import Path
import time

from dotenv import load_dotenv
import numpy as np
import pandas as pd
import requests

from src.edge_signals import MarketFeatures, model_side

ROOT = Path(__file__).resolve().parents[1]
BAR = pd.Timedelta(minutes=15)
QUOTE_AGE = pd.Timedelta(seconds=30)
ENTRY_WINDOW = pd.Timedelta(seconds=90)
MIN_HISTORY = 550
OHLC = ["Open", "High", "Low", "Close"]
LOGGER = logging.getLogger("fxfx-paper")


def utcnow():
    return pd.Timestamp.now(tz="UTC")


def instrument(pair):
    return f"{pair[:3]}_{pair[3:]}"


class FeedError(Exception):
    """A market feed request did not return usable data."""


class PracticeFeed:
    endpoint = "https://api-fxpractice.oanda.com/v3"

    def __init__(self, account, token):
        self.account = account
        self.headers = {"Authorization": f"Bearer {token}"}

    def get(self, path, **params):
        try:
            response = requests.get(self.endpoint + path, params=params, headers=self.headers, timeout=(4, 8))
            if not response.ok:
                raise FeedError(f"OANDA HTTP {response.status_code}")
            return response.json()
        except (requests.RequestException, ValueError):
            raise FeedError("OANDA request failed") from None

    def prices(self, pairs):
        data = self.get(f"/accounts/{self.account}/pricing", instruments=",".join(map(instrument, pairs)))
        quotes = {}
        for row in data.get("prices", []):
            if not row.get("tradeable", row.get("status") == "tradeable") or not row.get("bids") or not row.get("asks"):
                continue
            bid, ask = float(row["bids"][0]["price"]), float(row["asks"][0]["price"])
            if math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask:
                quotes[row["instrument"].replace("_", "")] = {
                    "time": pd.Timestamp(row["time"]).isoformat(), "bid": bid, "ask": ask,
                }
        return quotes

    def candles(self, pair, count):
        rows = self.get(f"/instruments/{instrument(pair)}/candles", granularity="M15", price="M", count=count)["candles"]
        stamps, values = [], []
        for row in rows:
            if row["complete"]:
                stamps.append(row["time"])
                values.append([float(row["mid"][name]) for name in "ohlc"])
        frame = pd.DataFrame(values, index=pd.to_datetime(stamps, utc=True), columns=OHLC)
        if (not frame.index.is_unique or not frame.index.is_monotonic_increasing
                or not (frame.index == frame.index.floor("15min")).all()
                or not np.isfinite(frame.to_numpy()).all() or not frame.gt(0).all().all()
                or not frame.High.ge(frame[["Open", "Close"]].max(axis=1)).all()
                or not frame.Low.le(frame[["Open", "Close"]].min(axis=1)).all()):
            raise FeedError(f"{pair} candles are invalid")
        return frame


class Telegram:
    def __init__(self, token, chat_id):
        self.url = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id

    def call(self, method, payload):
        try:
            response = requests.post(f"{self.url}/{method}", json=payload, timeout=(3, 5))
            if not response.ok:
                LOGGER.warning("Telegram %s failed with HTTP %s", method, response.status_code)
                return None
            data = response.json()
            return data["result"] if data.get("ok") else None
        except (requests.RequestException, ValueError):
            LOGGER.warning("Telegram %s request failed", method)
            return None

    def send(self, text):
        return self.call("sendMessage", {"chat_id": self.chat_id, "text": text})


def fresh_quotes(quotes, now):
    return {pair: quote for pair, quote in quotes.items()
            if pd.Timedelta(0) <= now - pd.Timestamp(quote["time"]) <= QUOTE_AGE}


def conversion(pair, quotes):
    if not pair.endswith("JPY"):
        return 1.0
    quote = quotes.get("USDJPY")
    return (quote["bid"] + quote["ask"]) / 2 if quote else None


def closing_price(position, quote):
    return quote["bid"] if position["side"] == 1 else quote["ask"]


def gross_pnl(position, price, rate):
    return (price - position["fill"]) * position["side"] * position["units"] / rate


def equity(book, quotes):
    value = book["balance"]
    for pair, position in book["positions"].items():
        rate = conversion(pair, quotes)
        if pair not in quotes or rate is None:
            return None
        value += gross_pnl(position, closing_price(position, quotes[pair]), rate)
    return value


class PaperEngine:
    def __init__(self, definition, state_path, fee_per_100k):
        self.definition = definition
        self.path = state_path
        self.fee_rate = fee_per_100k / 200_000
        names = definition["portfolios"]
        self.state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {
            "offset": 0, "books": {name: {"balance": definition["starting_equity"], "positions": {},
                                          "seen": {}, "journal": []} for name in names},
        }
        if set(names) != set(self.state["books"]):
            raise ValueError("Saved books differ from configured paper portfolios")
        self.frames = {}
        self.marks = {}
        self.quotes = {}
        self.health = "Waiting for the first quote"
        self.last_cycle = None

    def save(self):
        temp = self.path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(self.state, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(self.path)

    @property
    def pairs(self):
        return sorted({model["pair"] for models in self.definition["portfolios"].values() for model in models})

    def cycle(self, now, quotes, frames):
        self.last_cycle = now.isoformat()
        quotes = fresh_quotes(quotes, now)
        self.quotes = quotes
        self.marks.update(quotes)
        bucket = now.floor("15min")
        previous = bucket - BAR
        complete = {pair: frame.loc[:previous] for pair, frame in frames.items()}
        ready = {pair for pair, frame in complete.items()
                 if len(frame) >= MIN_HISTORY and frame.index[-1] == previous}
        features = {}
        signals = {}
        dirty = not self.path.exists()
        for name, models in self.definition["portfolios"].items():
            book = self.state["books"][name]
            before = len(book["journal"])
            self.manage(book, quotes, complete, now)
            dirty = dirty or len(book["journal"]) != before
            if now - bucket > ENTRY_WINDOW:
                continue
            for model in models:
                pair = model["pair"]
                quote, rate = quotes.get(pair), conversion(pair, quotes)
                if pair not in ready or not quote or rate is None or pd.Timestamp(quote["time"]) < bucket:
                    continue
                if book["seen"].get(pair) == bucket.isoformat():
                    continue
                value = equity(book, quotes)
                if value is None:
                    continue
                book["seen"][pair] = bucket.isoformat()
                dirty = True
                if len(book["positions"]) >= self.definition["max_active"] or pair in book["positions"]:
                    continue
                if pair.endswith("JPY") and any(p.endswith("JPY") for p in book["positions"]):
                    continue
                key = json.dumps(model, sort_keys=True)
                if key not in signals:
                    if pair not in features:
                        features[pair] = MarketFeatures(pair, complete[pair], complete)
                    market = features[pair]
                    sides = model_side(model, market)
                    signals[key] = market.signal_frame(sides, model["stop_scale"], model["reward"], model["hold"]).iloc[-1]
                signal = signals[key]
                if signal.signal and value > 0:
                    self.enter(book, pair, quote, rate, signal, value, bucket, now)
        if dirty:
            self.save()

    def enter(self, book, pair, quote, rate, signal, value, bucket, now):
        side = int(signal.signal)
        fill = quote["ask"] if side == 1 else quote["bid"]
        stop = float(signal.sl_price)
        target = None if pd.isna(signal.tp_price) else float(signal.tp_price)
        distance = (fill - stop) * side
        exit_side = quote["bid"] if side == 1 else quote["ask"]
        if not math.isfinite(stop) or distance <= 0 or (exit_side - stop) * side <= 0 or (
            target is not None and (not math.isfinite(target) or (target - fill) * side <= 0)
        ):
            return
        risk = value * self.definition["risk_pct"] / 100
        units = risk * rate / (distance + (fill + stop) * self.fee_rate)
        fee = units * fill / rate * self.fee_rate
        position = {
            "pair": pair, "side": side, "fill": fill, "stop": stop, "target": target,
            "units": units, "entry_fee": fee, "risk": risk, "quote_to_usd_rate": rate,
            "entry_bar": bucket.isoformat(), "hold": int(signal.max_bars),
            "entry_quote": quote, "observed_utc": now.isoformat(),
        }
        book["balance"] -= fee
        book["positions"][pair] = position
        book["journal"].append({"event": "entry", **position})

    def manage(self, book, quotes, frames, now):
        for pair, position in list(book["positions"].items()):
            quote, rate = quotes.get(pair), conversion(pair, quotes)
            if not quote or rate is None or pd.Timestamp(quote["time"]) <= pd.Timestamp(position["entry_quote"]["time"]):
                continue
            price = closing_price(position, quote)
            side, target = position["side"], position["target"]
            frame = frames.get(pair)
            held = frame.index[frame.index >= pd.Timestamp(position["entry_bar"])] if frame is not None else []
            if (price - position["stop"]) * side <= 0:
                reason = "stop"
            elif target is not None and (price - target) * side >= 0:
                reason = "target"
            elif len(held) >= position["hold"] and pd.Timestamp(quote["time"]) >= held[position["hold"] - 1] + BAR:
                reason = "time"
            else:
                continue
            fee = position["units"] * price / rate * self.fee_rate
            gross = gross_pnl(position, price, rate)
            book["balance"] += gross - fee
            book["journal"].append({"event": "exit", **position, "exit_price": price, "exit_quote": quote,
                                    "exit_quote_to_usd_rate": rate, "observed_exit_utc": now.isoformat(),
                                    "exit_fee": fee, "reason": reason, "pnl": gross - fee - position["entry_fee"]})
            del book["positions"][pair]

    def status(self, command):
        lines = ["FXFX paper trading", f"Feed: {self.health}"]
        if self.last_cycle:
            lines.append(f"Last cycle UTC: {self.last_cycle}")
        if command == "/health":
            for pair in self.pairs:
                quote, frame = self.marks.get(pair), self.frames.get(pair)
                stamp = frame.index[-1].isoformat() if frame is not None and not frame.empty else "waiting"
                lines.append(f"{pair} | quote {quote['time'] if quote else 'waiting'} | candle {stamp}")
            return "\n".join(lines)
        for name, book in self.state["books"].items():
            exits = [x for x in book["journal"] if x["event"] == "exit"]
            lines.extend(["", name])
            if command == "/trades":
                lines.extend(f"{x['pair']} {x['reason']} {x['pnl']:+,.2f} USD" for x in exits[-5:])
                if not exits:
                    lines.append("No closed paper trades")
                continue
            mark = equity(book, self.quotes)
            balance = book["balance"]
            mark_text = f"{mark:,.2f} USD" if mark is not None else "waiting for fresh marks"
            lines.append(f"Cash balance {balance:,.2f} USD | Equity {mark_text}")
            lines.append(f"Closed trades {len(exits)} | Net closed P&L {sum(x['pnl'] for x in exits):+,.2f} USD")
            for p in book["positions"].values():
                lines.append(f"{p['pair']} {'BUY' if p['side'] == 1 else 'SELL'} @ {p['fill']:g} | risk {p['risk']:,.2f} USD")
            if not book["positions"]:
                lines.append("No open positions")
        return "\n".join(lines)

    def poll_telegram(self, bot):
        updates = bot.call("getUpdates", {"offset": self.state["offset"], "allowed_updates": ["message"], "timeout": 0})
        for update in updates or []:
            message = update.get("message", {})
            chat, sender = message.get("chat", {}), message.get("from", {})
            text = message.get("text", "").split()
            if (chat.get("type") == "private" and chat.get("id") == bot.chat_id == sender.get("id") and text):
                command = text[0].lower().split("@", 1)[0]
                response = self.status(command) if command in ("/status", "/trades", "/health") else (
                    "FXFX paper trading\n/status shows paper books\n/trades shows recent exits\n/health shows feed status"
                )
                if bot.send(response) is None:
                    break
            self.state["offset"] = update["update_id"] + 1
            self.save()


def refresh_candles(feed, engine, previous, current_quotes):
    needed = [pair for pair in current_quotes if pair not in engine.frames
              or engine.frames[pair].empty or engine.frames[pair].index[-1] < previous]
    if not needed:
        return []
    errors = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        pending = {}
        for pair in needed:
            frame = engine.frames.get(pair)
            count = 700 if frame is None or frame.empty or previous - frame.index[-1] > 12 * BAR else 12
            pending[pair] = pool.submit(feed.candles, pair, count)
        for pair, task in pending.items():
            existing = engine.frames.get(pair)
            try:
                frame = pd.concat([existing, task.result()])
            except (FeedError, KeyError, ValueError):
                errors.append(pair)
                continue
            engine.frames[pair] = frame.loc[~frame.index.duplicated(keep="last")].sort_index().tail(700)
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--state-dir", type=Path, default=Path(os.getenv("STATE_DIRECTORY", ROOT / ".paper-state")))
    parser.add_argument("--once", action="store_true", help="Run one live-data paper cycle")
    parser.add_argument("--check-config", action="store_true", help="Validate local settings without network calls")
    args = parser.parse_args()
    load_dotenv(args.env_file)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    token_prefix, sep, token_secret = token.partition(":")
    if not sep or not token_prefix.isdigit() or not token_secret or not chat.isdigit() or int(chat) <= 0:
        parser.error("Set TELEGRAM_BOT_TOKEN and a positive private TELEGRAM_CHAT_ID in the VPS .env")
    account, market_token = os.getenv("OANDA_PRACTICE_ACCOUNT_ID"), os.getenv("OANDA_PRACTICE_TOKEN")
    if account and not all(c in "0123456789-" for c in account):
        parser.error("Invalid OANDA_PRACTICE_ACCOUNT_ID")
    try:
        fee = float(os.getenv("PAPER_FEE_USD_PER_100K_ROUND_TURN", "0"))
    except ValueError:
        fee = math.nan
    if not math.isfinite(fee) or fee < 0:
        parser.error("PAPER_FEE_USD_PER_100K_ROUND_TURN must be a finite nonnegative number")
    if bool(account) != bool(market_token):
        parser.error("Set both OANDA practice fields or leave both empty")
    definition = json.loads((ROOT / "deploy/paper_models.json").read_text(encoding="utf-8"))
    if args.check_config:
        print("Paper settings are valid. Practice market feed is " + ("configured." if account else "waiting for credentials."))
        return
    import fcntl

    feed = PracticeFeed(account, market_token) if account and market_token else None
    bot = Telegram(token, int(chat))
    args.state_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with (args.state_dir / "lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Another paper process owns this state directory")
        engine = PaperEngine(definition, args.state_dir / "state.json", fee)
        LOGGER.info("Paper worker started with %d simulated books", len(engine.state["books"]))
        while True:
            started = time.monotonic()
            quotes = {}
            if feed:
                try:
                    quotes = feed.prices(engine.pairs)
                    good = fresh_quotes(quotes, utcnow())
                    errors = refresh_candles(feed, engine, utcnow().floor("15min") - BAR, good)
                    engine.health = f"OANDA practice | {len(good)}/{len(engine.pairs)} fresh quotes"
                    if errors:
                        engine.health += " | candle request failed for " + ", ".join(errors)
                except (FeedError, KeyError, ValueError) as error:
                    engine.health = str(error) if isinstance(error, FeedError) else "OANDA returned invalid data"
            else:
                engine.health = "Waiting for OANDA_PRACTICE_ACCOUNT_ID and OANDA_PRACTICE_TOKEN"
            engine.cycle(utcnow(), quotes, engine.frames)
            engine.poll_telegram(bot)
            if args.once:
                print(engine.status("/status"))
                return
            time.sleep(max(0.25, 5 - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
