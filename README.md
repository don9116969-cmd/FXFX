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

## 24/5 Deployment & Cron Triggering

### Option A: Trigger GitHub Actions via cron-job.org (Eliminate Action Delays)

GitHub Actions scheduled crons (`cron: '*/15 * * * 1-5'`) are prone to 15–45 minute queue delays during peak GitHub traffic. You can trigger GitHub Actions **instantly on the exact minute** for free using [cron-job.org](https://cron-job.org/en/):

1. **Generate a GitHub Personal Access Token (PAT):**
   - Go to GitHub $\to$ **Settings** $\to$ **Developer settings** $\to$ **Personal access tokens** $\to$ **Tokens (classic)**.
   - Click **Generate new token (classic)**.
   - Give it a name (e.g., `cron-job-org`) and check the **`repo`** (or **`workflow`**) scope.
   - Copy the generated token (`ghp_...`).

2. **Create a Job on cron-job.org:**
   - Sign up / Log in to [cron-job.org](https://cron-job.org/en/).
   - Click **Create Cronjob**.
   - **Title:** `FXFX Forex Monitor`
   - **URL:** `https://api.github.com/repos/Vraj3005/FXFX/dispatches`
   - **Execution Schedule:** Every 15 minutes (or 5–10 mins), Mon–Fri.
   - Click **Advanced** / **HTTP Request**:
     - **Request Method:** `POST`
     - **Headers:**
       ```
       Authorization: Bearer ghp_YOUR_GITHUB_TOKEN_HERE
       Accept: application/vnd.github+json
       User-Agent: cron-job-org
       ```
     - **Request Body (JSON):**
       ```json
       {
         "event_type": "cron_trigger"
       }
       ```
   - Click **Create**.
   - Now, cron-job.org will ping GitHub every 15 minutes, triggering your workflow within **5 to 10 seconds**!

---

### Option B: Interactive Real-Time Telegram Control Panel

If you want **instant 1-second replies** to touch menu buttons (Active Trades, Strategy Profits, Check Now, Specs, History, Status):

Run the interactive listener daemon:
```bash
python scripts/run_telegram_bot.py
```
Or run the full 24/5 live monitoring daemon:
```bash
python src/live_engine.py
```
*(The live engine includes a built-in health-check server on port 8080. If hosting on Render.com or Koyeb, set cron-job.org to ping `https://your-service.onrender.com/` every 10 minutes to keep it awake 24/5 for free!)*

---

### GitHub Actions Secrets Configuration

In your repository under **Settings** $\to$ **Secrets and variables** $\to$ **Actions**:
- `TELEGRAM_BOT_TOKEN`: Your Telegram Bot API token (e.g., `8921977032:AAGtcA...`)
- `TELEGRAM_CHAT_ID`: Your personal Telegram Chat ID (e.g., `1390044763`)
- `RISK_PER_TRADE_USD`: (Optional, default `100.0`)
- `NOTIFY_CYCLE`: (Optional, set to `true` if you want a Telegram heartbeat on every check cycle)

Under **Settings** $\to$ **Actions** $\to$ **General** $\to$ **Workflow permissions**, grant **Read and write permissions** so the runner can persist trade state.

