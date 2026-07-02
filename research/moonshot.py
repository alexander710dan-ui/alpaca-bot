#!/usr/bin/env python3
"""
Moonshot research: what design maximizes P($1k -> $100k within 5 years) WITHOUT certain ruin?

Requirement math: 100x in 5y = 151%/yr CAGR = 92% continuous. At full-Kelly leverage the
growth rate is ~Sharpe^2/2, so you need a TRUE Sharpe >= 1.36 traded at full Kelly (with
routine 60-80% drawdowns) just to EXPECT 100x. No honest daily-bar equity strategy here has
that. The only liquid, retail-accessible assets where 100x/5y has actually occurred are
crypto — so the candidates are trend-followed crypto (cuts the -80% winters), leveraged-ETF
trend, and barbells of those with the validated v10 core.

Two honesty checks on every candidate:
  1. ROLLING WINDOWS — every historical 5y entry point: what multiple did you actually get?
  2. BLOCK-BOOTSTRAP MONTE CARLO — 20k resampled 5y paths; P(>=100x), P(>=10x), median, tails.
     Plus a HAIRCUT scenario: crypto daily returns minus 50% of historical drift, because
     2014-2021 crypto appreciation is unlikely to repeat at today's market cap.

Costs: crypto 25bp/side (Alpaca taker), ETFs 5bp/side. Signals lag 1 day. Spot only (1x).
"""
import sys, os, json, math, random, datetime, urllib.request
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import moe_core as C
from backtest import load, yf, simulate, metrics, in_window, fmt, HDR

# ---------------- sleeves ----------------
def sma_map(bars,n):
    c=[r["c"] for r in bars]; s=C.SMA(c,n)
    return {bars[i]["t"]:s[i] for i in range(len(bars))}

def trend_sleeve(coins, fee_bps, ma=200):
    """Long each asset when close>MA200 (decided at t-1), inverse-60d-vol split, else cash."""
    DB={s:yf(s) for s in coins}; DB={s:b for s,b in DB.items() if len(b)>250}
    MAS={s:sma_map(b,ma) for s,b in DB.items()}
    dates=sorted(set(t for b in DB.values() for t in (r["t"] for r in b)))
    IDX={s:{r["t"]:i for i,r in enumerate(b)} for s,b in DB.items()}
    rets={}; W_prev={}
    out=[]
    for t in dates:
        # book decided at each asset's PREVIOUS bar (honest lag)
        sig={}
        for s,b in DB.items():
            i=IDX[s].get(t)
            if i is None or i<61: continue
            pt=b[i-1]; m=MAS[s].get(pt["t"])
            if m and pt["c"]>m:
                rs=[b[j]["c"]/b[j-1]["c"]-1 for j in range(i-60,i)]
                mu=sum(rs)/len(rs); v=(sum((x-mu)**2 for x in rs)/len(rs))**0.5
                if v>1e-9: sig[s]=1.0/v
        tot=sum(sig.values()); W={s:w/tot for s,w in sig.items()} if tot else {}
        r=0.0
        for s,w in W.items():
            i=IDX[s][t]
            a0=DB[s][i-1].get("ac",DB[s][i-1]["c"]); a1=DB[s][i].get("ac",DB[s][i]["c"])
            r+=w*(a1/a0-1)
        turn=sum(abs(W.get(s,0)-W_prev.get(s,0)) for s in set(W)|set(W_prev))
        out.append((C.uday(t), r-turn*fee_bps*1e-4)); W_prev=W
    return out

def buyhold(sym):
    b=yf(sym); out=[]
    for i in range(1,len(b)):
        a0=b[i-1].get("ac",b[i-1]["c"]); a1=b[i].get("ac",b[i]["c"])
        out.append((C.uday(b[i]["t"]), a1/a0-1))
    return out

def combine(sleeves, weights):
    """Union calendar; fixed weights (≈ periodically rebalanced). Missing day = 0 for a sleeve."""
    maps=[dict(s) for s in sleeves]
    dates=sorted(set(d for m in maps for d in m))
    return [(d, sum(w*m.get(d,0.0) for w,m in zip(weights,maps))) for d in dates]

def haircut(rets, frac=0.5):
    """Remove frac of the historical mean daily drift (crypto-won't-repeat scenario)."""
    mu=sum(r for _,r in rets)/len(rets)
    return [(d, r-mu*frac) for d,r in rets]

# ---------------- honesty checks ----------------
def rolling_5y_multiples(rets):
    """Multiple achieved from every possible historical entry day, 5y hold (or None if <5y left)."""
    ds=[d for d,_ in rets]; rs=[r for _,r in rets]
    out=[]
    j=0
    for i in range(len(ds)):
        end=ds[i]+datetime.timedelta(days=1826)
        if ds[-1]<end: break
        m=1.0; j=i
        while j<len(ds) and ds[j]<end:
            m*=(1+rs[j]); j+=1
        out.append(m)
    return out

