#!/bin/bash
# Two-way GitHub sync, run by launchd every 30 min:
#   - pull any code updates I push (git pull)
#   - push the bot's bot.log + status.json so they can be reviewed remotely
# secrets.env is gitignored, so keys never leave the machine.
cd "$(dirname "$0")" || exit 0
git pull --rebase --autostash -q >> sync.log 2>&1 || true

# --- ZOMBIE KILL (2026-07-26): this Mac came back online on Jul 21 and launchd auto-started
# the RETIRED RSI2 trader (alpaca_bot.py --loop), which then traded the shared account
# (orphan TQQQ sells Jul 22). Permanently unload it; the v12 cloud bots own this account.
if [ ! -f "$HOME/.alpacabot_rsi2_killed" ]; then
  launchctl unload "$HOME/Library/LaunchAgents/com.alpacabot.daily.plist" 2>/dev/null || true
  launchctl remove com.alpacabot.daily 2>/dev/null || true
  pkill -f "alpaca_bot.py" 2>/dev/null || true
  echo "$(date '+%Y-%m-%d %H:%M:%S')  [sync] RETIRED RSI2 BOT KILLED on this host (launchd unloaded, process terminated)" >> bot.log
  touch "$HOME/.alpacabot_rsi2_killed"
fi
pkill -f "alpaca_bot.py --loop" 2>/dev/null || true   # keep swatting strays every sync
git add -f bot.log status.json >> sync.log 2>&1 || true
if ! git diff --cached --quiet 2>/dev/null; then
  git commit -q -m "auto: bot status $(date '+%Y-%m-%d %H:%M')" >> sync.log 2>&1 || true
  git push -q >> sync.log 2>&1 || true
fi
