# FXFX - Institutional Zero-Indicator Algorithmic Forex Trading

Quantitative, zero-indicator multi-strategy portfolio engine engineered for 24/5 live execution and automated Telegram alerts.

---

## Performance Highlights (Out-Of-Sample Validation)

| Rank | Strategy | Pair | Key Parameters | Out-of-Sample Win Rate | Profit Factor | Sharpe Ratio | Max Drawdown |
|:---:|---|---|---|:---:|:---:|:---:|:---:|
| **#1** | **London ORB** | **EUR/JPY (15m)** | Buffer: 15 pips, 1.5 R:R, Mid SL | **71.43%** | **10.39** | **3.97** | **0.31%** |
| **#2** | **London ORB** | **GBP/USD (15m)** | Buffer: 12 pips, 2.5 R:R, Mid SL | **62.50%** | **6.61** | **4.23** | **0.70%** |
| **#3** | **Turtle Soup Sweep** | **USD/CAD (15m)** | Lookback: 15, Buffer: 5 pips, 2.0 R:R | **69.23%** | **6.34** | **5.45** | **1.30%** |
| **#4** | **London ORB** | **EUR/USD (15m)** | Buffer: 5 pips, 1.5 R:R, Boundary SL | **76.92%** | **5.56** | **7.28** | **1.06%** |
| **#5** | **Turtle Soup Sweep** | **EUR/JPY (15m)** | Lookback: 40, Buffer: 5 pips, Wick $\ge 60\%$ | **75.00%** | **5.50** | **5.83** | **1.04%** |
| **#8** | **Variance Ratio MR** | **EUR/USD (1h)** | Lo-MacKinlay $VR < 0.80$, $Z \ge 2.3$ | **42.96%** | **1.28** | **0.72** | **8.56%** |

---

## Core Philosophy: Zero Indicators

No moving averages, RSI, MACD, or Bollinger Bands. The edge is derived purely from:
1. **Institutional Market Microstructure & Session Liquidity**: Asian session accumulation breaks (London ORB) and retail stop-cluster sweeps with wick absorption (Turtle Soup).
2. **Mathematical Sub-Diffusion**: Lo & MacKinlay Variance Ratio tests rejecting random walk behavior on EUR/USD.
3. **Cross-Asset Microstructure Divergence**: Lead-lag order flow failure between correlated currency pairs (EUR/USD vs GBP/USD).
4. **Strict No-Lookahead Bias**: Bar $t$ close signal $\to$ Bar $t+1$ Open execution with conservative intrabar resolution and live broker spreads deducted.

---

## Project Structure

```
FXFX/
├── .github/workflows/
│   └── forex_monitor.yml       # Automated 15-minute GitHub Actions runner
├── data/                       # Historical & live Parquet/CSV data
├── deploy/
│   └── setup_vps.sh            # One-click Ubuntu systemd daemon deployment
├── results/                    # Optimization grid results and discovery leaderboards
├── scripts/
│   ├── pair_telegram.py        # Telegram pairing wizard
│   └── show_top_trades.py      # Extracts detailed trade logs for Top Ranks
├── src/
│   ├── strategies/             # Zero-indicator strategy implementations
│   ├── backtester.py           # Institutional friction & no-lookahead engine
│   ├── data_manager.py         # Multi-year data pipeline
│   ├── live_engine.py          # 24/5 multi-strategy execution engine
│   ├── metrics.py              # Quantitative risk-adjusted performance metrics
│   └── telegram_notifier.py    # Instant Telegram trade alert engine
├── Dockerfile                  # Container definition for cloud deployment
├── docker-compose.yml          # Production Docker compose
└── requirements.txt            # Python dependencies
```

---

## 24/5 Deployment via GitHub Actions

This repository is configured to run automatically every 15 minutes via GitHub Actions:

1. In this repository, navigate to **Settings** $\to$ **Secrets and variables** $\to$ **Actions**.
2. Add your secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. Under **Settings** $\to$ **Actions** $\to$ **General** $\to$ **Workflow permissions**, grant **Read and write permissions**.
4. The workflow will automatically run every 15 minutes Monday through Friday, check all 8 strategies on the latest closed candle, and send instant alerts to your Telegram bot.
