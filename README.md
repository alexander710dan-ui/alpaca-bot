# Alpaca RSI-2 Bot (paper)

Autonomous mean-reversion bot. Watches a universe of leveraged ETFs, buys the oversold ones
in an uptrend (2-day RSI < 10, above 200-day average), holds several at once, sells each on
the bounce (close back above its 5-day average). **Paper money by default.**

## Install on a new Mac (one command)

```bash
git clone <YOUR_REPO_URL> alpaca-bot && cd alpaca-bot && bash setup.sh
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
