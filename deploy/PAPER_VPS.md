# FXFX paper trading on an AWS VPS

The paper service keeps two separate simulated USD accounts with $25,000 each. The growth book follows the five frozen strategies. The comparison book follows AUDUSD and GBPUSD. Both use 1% of current equity for new trades, permit up to two open positions, and permit one yen position at a time.

## Install

Run these commands on the VPS as your regular user.

```bash
git clone --branch main --single-branch https://github.com/don9116969-cmd/FXFX.git ~/fxfx-paper
cd ~/fxfx-paper
cp deploy/paper.env.example .env
chmod 600 .env
nano .env
bash deploy/setup_paper_vps.sh
```

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the VPS .env. Use a positive private chat ID and send the bot /start from that Telegram account. Telegram allows a single polling process per bot. Use a dedicated token or stop the older FXFX bot, scheduled GitHub job, or webhook that uses the same token. If the older VPS worker is the existing FXFX service, stop it with `sudo systemctl disable --now fxfx.service` before reusing its token.

Set `OANDA_PRACTICE_ACCOUNT_ID` and `OANDA_PRACTICE_TOKEN` for new market data. The practice account must support AUD/USD, GBP/USD, USD/JPY, EUR/JPY, and XAU/USD. Telegram status works while these fields are empty and reports that the feed is waiting. The worker only makes GET requests to the OANDA practice data API. All fills and balances are simulated locally.

The worker uses completed 15-minute midpoint candles for signals and polls observed bid/ask quotes for paper fills and exits. It discards stale quotes and takes entries only during the first 90 seconds of the next candle. Prices between polls and any simulated slippage beyond the observed quote are outside this model. The optional `PAPER_FEE_USD_PER_100K_ROUND_TURN` sets the round-turn fee per USD 100,000 of notional. The default is zero.

## Read status and update

In Telegram, send `/status` for both balances and open positions, `/trades` for recent paper exits, or `/health` for quote and candle timestamps. Quote timestamps may stop advancing when markets are closed.

```bash
sudo systemctl status fxfx-paper --no-pager
sudo journalctl -u fxfx-paper -n 50 --no-pager
```

After a future push, update and restart the existing branch checkout.

```bash
cd ~/fxfx-paper
git pull --ff-only origin main
bash deploy/setup_paper_vps.sh
```

The paper ledger lives in `/var/lib/fxfx-paper/state.json` under systemd. A restart keeps its two books, positions and Telegram offset. This ledger is separate from the tracked research data and stays on the VPS.
