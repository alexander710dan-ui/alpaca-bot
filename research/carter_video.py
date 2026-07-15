#!/usr/bin/env python3
"""
Viability test: "How I Built 2 Trading Bots With Claude That Made Me $13,364" (Alex Carter).

Strategy 1 (claimed 92% win): BB(30,2) + RSI(14) — long close<lowerBB & RSI<30,
  short close>upperBB & RSI>70. Video states NO exit; we grant it the canonical
  mean-reversion exit (RSI back through 50) and also test the validated variant
  (+200MA trend filter, long-only). Daily bars, close-based entries filled next bar,
  costs 5bp/side equities, 25bp/side crypto.
Strategy 2: Donchian(96) breakout + LWTI(25,20) green/red + volume>SMA30 confirm,
  5-minute BTC/ETH, stop = mid-channel, TP = 2R, intrabar stop-first. Futures costs
  5bp/side + 2bp slippage. LWTI implemented per the public TradingView script
  (RMA(close-close[n],n)/RMA(ATR n,n) scaled to 50, SMA-20 smoothed; green = >50 & rising).

Gauntlet: avg %/trade net, win rate, and permutation p vs 200 matched-random entry sets
(same number of trades, same holding-duration distribution / same stop-TP geometry).
"""
import sys, os, json, math, random, datetime, urllib.request
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import moe_core as C
from backtest import load, yf

def rsi14(c,n=14):
    return C.RSI(c,n)

# ---------------- strategy 1: daily BB+RSI ----------------
def bb(c,n=30,k=2.0):
    m=C.SMA(c,n); lo=[None]*len(c); hi=[None]*len(c)
    for i in range(n-1,len(c)):
        mu=m[i]; sd=(sum((c[j]-mu)**2 for j in range(i-n+1,i+1))/n)**0.5
        lo[i]=mu-k*sd; hi[i]=mu+k*sd
    return m,lo,hi

def strat1_trades(bars, side="long", trend_filter=False, cost=5e-4):
    c=[b["c"] for b in bars]; a=[b.get("ac",b["c"]) for b in bars]
    m,lo,hi=bb(c); r=rsi14(c); s200=C.SMA(c,200)
    trades=[]; i=0; n=len(c)
    while i<n-2:
        sig=False
        if side=="long" and lo[i] and r[i] is not None and c[i]<lo[i] and r[i]<30:
            sig=not trend_filter or (s200[i] and c[i]>s200[i])
        if side=="short" and hi[i] and r[i] is not None and c[i]>hi[i] and r[i]>70:
            sig=True
        if sig:
            e=i+1                                     # enter next bar (close-based, no lookahead)
            j=e+1
            while j<n-1 and r[j] is not None and ((side=="long" and r[j]<50) or (side=="short" and r[j]>50)) and j-e<40:
                j+=1
            ret=(a[j]/a[e]-1) if side=="long" else (a[e]/a[j]-1)
            trades.append((e,j-e,ret-2*cost))
            i=j
        else: i+=1
    return trades,n

def perm_p(trades, bars, side, n_perm=200, seed=7):
    """matched random: same trade count, same duration distribution, random entries."""
    a=[b.get("ac",b["c"]) for b in bars]; n=len(a)
    if not trades: return 1.0
    real=sum(t[2] for t in trades)/len(trades)
    durs=[t[1] for t in trades]; rng=random.Random(seed); beat=0
    for _ in range(n_perm):
        tot=0
        for d in durs:
            e=rng.randrange(1,n-d-1)
            r=(a[e+d]/a[e]-1)
            tot+= r if side=="long" else -r
        if tot/len(durs)>=real: beat+=1
    return beat/n_perm

