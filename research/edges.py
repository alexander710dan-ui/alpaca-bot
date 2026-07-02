#!/usr/bin/env python3
"""
Edge lab — structural anomalies testable on daily data with a once-a-day bot.

Every edge here is DOCUMENTED in the literature for decades (not mined from this dataset),
implemented with honest timing and costs, judged on DEV (<=2019), then given ONE holdout look.

  TOM   turn-of-month: hold SPY (or UPRO) only the last 4 + first 3 trading days of each
        month (pension/payroll flows; Lakonishok-Smidt 1988, Ogden 1990). Calendar-known
        in advance -> zero lookahead by construction. ~2 round trips/month.
  VRP   volatility risk premium: hold SVXY (short vol) only while the VIX curve is in
        contango (VIX3M/VIX > 1, measured at t-1). You are selling insurance ONLY when
        the market pays a visible premium. NOTE: SVXY halved leverage after Feb-2018.
  ONI   overnight-only SPY (close->open drift): documented, but needs 2 trades/day —
        included to SHOW the costs eating it, so nobody resurrects it later.
"""
import sys, os, datetime
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import moe_core as C
from backtest import load, yf, metrics, in_window, fmt, HDR, DEV_END

def series_bh(bars):
    out=[]
    for i in range(1,len(bars)):
        a0=bars[i-1].get("ac",bars[i-1]["c"]); a1=bars[i].get("ac",bars[i]["c"])
        out.append((C.uday(bars[i]["t"]), a1/a0-1))
    return out

def tom_flags(bars, pre=4, post=3):
    """flag[i]: is bar i inside the turn-of-month window (last `pre` + first `post` t-days)."""
    mo=[C.uday(r["t"]).month for r in bars]; n=len(bars)
    first=[0]*n; k=0
    for i in range(n):
        k=1 if (i==0 or mo[i]!=mo[i-1]) else k+1
        first[i]=k
    rem=[0]*n; k=0
    for i in range(n-1,-1,-1):
        k=0 if (i==n-1 or mo[i]!=mo[i+1]) else k+1
        rem[i]=k
    return [(first[i]<=post) or (rem[i]<pre) for i in range(n)]

def tom_series(bars, cost_bps=5.0, pre=4, post=3):
    f=tom_flags(bars,pre,post); out=[]; prev=0.0
    for i in range(1,len(bars)):
        w=1.0 if f[i] else 0.0                      # membership of day i known in advance
        a0=bars[i-1].get("ac",bars[i-1]["c"]); a1=bars[i].get("ac",bars[i]["c"])
        r=w*(a1/a0-1)-abs(w-prev)*cost_bps*1e-4
        out.append((C.uday(bars[i]["t"]), r)); prev=w
    return out

def vrp_series(svxy, vix, vix3m, cost_bps=5.0, thresh=1.0):
    v={C.uday(r["t"]):r["c"] for r in vix}; v3={C.uday(r["t"]):r["c"] for r in vix3m}
    out=[]; prev=0.0
    for i in range(1,len(svxy)):
        d_prev=C.uday(svxy[i-1]["t"])
        contango=(v3.get(d_prev) or 0)/(v.get(d_prev) or 1e9)
        w=1.0 if contango>thresh else 0.0           # decided at t-1: honest
        a0=svxy[i-1].get("ac",svxy[i-1]["c"]); a1=svxy[i].get("ac",svxy[i]["c"])
        r=w*(a1/a0-1)-abs(w-prev)*cost_bps*1e-4
        out.append((C.uday(svxy[i]["t"]), r)); prev=w
    return out

def overnight_series(bars_ohlc, cost_bps=5.0):
    out=[]
    for i in range(1,len(bars_ohlc)):
        o=bars_ohlc[i].get("o")
        if not o: continue
        r=o/bars_ohlc[i-1]["c"]-1 - 2*cost_bps*1e-4   # buy close, sell open: 2 trades/day
        out.append((C.uday(bars_ohlc[i]["t"]), r))
    return out

def yf_ohlc(sym):
    import json, urllib.request, time as _t
    fn=os.path.join(HERE,"cache",sym.replace("^","_")+"_ohlc.json")
    if os.path.exists(fn): return json.load(open(fn))
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=0&period2={int(_t.time())}&interval=1d"
    raw=json.load(urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"}),timeout=30))
    res=raw["chart"]["result"][0]; ts=res["timestamp"]; q=res["indicators"]["quote"][0]
    out=[{"t":ts[i],"c":q["close"][i],"o":q["open"][i]} for i in range(len(ts)) if q["close"][i]]
    json.dump(out,open(fn,"w")); return out

if __name__=="__main__":
    DB,VIXB,IRX=load()
    vix3m=yf("^VIX3M")
    svxy=yf("SVXY")
    upro=yf("UPRO")
    spy=DB["SPY"]
    a=datetime.date(2007,1,3); h0=datetime.date(2020,1,1); today=datetime.date(2026,6,30)
    rows=[
        ("SPY buy&hold",            series_bh(spy)),
        ("TOM SPY (last4+first3)",  tom_series(spy)),
        ("TOM UPRO (3x version)",   tom_series(upro)),
        ("VRP SVXY contango-gated", vrp_series(svxy,VIXB,vix3m)),
        ("SVXY buy&hold (control)", series_bh(svxy)),
        ("overnight-only SPY",      overnight_series(yf_ohlc("SPY"))),
    ]
    for title,lo,hi in [("DEV (<=2019)",a,DEV_END),("HOLDOUT 2020+ (one look)",h0,today)]:
        print(f"\n== {title} ==\n{HDR}")
        for name,r in rows:
            print(fmt(name, metrics(in_window(r,lo,hi))))
    # in-window vs out-of-window decomposition for TOM (is the effect real in this data?)
    f=tom_flags(spy); rs=series_bh(spy)
    fl={C.uday(spy[i]["t"]):f[i] for i in range(len(spy))}
    inw=[r for d,r in rs if fl.get(d)]; outw=[r for d,r in rs if fl.get(d) is False]
    def ann(x): return (sum(x)/len(x))*252*100
    print(f"\nTOM decomposition (2007+): in-window days {len(inw)} ann.ret {ann(inw):+.1f}% | "
          f"other days {len(outw)} ann.ret {ann(outw):+.1f}%")
