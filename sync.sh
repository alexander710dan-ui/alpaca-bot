#!/bin/bash
# Two-way GitHub sync, run by launchd every 30 min:
#   - pull any code updates I push (git pull)
#   - push the bot's bot.log + status.json so they can be reviewed remotely
# secrets.env is gitignored, so keys never leave the machine.
cd "$(dirname "$0")" || exit 0
git pull --rebase --autostash -q >> sync.log 2>&1 || true
git add -f bot.log status.json >> sync.log 2>&1 || true
if ! git diff --cached --quiet 2>/dev/null; then
  git commit -q -m "auto: bot status $(date '+%Y-%m-%d %H:%M')" >> sync.log 2>&1 || true
  git push -q >> sync.log 2>&1 || true
fi
