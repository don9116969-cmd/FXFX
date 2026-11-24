import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from src.paper_engine import BAR, PaperEngine, PracticeFeed, fresh_quotes


class PaperTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        models = [{"pair": pair, "stop_scale": 1, "reward": None, "hold": 16}
                  for pair in ("USDJPY", "EURJPY", "AUDUSD")]
        self.definition = {"starting_equity": 25000, "risk_pct": 1, "max_active": 2,
                           "portfolios": {"Growth": models, "Comparison": [models[-1]]}}
        self.engine = PaperEngine(self.definition, self.path, 0)
        self.bucket = pd.Timestamp("2026-01-02 09:30", tz="UTC")
        index = pd.date_range(end=self.bucket - BAR, periods=550, freq=BAR)
        self.frame = pd.DataFrame(100.0, index=index, columns=["Open", "High", "Low", "Close"])
        self.frames = {m["pair"]: self.frame for m in models}

    def quotes(self, time):
        return {pair: {"time": time.isoformat(), "bid": 100.0, "ask": 100.1} for pair in self.engine.pairs}

    def test_compounding_two_books_and_restart(self):
        now = self.bucket + pd.Timedelta(seconds=3)
        fake = Mock()
        fake.signal_frame.return_value = pd.DataFrame({
            "signal": [1], "sl_price": [99], "tp_price": [102], "max_bars": [16],
        })
        with patch("src.paper_engine.MarketFeatures", return_value=fake), patch("src.paper_engine.model_side"):
            self.engine.cycle(now, self.quotes(now), self.frames)
            self.engine = PaperEngine(self.definition, self.path, 0)
            self.engine.cycle(now, self.quotes(now), self.frames)
        growth, small = self.engine.state["books"].values()
        self.assertEqual(list(growth["positions"]), ["USDJPY", "AUDUSD"])
        self.assertEqual(list(small["positions"]), ["AUDUSD"])
        self.assertEqual(len(growth["journal"]), 2)
        self.assertEqual(growth["positions"]["USDJPY"]["fill"], 100.1)
        self.assertAlmostEqual(growth["positions"]["USDJPY"]["risk"], 250)
        self.assertLess(growth["positions"]["AUDUSD"]["risk"], 250)
        self.assertAlmostEqual(small["positions"]["AUDUSD"]["risk"], 250)

    def test_stale_and_expired_quotes_do_not_open_positions(self):
        stamp = self.bucket - pd.Timedelta(minutes=1)
        self.assertEqual(fresh_quotes(self.quotes(stamp), self.bucket), {})
        now = self.bucket + pd.Timedelta(seconds=91)
        with patch("src.paper_engine.MarketFeatures") as features:
            self.engine.cycle(now, self.quotes(now), self.frames)
        features.assert_not_called()
        self.assertFalse(any(b["positions"] for b in self.engine.state["books"].values()))

    def test_practice_feed_excludes_open_candles(self):
        feed = PracticeFeed("000-000", "test")
        early, later = self.bucket - BAR, self.bucket
        bar = {"o": "100", "h": "102", "l": "99", "c": "101"}
        with patch.object(feed, "get", return_value={"candles": [
            {"time": early.isoformat(), "complete": True, "mid": bar},
            {"time": later.isoformat(), "complete": False, "mid": bar},
        ]}) as request:
            frame = feed.candles("XAUUSD", 700)
        self.assertEqual(list(frame.index), [early])
        request.assert_called_once_with("/instruments/XAU_USD/candles", granularity="M15", price="M", count=700)

    def test_exit_uses_observed_sell_quote_and_journals_fees(self):
        now = self.bucket + pd.Timedelta(seconds=3)
        book = self.engine.state["books"]["Comparison"]
        signal = pd.Series({"signal": 1, "sl_price": 99.0, "tp_price": 102.0, "max_bars": 16})
        self.engine.fee_rate = 0.000025
        self.engine.enter(book, "AUDUSD", self.quotes(now)["AUDUSD"], 1, signal, 25000, self.bucket, now)
        units = book["positions"]["AUDUSD"]["units"]
        later = now + pd.Timedelta(seconds=5)
        quote = {"time": later.isoformat(), "bid": 98.8, "ask": 99.2}
        self.engine.manage(book, {"AUDUSD": quote}, self.frames, later)
        entry, exit_event = book["journal"]
        self.assertEqual(exit_event["reason"], "stop")
        self.assertEqual(exit_event["exit_price"], 98.8)
        expected = (98.8 - 100.1) * units - entry["entry_fee"] - exit_event["exit_fee"]
        self.assertAlmostEqual(book["balance"] - 25000, expected)
        self.assertAlmostEqual(exit_event["pnl"], expected)

    def test_telegram_only_answers_the_configured_private_sender(self):
        bot = Mock(chat_id=10)
        bot.call.return_value = [
            {"update_id": 1, "message": {"text": "/status", "from": {"id": 11}, "chat": {"id": 11, "type": "private"}}},
            {"update_id": 2, "message": {"text": "/status", "from": {"id": 10}, "chat": {"id": 10, "type": "group"}}},
            {"update_id": 3, "message": {"text": "/status", "from": {"id": 10}, "chat": {"id": 10, "type": "private"}}},
        ]
        self.engine.poll_telegram(bot)
        bot.send.assert_called_once()
        self.assertIn("Growth", bot.send.call_args.args[0])
        self.assertEqual(json.loads(self.path.read_text())["offset"], 4)


if __name__ == "__main__":
    unittest.main()
