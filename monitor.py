#!/usr/bin/env python3
"""
Out-of-band watchdog — deliberately independent of the bot and of alpaca-py.

Reads the account with plain REST and exits NON-ZERO (so the CI run fails and GitHub emails
the operator) if anything looks wrong. It places no orders and shares no code with the bot,
so a bug that blinds the bot cannot blind the watchdog too.

Trips on: equity unreadable | daily loss > 3.5% | drawdown > 20% (warn level, inside the
bot's 25% flatten breaker) | more open orders than one rebalance could plausibly leave.
"""
import os, sys, json, urllib.request

WARN_DAILY_LOSS = 0.035
WARN_DRAWDOWN   = 0.20
MAX_OPEN_ORDERS = 30
BASE="https://paper-api.alpaca.markets"

HERE=os.path.dirname(os.path.abspath(__file__))
def keys():
    k=os.environ.get("ALPACA_KEY"); s=os.environ.get("ALPACA_SECRET"); sf=os.path.join(HERE,"secrets.env")
    if (not k or not s) and os.path.exists(sf):
        for line in open(sf):
            if line.startswith("ALPACA_KEY="): k=line.split("=",1)[1].strip()
            if line.startswith("ALPACA_SECRET="): s=line.split("=",1)[1].strip()
    return k,s

def api(path,k,s):
    req=urllib.request.Request(BASE+path, headers={"APCA-API-KEY-ID":k,"APCA-API-SECRET-KEY":s})
    return json.load(urllib.request.urlopen(req,timeout=30))

def main():
    k,s=keys()
    if not k or not s: print("MONITOR: no API keys"); return 1
    problems=[]
    try:
        acct=api("/v2/account",k,s)
        eq=float(acct["equity"]); last=float(acct.get("last_equity") or eq)
        if last>0 and eq/last-1 <= -WARN_DAILY_LOSS:
            problems.append(f"daily loss {(eq/last-1)*100:.1f}% beyond {WARN_DAILY_LOSS:.1%}")
        hist=api("/v2/account/portfolio/history?period=1A&timeframe=1D",k,s)
        eqs=[float(v) for v in hist.get("equity",[]) if v]
        peak=max(eqs+[eq]) if eqs else eq
        dd=(peak-eq)/peak if peak>0 else 0.0
        if dd>=WARN_DRAWDOWN: problems.append(f"drawdown {dd:.1%} beyond {WARN_DRAWDOWN:.0%}")
        orders=api("/v2/orders?status=open&limit=100",k,s)
        if len(orders)>MAX_OPEN_ORDERS: problems.append(f"{len(orders)} open orders (runaway?)")
        print(f"MONITOR: equity ${eq:,.0f} | day {(eq/last-1)*100:+.2f}% | dd {dd:.1%} | open orders {len(orders)}")
    except Exception as e:
        problems.append(f"cannot read account: {e}")
    for p in problems: print(f"MONITOR ALERT: {p}")
    return 1 if problems else 0

if __name__=="__main__":
    sys.exit(main())