def mc_5y(rets, n_paths=20000, block=20, seed=11):
    """Moving-block bootstrap of 5y paths. Returns dict of P(target) and percentiles."""
    rs=[r for _,r in rets]
    days=len(rs); years=(rets[-1][0]-rets[0][0]).days/365.25
    per_year=days/years; horizon=int(per_year*5)
    rng=random.Random(seed); res=[]
    for _ in range(n_paths):
        m=1.0; k=0
        while k<horizon:
            st=rng.randrange(0,days-block)
            for b in range(block):
                m*=(1+rs[st+b]); k+=1
                if k>=horizon: break
            if m<=0.005: break                      # account effectively dead
        res.append(m)
    res.sort()
    def P(x): return sum(1 for v in res if v>=x)/len(res)
    def pct(q): return res[int(q*len(res))]
    return {"P100x":P(100),"P10x":P(10),"P3x":P(3),"P(loss)":1-P(1),"P(-80%)":sum(1 for v in res if v<=0.2)/len(res),
            "median":pct(0.5),"p5":pct(0.05),"p95":pct(0.95)}

def report(name, rets, f):
    ds=[d for d,_ in rets]; years=(ds[-1]-ds[0]).days/365.25
    n=len(rets); af=n/years
    rs=[r for _,r in rets]; mu=sum(rs)/n; sd=(sum((r-mu)**2 for r in rs)/n)**0.5
    eq=1.0; peak=1.0; mdd=0.0
    for r in rs:
        eq*=(1+r); peak=max(peak,eq); mdd=max(mdd,1-eq/peak)
    cagr=eq**(1/years)-1; sharpe=mu/sd*math.sqrt(af) if sd>0 else 0
    roll=rolling_5y_multiples(rets)
    mc=mc_5y(rets)
    line1=(f"{name:42s} {ds[0]} .. {ds[-1]}  CAGR {cagr*100:7.1f}%  Sharpe {sharpe:5.2f}  MaxDD {mdd*100:5.1f}%")
    if roll:
        h100=sum(1 for m in roll if m>=100)/len(roll); h10=sum(1 for m in roll if m>=10)/len(roll)
        line2=(f"    rolling 5y entries n={len(roll)}: P(>=100x) {h100*100:5.1f}%  P(>=10x) {h10*100:5.1f}%  "
               f"median {sorted(roll)[len(roll)//2]:.1f}x  worst {min(roll):.2f}x  best {max(roll):.0f}x")
    else:
        line2="    rolling 5y entries: not enough history"
    line3=(f"    MC 20k paths:  P(>=100x) {mc['P100x']*100:5.1f}%  P(>=10x) {mc['P10x']*100:5.1f}%  P(>=3x) {mc['P3x']*100:5.1f}%  "
           f"median {mc['median']:.1f}x  p5 {mc['p5']:.2f}x  P(-80%) {mc['P(-80%)']*100:4.1f}%")
    for l in (line1,line2,line3): print(l); f.write(l+"\n")

if __name__=="__main__":
    DB,VIXB,IRX=load()
    # v10 2x core (equity spine) — reuse main engine
    M=C.build_market(DB,{C.uday(r["t"]):r["c"] for r in VIXB})
    Dv=C.expert_decisions(M,div=C.ETF_DIV); Hv,Sv=C.expert_series(M,Dv,legacy=False)
    ev,xv,cv,_=C.fixed_router(M,Sv,C.V10_WEIGHTS)
    v10=simulate((M,Dv,Hv,Sv,ev,xv,cv),IRX,lev=2.0,max_gross=2.0,vol_target=0.16,cash_yield=True)

    crypto=trend_sleeve(["BTC-USD","ETH-USD"], fee_bps=25)
    btc_bh=buyhold("BTC-USD")
    tqqq=trend_sleeve(["TQQQ"], fee_bps=5)          # 3x NASDAQ, trend-gated by its own MA200
    soxl=trend_sleeve(["SOXL","TQQQ"], fee_bps=5)   # 3x semis + 3x NASDAQ, inv-vol

    out=open(os.path.join(HERE,"moonshot_results.md"),"w")
    out.write("# Moonshot designs — P($1k->$100k in 5y), honest timing & costs\n\n```\n")
    print("== Candidates (honest lag-1 timing, costs in; crypto CAGRs are HISTORICAL — see haircut) ==")
    report("BTC buy & hold", btc_bh, out)
    report("crypto trend (BTC/ETH, MA200, 1x spot)", crypto, out)
    report("crypto trend HAIRCUT50 (drift halved)", haircut(crypto), out)
    report("TQQQ trend (MA200)", tqqq, out)
    report("SOXL+TQQQ trend (MA200, inv-vol)", soxl, out)
    report("v10 2x volT16 (the validated core)", v10, out)
    print("-- barbells (fixed weights ~ rebalanced) --"); out.write("-- barbells --\n")
    report("BARBELL 85% v10 / 15% crypto trend", combine([v10,crypto],[0.85,0.15]), out)
    report("BARBELL 70% v10 / 30% crypto trend", combine([v10,crypto],[0.70,0.30]), out)
    report("BARBELL 50% v10 / 50% crypto trend", combine([v10,crypto],[0.50,0.50]), out)
    report("BARBELL 50/50 HAIRCUT50 on crypto", combine([v10,haircut(crypto)],[0.50,0.50]), out)
    report("MAX: 60% crypto tr / 40% SOXL+TQQQ tr", combine([crypto,soxl],[0.60,0.40]), out)
    report("MAX HAIRCUT50 on crypto leg", combine([haircut(crypto),soxl],[0.60,0.40]), out)
    out.write("```\n"); out.close()
    print(f"\nwrote {os.path.join(HERE,'moonshot_results.md')}")
