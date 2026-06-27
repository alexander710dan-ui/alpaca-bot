#!/usr/bin/env python3
"""
RSI-2 mean-reversion bot for Alpaca — PAPER (fake money) by default.
Watches the WHOLE universe at once and holds MULTIPLE positions (not one a day).

Logic each check (it loops every 15 min while the market is open):
  - EXIT  any position whose close is back above its 5-day average (the bounce = take profit).
  - ENTER any ticker that's oversold (2-day RSI < 10) AND in an uptrend (above its 200-day avg),
          most-oversold first, equal-weighted, up to MAX_POSITIONS at once.
  - Otherwise sit in cash and wait.

Keys are read from environment vars ALPACA_KEY / ALPACA_SECRET, or a local `secrets.env`
file next to this script (so they never get committed to GitHub).

Run:
  python3 alpaca_bot.py --test    # dry run: connect + show what it would trade (no orders)
  python3 alpaca_bot.py           # one real check
  python3 alpaca_bot.py --loop    # check every 15 min, autonomous (what the installer runs)
Logs are written to bot.log next to this script.
"""
import os, sys, time, json, datetime, logging, logging.handlers

# ----------------- CONFIG -----------------
PAPER         = True        # <<< fake money. Do NOT change until you've watched it work for weeks.
UNIVERSE      = ["TQQQ","SOXL","SPXL","TECL","UPRO","TNA","FAS","LABU","UDOW","DPST","NAIL","RETL","CURE","FNGU"]
MAX_POSITIONS = 6           # hold up to this many oversold names at once ("eyes on all")
RSI_BUY       = 10          # buy when 2-day RSI below this
LOOP_SECONDS  = 900         # --loop: seconds between checks (900 = 15 min)
# ------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- logging: to bot.log (rotating) AND stdout ----
log = logging.getLogger("bot"); log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S")
_fh = logging.handlers.RotatingFileHandler(os.path.join(HERE, "bot.log"), maxBytes=2_000_000, backupCount=3)
_sh = logging.StreamHandler()
for h in (_fh, _sh): h.setFormatter(_fmt); log.addHandler(h)

def load_keys():
    k = os.environ.get("ALPACA_KEY"); s = os.environ.get("ALPACA_SECRET")
    sf = os.path.join(HERE, "secrets.env")
    if (not k or not s) and os.path.exists(sf):
        for line in open(sf):
            line = line.strip()
            if line.startswith("ALPACA_KEY="):    k = line.split("=", 1)[1].strip()
            if line.startswith("ALPACA_SECRET="): s = line.split("=", 1)[1].strip()
    if not k or not s:
        log.error("No API keys found. Set ALPACA_KEY/ALPACA_SECRET or create secrets.env."); sys.exit(1)
    return k, s

API_KEY, API_SECRET = load_keys()

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

trade = TradingClient(API_KEY, API_SECRET, paper=PAPER)
data  = StockHistoricalDataClient(API_KEY, API_SECRET)

def sma(x, n): return sum(x[-n:]) / n if len(x) >= n else None
def rsi(closes, n):
    if len(closes) < n + 1: return None
    g = l = 0.0
    for i in range(len(closes) - n, len(closes)):
        ch = closes[i] - closes[i-1]; g += max(ch, 0); l += max(-ch, 0)
    if l == 0: return 100.0
    rs = (g / n) / (l / n); return 100 - 100 / (1 + rs)

def daily_closes(symbols):
    start = datetime.datetime.now() - datetime.timedelta(days=420)
    req = StockBarsRequest(symbol_or_symbols=symbols, timeframe=TimeFrame.Day, start=start)
    bars = data.get_stock_bars(req).data
    return {s: [b.close for b in bars.get(s, [])] for s in symbols}

