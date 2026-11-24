"""Closed-candle signal rules shared by research and paper trading."""

import numpy as np
import pandas as pd

USD_DIRECTION = {"EURUSD": -1, "GBPUSD": -1, "AUDUSD": -1, "USDJPY": 1, "XAUUSD": -1}


def crossings(side):
    return np.where(side != np.r_[0, side[:-1]], side, 0)


class MarketFeatures:
    def __init__(self, pair, frame, universe):
        self.pair = pair
        self.frame = frame
        self.close = frame.Close
        self.index = frame.index + pd.Timedelta(minutes=15)
        previous = self.close.shift(1)
        ranges = pd.concat([frame.High - frame.Low, (frame.High - previous).abs(), (frame.Low - previous).abs()], axis=1)
        self.atr = ranges.max(axis=1).rolling(64).mean().shift(1)
        self.volatility_ratio = (self.atr / self.atr.rolling(1920).median()).to_numpy()
        self.log = np.log(self.close)
        self.sign = {n: np.sign(self.log.diff(n)).to_numpy() for n in (96, 480, 1920)}
        self.active = (self.index.dayofweek < 5) & (self.index.hour >= 6) & (self.index.hour < 16)
        self.price = self.close.to_numpy()
        self.forecasts = {}
        self.peer_move = {}
        for horizon in (8, 24, 64):
            peers = [
                (np.log(other.Close).diff(horizon) * USD_DIRECTION[symbol]).reindex(frame.index)
                for symbol, other in universe.items() if symbol in USD_DIRECTION and symbol != pair and symbol != "XAUUSD"
            ]
            self.peer_move[horizon] = (
                pd.concat(peers, axis=1).median(axis=1).to_numpy()
                if peers else np.full(len(frame), np.nan)
            )

    def at(self, zone, hour, minute):
        local = self.index.tz_convert(zone)
        return (local.hour == hour) & (local.minute == minute) & (local.dayofweek < 5)

    def forecast(self, horizon, train_days):
        key = horizon, train_days
        if key in self.forecasts:
            return self.forecasts[key]
        # Forecast normalized next-open-to-close return with a rolling, quarterly fit.
        # Use only labels whose exits occurred before the first signal of a quarter.
        volatility = self.atr.to_numpy() / self.price
        moves = [self.log.diff(n).to_numpy() / (volatility * np.sqrt(n)) for n in (4, 16, 64, 256, 960)]
        peer = [self.peer_move[n] / (volatility * np.sqrt(n)) for n in (8, 24, 64)]
        clock = self.index.hour.to_numpy()
        time_bins = [(clock < 9).astype(float), ((clock >= 9) & (clock < 13)).astype(float), (clock >= 13).astype(float)]
        features = np.column_stack([*moves, *peer, *time_bins, moves[0] * moves[3], moves[1] * peer[1],
                                    np.ones(len(clock))])
        features = np.clip(features, -5, 5)
        prediction = np.zeros(len(clock))
        opening = self.frame.Open.to_numpy()
        sample = np.flatnonzero(self.active & (self.index.minute == 0) & np.isfinite(features).all(axis=1))
        last = sample[sample + horizon < len(clock)]
        # Skip labels spanning market closures or substantial missing candles.
        consecutive = self.index[last + horizon] - self.index[last] <= pd.Timedelta(minutes=15 * (horizon + 2))
        last = last[consecutive]
        target = np.clip((np.log(self.price[last + horizon]) - np.log(opening[last + 1]))
                         / (volatility[last] * np.sqrt(horizon)), -5, 5)
        first = self.index[0].normalize() + pd.Timedelta(days=train_days)
        for date in pd.date_range(first, self.index[-1], freq="QS"):
            train = ((self.index[last] >= date - pd.Timedelta(days=train_days))
                     & (self.index[last + horizon] < date))
            test = sample[(self.index[sample] >= date) & (self.index[sample] < date + pd.DateOffset(months=3))]
            if train.sum() < 400 or not len(test):
                continue
            design = features[last[train]]
            penalty = np.eye(design.shape[1]) * 128
            penalty[-1, -1] = 0
            coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ target[train])
            prediction[test] = features[test] @ coefficients
        self.forecasts[key] = prediction
        return prediction

    def side(self, family, params):
        if family == "fix":
            zone, hour, minute = {
                "Tokyo": ("Asia/Tokyo", 10, 0),
                "Frankfurt": ("Europe/Berlin", 14, 15),
                "London": ("Europe/London", 16, 0),
            }[params["event"]]
            offset = params["offset"]
            total = hour * 60 + minute + offset
            when = self.at(zone, total // 60, total % 60)
            direction = USD_DIRECTION[self.pair] * (1 if offset < 0 else -1)
            confirming = self.close.diff(16).to_numpy() * direction
            if params["filter"] == "opposite_move":
                when = when & (confirming < -self.atr.to_numpy())
            return np.where(when, direction, 0)

        if family == "session":
            zone, hour, minute = {
                "London_open": ("Europe/London", 8, 0),
                "US_data_hour": ("America/New_York", 8, 30),
                "New_York_open": ("America/New_York", 9, 30),
            }[params["event"]]
            change = self.close.diff(params["lookback"]).to_numpy()
            side = np.sign(change).astype(float) * params["direction"]
            active = self.at(zone, hour, minute) & (np.abs(change) >= self.atr.to_numpy() * params["trigger"])
            if params["trend"]:
                active = active & (side == self.sign[params["trend"]])
            return np.where(active & np.isfinite(side), side, 0)

        if family == "gold_daypart":
            zone, hour, minute = {
                "Tokyo_open": ("Asia/Tokyo", 9, 0),
                "Tokyo_late": ("Asia/Tokyo", 11, 0),
                "London_open": ("Europe/London", 8, 0),
                "New_York_after_open": ("America/New_York", 10, 30),
            }[params["event"]]
            trend = params["trend"]
            direction = params["direction"]
            side = self.sign[trend] * direction if trend else np.full(len(self.price), direction)
            return np.where(self.at(zone, hour, minute) & np.isfinite(side), side, 0)

        if family == "adaptive":
            prediction = self.forecast(params["horizon"], params["train_days"])
            return np.where(np.abs(prediction) >= params["trigger"], np.sign(prediction), 0)

        trend = self.sign[params["trend"]] if params["trend"] else None
        if family == "breakout":
            width = params["lookback"]
            high = self.frame.High.shift(1).rolling(width).max().to_numpy()
            low = self.frame.Low.shift(1).rolling(width).min().to_numpy()
            side = np.where(self.price > high, 1, np.where(self.price < low, -1, 0))
            side = crossings(side) * params["direction"]
        elif family == "shock":
            price_move = self.close.diff(params["lookback"]).to_numpy()
            hurdle = self.atr.to_numpy() * params["trigger"]
            side = crossings(np.where(price_move > hurdle, 1, np.where(price_move < -hurdle, -1, 0)))
            side = side * params["direction"]
        elif family == "relative":
            horizon = params["lookback"]
            own = self.log.diff(horizon).to_numpy() * USD_DIRECTION[self.pair]
            residual = own - self.peer_move[horizon]
            hurdle = (self.atr.to_numpy() / self.price) * params["trigger"]
            side = crossings(np.where(residual > hurdle, 1, np.where(residual < -hurdle, -1, 0)))
            side = side * params["direction"] * USD_DIRECTION[self.pair]
        else:
            raise ValueError(family)
        valid = self.active if trend is None else self.active & (side == trend)
        return np.where(valid, side, 0)

    def signal_frame(self, side, stop_scale, reward=None, hold=32):
        # Floor stop widths to constrain the exposure implied by $250 of signal risk.
        minimum = 0.0020 if self.pair == "XAUUSD" else 0.0010
        distance = np.maximum(self.atr.to_numpy() * stop_scale, self.price * minimum)
        side = np.where(np.isfinite(distance), side, 0).astype(int)
        stop = self.price - side * distance
        target = np.nan if reward is None else self.price + side * distance * reward
        return pd.DataFrame({"signal": side, "sl_price": stop, "tp_price": target, "max_bars": hold}, index=self.frame.index)


def model_side(model, market):
    side = market.side(model["family"], model["params"])
    regime = model.get("regime")
    if regime is None:
        return side
    volatility, session = regime
    ratio = market.volatility_ratio
    volatile = {
        "any": np.ones(len(side), dtype=bool),
        "calm": ratio <= 1,
        "active": ratio > 1,
        "controlled": (ratio >= 0.65) & (ratio <= 1.55),
    }[volatility]
    hours = market.index.hour
    trading = {
        "any": np.ones(len(side), dtype=bool),
        "before_noon_utc": hours < 12,
        "after_noon_utc": hours >= 12,
    }[session]
    return np.where(volatile & trading, side, 0)