# ---------------- strategy 2: 5-min Donchian+LWTI+volume ----------------
def binance(sym, interval="5m", batches=30):
    out=[]; end=None
    for _ in range(batches):
        u=f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit=1000"
        if end: u+=f"&endTime={end}"
        d=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"}),timeout=20))
        if not d: break
        out=d+out; end=d[0][0]-1
    return [{"t":k[0]//1000,"o":float(k[1]),"h":float(k[2]),"l":float(k[3]),"c":float(k[4]),"v":float(k[5])} for k in out]

def rma(x,n):
    out=[None]*len(x); s=None
    for i,v in enumerate(x):
        if v is None: continue
        s=v if s is None else (s*(n-1)+v)/n
        out[i]=s
    return out

def lwti(bars,n=25,sm=20):
    c=[b["c"] for b in bars]
    diff=[None]*len(c); tr=[None]*len(c)
    for i in range(len(c)):
        if i>=n: diff[i]=c[i]-c[i-n]
        if i>=1: tr[i]=max(bars[i]["h"]-bars[i]["l"],abs(bars[i]["h"]-c[i-1]),abs(bars[i]["l"]-c[i-1]))
    num=rma(diff,n); den=rma(tr,n)
    raw=[(50*num[i]/den[i]+50) if (num[i] is not None and den[i]) else None for i in range(len(c))]
    out=[None]*len(c)
    for i in range(len(c)):
        w=[raw[j] for j in range(max(0,i-sm+1),i+1) if raw[j] is not None]
        if len(w)==sm: out[i]=sum(w)/sm
    return out

def strat2_trades(bars, cost=7e-4, rr=2.0, don=96, volma=30):
    hi=[b["h"] for b in bars]; lo=[b["l"] for b in bars]; c=[b["c"] for b in bars]; v=[b["v"] for b in bars]
    lw=lwti(bars); vma=C.SMA(v,volma)
    n=len(bars); trades=[]; i=don+30
    while i<n-2:
        du=max(hi[i-don:i]); dl=min(lo[i-don:i]); mid=(du+dl)/2
        long_sig = c[i]>=du and lw[i] and lw[i-1] and lw[i]>50 and lw[i]>lw[i-1] and vma[i] and v[i]>vma[i] and c[i]>bars[i]["o"]
        short_sig= c[i]<=dl and lw[i] and lw[i-1] and lw[i]<50 and lw[i]<lw[i-1] and vma[i] and v[i]>vma[i] and c[i]<bars[i]["o"]
        if long_sig or short_sig:
            e=i+1; px=bars[e]["o"]                     # fill next bar open
            if long_sig:
                stop=mid; tp=px+rr*(px-stop)
                if stop>=px: i+=1; continue
            else:
                stop=mid; tp=px-rr*(stop-px)
                if stop<=px: i+=1; continue
            j=e; ret=None
            while j<n-1:
                j+=1
                if long_sig:
                    if lo[j]<=stop: ret=stop/px-1; break        # stop-first (conservative)
                    if hi[j]>=tp: ret=tp/px-1; break
                else:
                    if hi[j]>=stop: ret=px/stop-1; break
                    if lo[j]<=tp: ret=px/tp-1; break
                if j-e>500: ret=(c[j]/px-1)*(1 if long_sig else -1); break
            if ret is None: break
            trades.append((e,j-e,ret-2*cost,1 if long_sig else -1,px,stop,tp))
            i=j
        else: i+=1
    return trades,n

def perm_p2(trades, bars, n_perm=200, seed=11):
    """matched random: same count, SAME stop/TP geometry (risk % sampled from real trades)."""
    if not trades: return 1.0
    real=sum(t[2] for t in trades)/len(trades)
    hi=[b["h"] for b in bars]; lo=[b["l"] for b in bars]; c=[b["c"] for b in bars]
    n=len(bars); rng=random.Random(seed); beat=0
    geoms=[(abs(t[4]-t[5])/t[4], t[3]) for t in trades]      # (risk fraction, direction)
    for _ in range(n_perm):
        tot=0
        for riskf,dr in geoms:
            e=rng.randrange(100,n-600); px=bars[e]["o"]
            stop=px*(1-riskf) if dr>0 else px*(1+riskf)
            tp=px*(1+2*riskf) if dr>0 else px*(1-2*riskf)
            j=e; r=0
            while j<n-1:
                j+=1
                if dr>0:
                    if lo[j]<=stop: r=stop/px-1; break
                    if hi[j]>=tp: r=tp/px-1; break
                else:
                    if hi[j]>=stop: r=px/stop-1; break
                    if lo[j]<=tp: r=px/tp-1; break
                if j-e>500: r=(c[j]/px-1)*dr; break
            tot+=r-14e-4
        if tot/len(geoms)>=real: beat+=1
    return beat/n_perm

def summarize(name,trades,p):
    if not trades: print(f"  {name}: NO TRADES"); return
    rs=[t[2] for t in trades]; w=sum(1 for r in rs if r>0)
    print(f"  {name}: {len(rs)} trades | win {w/len(rs)*100:.0f}% | avg {sum(rs)/len(rs)*100:+.3f}%/trade | "
          f"total {sum(rs)*100:+.1f}% | p_vs_random={p:.3f} {'<-- FAILS' if p>0.05 else '<-- passes'}")

if __name__=="__main__":
    DB,VIXB,IRX=load()
    print("== STRATEGY 1: BB(30,2)+RSI(14), daily, exit RSI-cross-50 (video gives no exit) ==")
    btc=yf("BTC-USD"); eth=yf("ETH-USD")
    for nm,bars,cost in [("BTC",btc,25e-4),("ETH",eth,25e-4),("SPY",DB["SPY"],5e-4),("QQQ",DB["QQQ"],5e-4)]:
        for side in ("long","short"):
            tr,_=strat1_trades(bars,side=side)
            summarize(f"{nm} {side} (as taught)",tr,perm_p(tr,bars,side))
        tr,_=strat1_trades(bars,side="long",trend_filter=True)
        summarize(f"{nm} long +200MA filter",tr,perm_p(tr,bars,"long"))
    print("\n== STRATEGY 2: Donchian(96)+LWTI+vol, 5-min, stop=mid, TP=2R ==")
    for sym in ("BTCUSDT","ETHUSDT"):
        bars=binance(sym)
        days=(bars[-1]["t"]-bars[0]["t"])/86400
        print(f"  {sym}: {len(bars)} 5-min bars ({days:.0f} days)")
        tr,_=strat2_trades(bars)
        summarize(f"{sym} scalper",tr,perm_p2(tr,bars))
        if tr:
            longs=[t for t in tr if t[3]>0]
            print(f"    longs {len(longs)}, shorts {len(tr)-len(longs)} | worst {min(t[2] for t in tr)*100:+.2f}% | best {max(t[2] for t in tr)*100:+.2f}%")