def write_status(tag=""):
    """Snapshot account+positions to status.json so it can be auto-pushed to GitHub for review."""
    try:
        a = trade.get_account(); ps = trade.get_all_positions()
        snap = {"time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "tag": tag, "paper": PAPER,
                "equity": float(a.equity), "cash": float(a.cash),
                "positions": [{"sym": p.symbol, "qty": float(p.qty), "value": float(p.market_value),
                               "unrealized_pl": float(p.unrealized_pl)} for p in ps]}
        json.dump(snap, open(os.path.join(HERE, "status.json"), "w"), indent=1)
    except Exception as e:
        log.error(f"status write failed: {e}")

def run_once():
    clock = trade.get_clock()
    if not clock.is_open:
        log.info(f"market closed (next open {clock.next_open}); waiting."); return
    acct = trade.get_account()
    positions = {p.symbol: p for p in trade.get_all_positions()}
    held = set(positions)
    log.info(f"CHECK | equity ${float(acct.equity):,.0f} cash ${float(acct.cash):,.0f} | holding {sorted(held) or 'nothing'}")
    closes = daily_closes(UNIVERSE)

    for sym in list(held):                                  # exits first
        c = closes.get(sym, []); s5 = sma(c, 5)
        if s5 is not None and c[-1] > s5:
            trade.submit_order(MarketOrderRequest(symbol=sym, qty=abs(float(positions[sym].qty)),
                               side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
            log.info(f"  SELL {sym} (close {c[-1]:.2f} > 5dMA {s5:.2f}) -> took the bounce"); held.discard(sym)

    candidates = []
    for sym in UNIVERSE:
        if sym in held: continue
        c = closes.get(sym, []); r2 = rsi(c, 2); s200 = sma(c, 200)
        if r2 is not None and s200 is not None and r2 < RSI_BUY and c[-1] > s200:
            candidates.append((r2, sym))
    candidates.sort()
    slots = MAX_POSITIONS - len(held)
    if slots > 0 and candidates:
        per = float(acct.cash) / slots * 0.98
        for r2, sym in candidates[:slots]:
            if per < 1: break
            trade.submit_order(MarketOrderRequest(symbol=sym, notional=round(per, 2),
                               side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
            log.info(f"  BUY  {sym} (RSI2 {r2:.1f} < {RSI_BUY}, above 200dMA) ~${per:,.0f}")
    else:
        log.info("  no new buys (slots full or nothing oversold-in-uptrend)")
    write_status("after-check")

def run_dry():
    acct = trade.get_account()
    positions = {p.symbol: p for p in trade.get_all_positions()}
    clock = trade.get_clock()
    log.info(f"CONNECTED to Alpaca PAPER (market {'OPEN' if clock.is_open else 'closed'})")
    log.info(f"  equity ${float(acct.equity):,.2f} cash ${float(acct.cash):,.2f} | holding {sorted(positions) or 'nothing'}")
    closes = daily_closes(UNIVERSE); buys = []
    for sym in UNIVERSE:
        c = closes.get(sym, [])
        if len(c) < 201: log.info(f"  {sym:6s} (no data)"); continue
        r2 = rsi(c, 2); s200 = sma(c, 200); s5 = sma(c, 5); up = c[-1] > s200
        if sym in positions: act = "SELL (bounced)" if c[-1] > s5 else "HOLD"
        elif r2 < RSI_BUY and up: act = "*** BUY candidate ***"; buys.append((r2, sym))
        elif not up: act = "skip (below 200dMA)"
        else: act = "watch (not oversold)"
        log.info(f"  {sym:6s} last {c[-1]:>8.2f}  RSI2 {r2:>5.1f}  {('up' if up else 'down'):>4s}  {act}")
    buys.sort()
    log.info("  -> " + (f"would BUY: {', '.join(s for _,s in buys[:MAX_POSITIONS])}" if buys
                        else "nothing oversold-in-uptrend; would hold cash"))
    write_status("dry")

if __name__ == "__main__":
    if "--test" in sys.argv or "--dryrun" in sys.argv:
        run_dry()
    elif "--loop" in sys.argv:
        log.info(f"=== bot started (loop every {LOOP_SECONDS//60} min, PAPER={PAPER}) ===")
        while True:
            try: run_once()
            except Exception as e: log.error(f"error: {e}")
            time.sleep(LOOP_SECONDS)
    else:
        run_once()
