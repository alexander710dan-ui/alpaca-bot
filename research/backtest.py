#!/usr/bin/env python3
"""
Honest backtester for the MoE strategy — imports moe_core, the SAME code the live bot trades.

Modeled costs:
  - 5bp per side on all turnover (slippage + spread; liquid ETFs/megacaps at 11am ET)
  - margin financing on gross exposure above 1x at 13-week T-bill (^IRX) + 150bp
  - dividends included (adjusted-close returns)
Not modeled: taxes, SPY short-borrow (~0.3%/yr; crash expert is rarely active).

Validation protocol (anti-curve-fitting):
  DEV      2011-01-01 .. 2019-12-31   — variants may be compared/chosen here
  HOLDOUT  2020-01-01 .. today        — untouched by any choice; reported once
Overlay parameters are standard textbook values, not fitted.

Usage: python3 research/backtest.py [--refresh]   (data cached in research/cache/)
"""
import sys, os, json, math, datetime, urllib.request
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import moe_core as C
import guardrails as G

CACHE=os.path.join(HERE,"cache"); os.makedirs(CACHE,exist_ok=True)
DEV_END=datetime.date(2019,12,31); EVAL_START=datetime.date(2007,1,1)   # full universe live by 2006 (DBC)

def yf(sym, refresh=False):
    fn=os.path.join(CACHE, sym.replace("^","_")+".json")
    if not refresh and os.path.exists(fn):
        return json.load(open(fn))
    import time as _time
    # range=max silently degrades to MONTHLY bars; explicit period1/period2 keeps interval=1d
    url=(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
         f"?period1=0&period2={int(_time.time())}&interval=1d")
    req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    raw=json.load(urllib.request.urlopen(req, timeout=30))
    res=raw["chart"]["result"][0]; ts=res["timestamp"]; q=res["indicators"]["quote"][0]
    adj=(res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    out=[]
    for i in range(len(ts)):
        c=q["close"][i]
        if c is None or c<=0: continue
        a=adj[i] if adj and i<len(adj) and adj[i] else c
        out.append({"t":ts[i],"c":round(c,6),"ac":round(a,6)})
    out=G.drop_partial_bar(out)
    json.dump(out, open(fn,"w"))
    return out

def load(refresh=False):
    DB={s:yf(s,refresh) for s in C.all_symbols()}
    DB={s:b for s,b in DB.items() if len(b)>=300}
    return DB, yf("^VIX",refresh), yf("^IRX",refresh)

# ---------------- engine ----------------
def pipeline(DB, VIXB, legacy, vix18=False):
    vixday={} if vix18 else {C.uday(r["t"]):r["c"] for r in VIXB}
    M=C.build_market(DB, vixday)
    D=C.expert_decisions(M)
    HELD,SER=C.expert_series(M,D,legacy=legacy)
    effS,expoS,sclS,_=C.router(M,SER,legacy=legacy)
    return M,D,HELD,SER,effS,expoS,sclS

def simulate(P, IRX, lev=1.0, max_gross=99.0, vol_target=None, dd_scale=False,
             cost_bps=5.0, fin_spread=0.015, cash_yield=False):
    """Daily net returns [(date, r)] of the levered, overlaid, cost-adjusted strategy."""
    M,D,HELD,SER,effS,expoS,sclS=P
    dl=M["dates"]; KS=list(SER)
    base=[min(lev*sclS[t]*expoS[t],max_gross)*sum(effS[t].get(k,0.0)*SER[k][t] for k in KS) for t in dl]
    m=[1.0]*len(dl)
    if vol_target:
        mv=C.vol_target_multipliers(base, target=vol_target)
        m=[a*b for a,b in zip(m,mv)]
    if dd_scale:
        md=C.dd_scale_multipliers(base)
        m=[a*b for a,b in zip(m,md)]
    irx={}; b=None
    for r in IRX: irx[C.uday(r["t"])]=r["c"]
    out=[]; Wp={}
    rate=0.0
    for i,t in enumerate(dl):
        g=min(lev*sclS[t]*expoS[t]*m[i], max_gross)
        W={}
        for k in KS:
            ek=effS[t].get(k,0.0)
            if not ek: continue
            for sym,pw in HELD[k][t].items():
                W[sym]=W.get(sym,0.0)+g*ek*pw
        rgross=sum(w*M["ARET"][s].get(t,0.0) for s,w in W.items())
        turn=sum(abs(W.get(s,0.0)-Wp.get(s,0.0)) for s in set(W)|set(Wp))
        gsum=sum(abs(w) for w in W.values())
        rate=irx.get(C.uday(t),rate) or rate
        fin=max(0.0,gsum-1.0)*((rate/100.0)+fin_spread)/252.0
        cy=max(0.0,1.0-gsum)*(rate/100.0)/252.0 if cash_yield else 0.0   # idle cash in BIL/T-bills
        out.append((C.uday(t), rgross - turn*cost_bps*1e-4 - fin + cy))
        Wp=W
    return out

def spy_bh(DB):
    A=C.build_market(DB,{})["ARET"]["SPY"]
    return [(C.uday(t),r) for t,r in sorted(A.items())]

# ---------------- metrics ----------------
def metrics(rets):
    rs=[r for _,r in rets]; n=len(rs)
    if n<50: return None
    eq=1.0; peak=1.0; mdd=0.0
    for r in rs:
        eq*=(1+r); peak=max(peak,eq); mdd=max(mdd,1-eq/peak)
    cagr=eq**(252.0/n)-1
    mu=sum(rs)/n; var=sum((r-mu)**2 for r in rs)/n; sd=var**0.5
    dn=[min(0,r) for r in rs]; dsd=(sum(d*d for d in dn)/n)**0.5
    sharpe=(mu/sd)*15.87 if sd>0 else 0.0
    sortino=(mu/dsd)*15.87 if dsd>0 else 0.0
    mo={}
    for d,r in rets:
        key=(d.year,d.month); mo[key]=mo.get(key,1.0)*(1+r)
    mrets=[v-1 for v in mo.values()]
    pos=sum(1 for x in mrets if x>0); pf=sum(x for x in mrets if x>0)/abs(sum(x for x in mrets if x<0) or 1e-9)
    return {"CAGR":cagr,"Vol":sd*15.87,"Sharpe":sharpe,"Sortino":sortino,"MaxDD":mdd,
            "WorstMo":min(mrets),"Mo+":pos/len(mrets),"PF":pf,"n_days":n,"final":eq}

def in_window(rets, a, b):
    return [(d,r) for d,r in rets if a<=d<=b]

def yearly(rets):
    y={}
    for d,r in rets: y[d.year]=y.get(d.year,1.0)*(1+r)
    return {k:v-1 for k,v in sorted(y.items())}

def fmt(name, m):
    if not m: return f"{name:34s}  (insufficient data)"
    return (f"{name:34s} {m['CAGR']*100:7.1f}% {m['Vol']*100:6.1f}% {m['Sharpe']:6.2f} {m['Sortino']:7.2f} "
            f"{m['MaxDD']*100:6.1f}% {m['WorstMo']*100:7.1f}% {m['Mo+']*100:5.0f}% {m['PF']:5.2f}")

HDR=f"{'variant':34s} {'CAGR':>7s} {'Vol':>6s} {'Sharpe':>6s} {'Sortino':>7s} {'MaxDD':>6s} {'WorstMo':>7s} {'Mo+':>5s} {'PF':>5s}"

# ---------------- main ----------------
if __name__=="__main__":
    refresh="--refresh" in sys.argv
    DB,VIXB,IRX=load(refresh)
    today=max(C.uday(r["t"]) for r in DB["SPY"])
    print(f"data: {len(DB)} symbols, SPY {len(DB['SPY'])} bars, last {today}")
    P_leg   = pipeline(DB,VIXB,legacy=True)
    P_leg18 = pipeline(DB,VIXB,legacy=True, vix18=True)
    P_fix   = pipeline(DB,VIXB,legacy=False)

    # v10: frozen config (see moe_core.V10_WEIGHTS + design_v10.py) — ETF dip, fixed weights
    Dv=C.expert_decisions(P_fix[0], div=C.ETF_DIV)
    Hv,Sv=C.expert_series(P_fix[0], Dv, legacy=False)
    ev,xv,cv,_=C.fixed_router(P_fix[0], Sv, C.V10_WEIGHTS)
    P_v10=(P_fix[0],Dv,Hv,Sv,ev,xv,cv)

    spy=spy_bh(DB)
    variants=[
        ("SPY buy & hold",                          spy),
        ("v8 legacy timing 1x (old backtest)",      simulate(P_leg,  IRX, lev=1.0)),
        ("v8 legacy + VIX=18 (as deployed) 1x",     simulate(P_leg18,IRX, lev=1.0)),
        ("v8 HONEST timing 1x",                     simulate(P_fix,  IRX, lev=1.0)),
        ("v8 HONEST 2x (gross cap 2)",              simulate(P_fix,  IRX, lev=2.0, max_gross=2.0)),
        ("v10 1x",                                  simulate(P_v10,  IRX, lev=1.0, cash_yield=True)),
        ("v10 2x (gross cap 2)",                    simulate(P_v10,  IRX, lev=2.0, max_gross=2.0, cash_yield=True)),
        ("v10 2x + volT16  << DEPLOY",              simulate(P_v10,  IRX, lev=2.0, max_gross=2.0, vol_target=0.16, cash_yield=True)),
    ]
    lines=[]
    for title,a,b in [("FULL 2007-now",EVAL_START,today),
                      ("DEV 2007-2019 incl GFC (selection allowed)",EVAL_START,DEV_END),
                      ("HOLDOUT 2020-now (untouched)",datetime.date(2020,1,1),today)]:
        lines.append(f"\n== {title} ==\n{HDR}")
        for name,rets in variants:
            lines.append(fmt(name, metrics(in_window(rets,a,b))))
    print("\n".join(lines))
    with open(os.path.join(HERE,"results.md"),"w") as f:
        f.write(f"# Backtest results (generated {today}, costs: 5bp/side + IRX+150bp financing, dividends in)\n```\n")
        f.write("\n".join(lines)+"\n```\n\n## Yearly returns: honest v8 2x vs v10 2x volT16 (deploy) vs SPY\n```\n")
        y1=yearly(in_window(variants[4][1],EVAL_START,today))
        y2=yearly(in_window(variants[7][1],EVAL_START,today))
        y3=yearly(in_window(spy,EVAL_START,today))
        f.write(f"{'year':>5s} {'v8 2x':>8s} {'v10 2x':>8s} {'SPY':>8s}\n")
        for yy in sorted(y3):
            f.write(f"{yy:>5d} {y1.get(yy,0)*100:7.1f}% {y2.get(yy,0)*100:7.1f}% {y3.get(yy,0)*100:7.1f}%\n")
        f.write("```\n")
    print(f"\nwrote {os.path.join(HERE,'results.md')}")
