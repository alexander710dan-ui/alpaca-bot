# Alpaca trading bots (paper)

**Live bot: `moe_bot.py`** (v10 blend at 2× with a vol-target overlay), run once per trading
day by `.github/workflows/putwrite.yml`; an independent watchdog (`monitor.py`) checks the
account after each close. **Satellite: `crypto_bot.py`** — a 20%-of-equity "moon sleeve"
(BTC/ETH + TQQQ/SOXL trend, `moon.yml`, runs daily incl. weekends) with honestly-quantified
aspirational odds in `research/moonshot_results.md`; the core bot ignores its symbols. Strategy math is in `moe_core.py`, shared with the honest
backtester `research/backtest.py` (results + methodology: `research/results.md`). Safety
layers and the emergency kill switch are documented in **SAFETY.md**; order gating lives in
`guardrails.py` with tests in `tests/` (`python3 -m pytest -q tests/`). `alpaca_bot.py`
(RSI-2, below), `allweather_bot.py` and the put-write bots are **retired** — don't schedule
two bots on the same account; they fight over positions.

---

Original RSI-2 bot: watches a universe of leveraged ETFs, buys the oversold ones
in an uptrend (2-day RSI < 10, above 200-day average), holds several at once, sells each on
the bounce (close back above its 5-day average). **Paper money by default.**

## Install on a new Mac (one command)

```bash
git clone https://github.com/alexander710dan-ui/alpaca-bot.git alpaca-bot && cd alpaca-bot && bash setup.sh
```

`setup.sh` will:
- create a Python venv and install `alpaca-py`,
- ask for your Alpaca **paper** API key + secret (saved locally in `secrets.env`, never committed),
- test the connection,
- register a launchd job that runs the bot 24/7 and **auto-restarts on reboot**.

## Use it

```bash
tail -f bot.log                                   # watch what it's doing (send me this file)
python3 alpaca_bot.py --test                      # dry run: show what it would trade, no orders
launchctl unload ~/Library/LaunchAgents/com.alpacabot.daily.plist   # stop
launchctl load   ~/Library/LaunchAgents/com.alpacabot.daily.plist   # start
```

## Notes
- `PAPER = True` is hard-coded in `alpaca_bot.py`. Don't change it until you've watched it work for weeks.
- Edit `UNIVERSE` / `MAX_POSITIONS` at the top of `alpaca_bot.py` to change what it trades.
- Logs rotate automatically (`bot.log`). Grab `bot.log` anytime to review the bot's decisions.
