#!/bin/bash
# One-command installer for the Alpaca bot (macOS).
# Run once on the new Mac:  bash setup.sh
# It: installs deps in a venv, asks for your PAPER keys, tests the connection,
# and registers a launchd job that runs the bot 24/7 and auto-restarts on reboot.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
echo "==> Installing into: $DIR"

# 1) Python venv + dependency
if [ ! -d venv ]; then python3 -m venv venv; fi
./venv/bin/pip install --quiet --upgrade pip alpaca-py
echo "==> Python environment ready."

# 2) Keys (stored locally in secrets.env, never committed)
if [ ! -f secrets.env ]; then
  echo "Paste your Alpaca PAPER keys (from app.alpaca.markets -> Paper -> API Keys):"
  read -p "  API Key:    " K
  read -p "  API Secret: " S
  printf "ALPACA_KEY=%s\nALPACA_SECRET=%s\n" "$K" "$S" > secrets.env
  chmod 600 secrets.env
  echo "==> Saved secrets.env (kept out of git)."
fi

# 3) Connection test
echo "==> Testing connection..."
./venv/bin/python3 alpaca_bot.py --test

# 4) launchd job: runs on login, restarts on crash, survives reboot
LABEL="com.alpacabot.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$DIR/venv/bin/python3</string>
    <string>$DIR/alpaca_bot.py</string>
    <string>--loop</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DIR/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$DIR/launchd.err.log</string>
</dict></plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

# 5) Auto-sync job: pushes logs to GitHub + pulls code updates every 30 min (if git push works)
chmod +x sync.sh
SLABEL="com.alpacabot.sync"
SPLIST="$HOME/Library/LaunchAgents/$SLABEL.plist"
cat > "$SPLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$SLABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$DIR/sync.sh</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartInterval</key><integer>1800</integer>
  <key>RunAtLoad</key><true/>
</dict></plist>
EOF
launchctl unload "$SPLIST" 2>/dev/null || true
launchctl load "$SPLIST"
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo "==> Auto-sync ON: logs push to GitHub, code updates pull in, every 30 min."
else
  echo "==> NOTE: to enable log-sync to GitHub, run:  gh auth login   (then it just works)."
fi

echo ""
echo "==> DONE. The bot is now running and will auto-start on every reboot."
echo "    Live log:   tail -f $DIR/bot.log"
echo "    Stop it:    launchctl unload $PLIST && launchctl unload $SPLIST"
echo "    Start it:   launchctl load $PLIST && launchctl load $SPLIST"
