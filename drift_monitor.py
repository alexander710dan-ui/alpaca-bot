#!/usr/bin/env python3
"""
Live-vs-engine drift monitor — weekly scientific check that the ACCOUNT is doing what the
ENGINE says the strategy should do.

Rebuilds the deployed mix's expected daily returns from fresh data (same code path as the
backtest: research/goal_charts.build), pulls the account's actual daily returns, aligns the
last ~15 common trading days (trying +/-1-day shifts — Alpaca stamps sessions oddly), and
alerts (exit 1 -> CI failure -> email) when live behavior stops tracking the engine:
  - correlation < 0.4  (book no longer resembles the strategy), or
  - cumulative gap > 3% over the window (execution slippage / decay / silent breakage).
Some tracking error is NORMAL (11am entries vs close-to-close engine convention).
"""
import os, sys, json, math, datetime, urllib.request
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE,"research"))

WINDOW=15; MIN_DAYS=8; MAX_CUM_GAP=0.03; MIN_CORR=0.4

def keys():
    k=os.environ.get("ALPACA_KEY"); s=os.environ.get("ALPACA_SECRET"); sf=os.path.join(HERE,"secrets.env")
    if (not k or not s) and os.path.exists(sf):
        for line in open(sf):
            if line.startswith("ALPACA_KEY="): k=line.split("=",1)[1].strip()
            if line.startswith("ALPACA_SECRET="): s=line.split("=",1)[1].strip()
    return k,s

def live_returns(k,s):
    req=urllib.request.Request("https://paper-api.alpaca.markets/v2/account/portfolio/history?period=1M&timeframe=1D",
        headers={"APCA-API-KEY-ID":k,"APCA-API-SECRET-KEY":s})
    d=json.load(urllib.request.urlopen(req,timeout=30))
    rows=[(datetime.date.fromtimestamp(t),v) for t,v in zip(d["timestamp"],d["equity"]) if v]
    return [(rows[i][0], rows[i][1]/rows[i-1][1]-1) for i in range(1,len(rows))]

def main():
    k,s=keys()
    if not k: print("DRIFT: no keys"); return 1
    live=live_returns(k,s)
    from goal_charts import build                       # fresh fetch on CI (cache dir is empty)
    _,_,_,_,_,full=build()
    eng={d:r for d,r in full}
    best=None
    for shift in (-1,0,1):                              # session-stamp offset tolerance
        pairs=[]
        for d,r in live[-WINDOW-2:]:
            de=d+datetime.timedelta(days=shift)
            if de in eng: pairs.append((r,eng[de]))
        pairs=pairs[-WINDOW:]
        if len(pairs)<MIN_DAYS: continue
        n=len(pairs); ml=sum(p[0] for p in pairs)/n; me=sum(p[1] for p in pairs)/n
        cov=sum((p[0]-ml)*(p[1]-me) for p in pairs)
        vl=sum((p[0]-ml)**2 for p in pairs)**0.5; ve=sum((p[1]-me)**2 for p in pairs)**0.5
        corr=cov/(vl*ve) if vl>0 and ve>0 else 0.0
        gap=sum(p[0]-p[1] for p in pairs)
        if best is None or corr>best[0]: best=(corr,gap,n,shift)
    if best is None:
        if len(live)<MIN_DAYS:
            print(f"DRIFT: account only has {len(live)} daily returns (<{MIN_DAYS}) — too early to judge, OK")
            return 0
        print("DRIFT ALERT: live history exists but does not overlap engine dates"); return 1
    corr,gap,n,shift=best
    print(f"DRIFT: {n} days | corr {corr:+.2f} | cumulative live-engine gap {gap*100:+.2f}% | shift {shift:+d}d")
    bad=[]
    if corr<MIN_CORR: bad.append(f"correlation {corr:.2f} < {MIN_CORR}")
    if abs(gap)>MAX_CUM_GAP: bad.append(f"cumulative gap {gap*100:+.1f}% beyond {MAX_CUM_GAP*100:.0f}%")
    for b in bad: print(f"DRIFT ALERT: {b}")
    return 1 if bad else 0

if __name__=="__main__":
    sys.exit(main())
