#!/usr/bin/env python3
"""
Day-wins lab — event-driven 1-DAY-HOLD setups: cash most days, strike on trigger days.

Every setup: signal on COMPLETED bar t-1 -> hold instrument during day t -> out (unless the
signal fires again). Costs charged on every entry/exit (5bp/side ETFs, 25bp/side crypto).
Setups are canonical short-term patterns from the literature, not mined from this data:

  S1 panic-bounce   RSI2 < 5 in an uptrend (above 200dma)     -> long TQQQ 1 day
  S2 three-down     3 consecutive down closes in an uptrend   -> long TQQQ 1 day
  S3 vix-spike      VIX > 1.25x its 10-day average            -> long TQQQ 1 day
  S4 big-down-day   QQQ fell >2.5% yesterday, uptrend intact  -> long TQQQ 1 day
  S5 btc-burst      BTC rose >5% yesterday, above 200dma      -> long BTC 1 day (momentum)
  S6 btc-knife      BTC fell >7% yesterday                    -> long BTC 1 day (catch knife)
  BURST sleeve      TQQQ leg = any of S1-S4; BTC leg = S5; idle cash earns T-bills

Protocol as always: judge on DEV (<=2019), ONE holdout look (2020+). Per-trade expectancy
shown so a lucky compounding path can't hide a broken edge.
"""
import sys, os, datetime, math
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import moe_core as C
from backtest import load, yf, metrics, in_window, fmt, HDR, DEV_END

DEV0=datetime.date(2011,1,1); H0=datetime.date(2020,1,1); TODAY=datetime.date(2026,6,30)

def arr(bars, key="c"): return [r[key] for r in bars]
def aret(bars,i):
    a0=bars[i-1].get("ac",bars[i-1]["c"]); a1=bars[i].get("ac",bars[i]["c"])
    return a1/a0-1

def sig_series(bars, sig_at, exec_bars=None, cost_bps=5.0):
    """sig_at(i) True -> hold exec instrument during bar i+1. Returns dated net returns."""
    ex=exec_bars or bars
    idx={r["t"]:i for i,r in enumerate(ex)}
    out=[]; prev=0.0
    for i in range(1,len(bars)):
        w=1.0 if sig_at(i-1) else 0.0
        j=idx.get(bars[i]["t"])
        r=w*aret(ex,j) if (j and j>0) else 0.0
        out.append((C.uday(bars[i]["t"]), r-abs(w-prev)*cost_bps*1e-4))
        prev=w
    return out

def trade_stats(rets, lo, hi):
    """per-active-day stats within a window"""
    xs=[r for d,r in rets if lo<=d<=hi and abs(r)>1e-9]
    if not xs: return "no trades"
    wins=[x for x in xs if x>0]
    return (f"days-in {len(xs):4d} | win {len(wins)/len(xs)*100:4.0f}% | avg {sum(xs)/len(xs)*100:+.3f}%/d | "
            f"best {max(xs)*100:+.1f}% worst {min(xs)*100:+.1f}%")

if __name__=="__main__":
    DB,VIXB,IRX=load()
    qqq=DB["QQQ"]; spyb=DB["SPY"]; tqqq=yf("TQQQ"); btc=yf("BTC-USD")
    vday={C.uday(r["t"]):r["c"] for r in VIXB}

    def mk_ctx(bars):
        c=arr(bars); return c, C.RSI(c,2), C.SMA(c,200)
    qc,qr2,qs200=mk_ctx(qqq)
    bc,_,bs200=mk_ctx(btc)

    def up(i): return qs200[i] is not None and qc[i]>qs200[i]
    def s1(i): return up(i) and qr2[i] is not None and qr2[i]<5
    def s2(i): return up(i) and i>=3 and qc[i]<qc[i-1]<qc[i-2]<qc[i-3]
    vmap={r["t"]:r["c"] for r in VIXB}
    vdays=[C.uday(r["t"]) for r in VIXB]; vvals=[r["c"] for r in VIXB]
    v10={}
    for i in range(10,len(vvals)): v10[vdays[i]]=sum(vvals[i-9:i+1])/10
    def s3(i):
        d=C.uday(qqq[i]["t"]); v=vday.get(d); m=v10.get(d)
        return bool(v and m and v>1.25*m)
    def s4(i): return up(i) and i>=1 and qc[i]/qc[i-1]-1 < -0.025
    def b_up(i): return bs200[i] is not None and bc[i]>bs200[i]
    def s5(i): return b_up(i) and i>=1 and bc[i]/bc[i-1]-1 > 0.05
    def s6(i): return i>=1 and bc[i]/bc[i-1]-1 < -0.07

    rows=[
        ("S1 panic-bounce -> TQQQ",  sig_series(qqq,s1,tqqq)),
        ("S2 three-down  -> TQQQ",   sig_series(qqq,s2,tqqq)),
        ("S3 vix-spike   -> TQQQ",   sig_series(qqq,s3,tqqq)),
        ("S4 big-down    -> TQQQ",   sig_series(qqq,s4,tqqq)),
        ("S5 btc-burst   -> BTC",    sig_series(btc,s5,None,cost_bps=25)),
        ("S6 btc-knife   -> BTC",    sig_series(btc,s6,None,cost_bps=25)),
    ]
    def any14(i): return s1(i) or s2(i) or s3(i) or s4(i)
    burst_eq=sig_series(qqq,any14,tqqq)
    from moonshot import combine
    burst=combine([burst_eq, rows[4][1]],[0.5,0.5])
    rows.append(("BURST sleeve 50/50 eq/btc", burst))

    for title,lo,hi in [("DEV 2011-2019",DEV0,DEV_END),("HOLDOUT 2020+ (one look)",H0,TODAY)]:
        print(f"\n== {title} ==\n{HDR}")
        for name,r in rows:
            print(fmt(name, metrics(in_window(r,lo,hi))))
            print(f"    {trade_stats(r,lo,hi)}")
