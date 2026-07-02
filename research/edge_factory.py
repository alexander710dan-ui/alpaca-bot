#!/usr/bin/env python3
"""
EDGE FACTORY — systematic search over edges, universes, regimes and combinations.

Protocol (anti-mining, hard rules):
  DEV        2011-01-01 .. 2017-12-31   build/compare freely
  VALIDATION 2018-01-01 .. 2019-12-31   verdicts use DEV+VAL only
  HOLDOUT    2020-01-01 .. today        shown ONLY for edges that already passed DEV+VAL,
                                        and for the two final blends (one look each)
  All series: signals from COMPLETED bars only (lag-1 or calendar-known), adjusted-close
  returns (dividends), costs 5bp/side ETFs, 25bp/side crypto, financing where levered.
  Crypto edges start 2014/2017 (data birth) — noted per edge; missing days contribute 0.

Verdicts (DEV+VAL only): PASS  Sharpe>=0.35 and CAGR>0 in BOTH windows
                         MARGINAL positive both, but Sharpe<0.35 in one
                         DEAD  otherwise
Blend search: greedy enumeration (weights in 0.1 steps, <=4 components) over the top pool,
scored on DEV+VAL. Two objectives: RELIABLE (max Sharpe) and UPSIDE (max CAGR, MaxDD<=65%).
No extra margin is layered on blends (crypto is spot-only at Alpaca; leveraged ETFs already
embed 3x) — no hidden leverage.
"""
import sys, os, math, json, datetime
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import moe_core as C
from backtest import load, yf, metrics, in_window, fmt, simulate
from edges import tom_series, vrp_series
from daywins import sig_series, arr
from moonshot import trend_sleeve, combine, rolling_5y_multiples, mc_5y

DEV0=datetime.date(2011,1,3);  DEV1=datetime.date(2017,12,31)
VAL0=datetime.date(2018,1,1);  VAL1=datetime.date(2019,12,31)
H0=datetime.date(2020,1,1);    TODAY=datetime.date(2026,6,30)

def sub(rets,a,b): return [(d,r) for d,r in rets if a<=d<=b]
def sharpe_cagr_dd(rets):
    m=metrics(rets)
    return (m["Sharpe"],m["CAGR"],m["MaxDD"]) if m else (0.0,-1.0,1.0)

# ---------------- edge builders ----------------
def bh(sym):
    b=yf(sym); out=[]
    for i in range(1,len(b)):
        a0=b[i-1].get("ac",b[i-1]["c"]); a1=b[i].get("ac",b[i]["c"])
        out.append((C.uday(b[i]["t"]), a1/a0-1))
    return out

def flag_series(bars, flag_next, exec_bars=None, cost=5.0):
    """hold during bar i iff flag_next(i-1) — calendar/lagged by construction."""
    return sig_series(bars, flag_next, exec_bars, cost_bps=cost)

def window_flags(bars, months=None, last_n=0, first_n=0):
    days=[C.uday(r["t"]) for r in bars]; n=len(days)
    mo=[d.month for d in days]
    first=[0]*n; k=0
    for i in range(n):
        k=1 if (i==0 or mo[i]!=mo[i-1]) else k+1
        first[i]=k
    rem=[0]*n; k=0
    for i in range(n-1,-1,-1):
        k=0 if (i==n-1 or mo[i]!=mo[i+1]) else k+1
        rem[i]=k
    def f(i):
        if months and mo[i] not in months: return False
        return (last_n and rem[i]<last_n) or (first_n and first[i]<=first_n)
    return f

def rotation(DB, syms, top=2, weekly=True, cost=5.0):
    """top-N by 63d momentum, above own 200dma; rebalance Mondays (weekly) or month-turn."""
    spine=DB["SPY"]; MOMS={}; SMAS={}; IDX={}
    for s in syms:
        if s not in DB: continue
        b=DB[s]; c=[r["c"] for r in b]
        sm=C.SMA(c,200); IDX[s]={r["t"]:i for i,r in enumerate(b)}
        MOMS[s]={b[i]["t"]:c[i]/c[i-63]-1 for i in range(63,len(b))}
        SMAS[s]={b[i]["t"]:sm[i] for i in range(len(b))}
    hold={}; prev={}; out=[]; pm=None
    for i in range(1,len(spine)):
        t=spine[i]["t"]; tp=spine[i-1]["t"]; d=C.uday(t)
        turn = d.weekday()==0 if weekly else d.month!=pm
        pm=d.month
        if turn or not hold:
            el=[]
            for s in MOMS:
                m=MOMS[s].get(tp); sm=SMAS[s].get(tp)
                jp=IDX[s].get(tp)
                if m is not None and sm and jp is not None and DB[s][jp]["c"]>sm and m>0: el.append((m,s))
            el.sort(reverse=True)
            hold={s:1.0/max(1,len(el[:top])) for _,s in el[:top]}
        r=0.0
        for s,w in hold.items():
            j=IDX[s].get(t)
            if j and j>0:
                a0=DB[s][j-1].get("ac",DB[s][j-1]["c"]); a1=DB[s][j].get("ac",DB[s][j]["c"])
                r+=w*(a1/a0-1)
        turn_cost=sum(abs(hold.get(s,0)-prev.get(s,0)) for s in set(hold)|set(prev))*cost*1e-4
        out.append((C.uday(t), r-turn_cost)); prev=dict(hold)
    return out

def dual_momentum(DB, cost=5.0):
    """GEM: monthly, decided on prev bar: SPY-12m > BIL-12m ? max(SPY,EFA) : TLT."""
    bil=yf("BIL"); spine=DB["SPY"]
    R12={}; IDX={}
    for s,b in [("SPY",DB["SPY"]),("EFA",DB["EFA"]),("BIL",bil),("TLT",DB["TLT"])]:
        IDX[s]={r["t"]:i for i,r in enumerate(b)}
        R12[s]={b[i]["t"]:(b[i].get("ac",b[i]["c"])/b[i-252].get("ac",b[i-252]["c"])-1) for i in range(252,len(b))}
    BARS={"SPY":DB["SPY"],"EFA":DB["EFA"],"BIL":bil,"TLT":DB["TLT"]}
    hold=None; prev=None; pm=None; out=[]
    for i in range(1,len(spine)):
        t=spine[i]["t"]; tp=spine[i-1]["t"]; d=C.uday(t)
        if d.month!=pm or hold is None:
            pm=d.month
            rs=R12["SPY"].get(tp); rb=R12["BIL"].get(tp); re_=R12["EFA"].get(tp)
            if rs is not None and rb is not None:
                hold=("SPY" if (re_ is None or rs>=re_) else "EFA") if rs>rb else "TLT"
        r=0.0
        if hold:
            j=IDX[hold].get(t)
            if j and j>0:
                b=BARS[hold]; r=b[j].get("ac",b[j]["c"])/b[j-1].get("ac",b[j-1]["c"])-1
        out.append((C.uday(t), r-(cost*1e-4 if hold!=prev else 0.0))); prev=hold
    return out

def relmom_crypto(cost=25.0):
    btc=yf("BTC-USD"); eth=yf("ETH-USD")
    IDX={"B":{r["t"]:i for i,r in enumerate(btc)},"E":{r["t"]:i for i,r in enumerate(eth)}}
    M={"B":{btc[i]["t"]:btc[i]["c"]/btc[i-63]["c"]-1 for i in range(63,len(btc))},
       "E":{eth[i]["t"]:eth[i]["c"]/eth[i-63]["c"]-1 for i in range(63,len(eth))}}
    out=[]; prev=None
    for i in range(1,len(btc)):
        t=btc[i]["t"]; tp=btc[i-1]["t"]
        mb=M["B"].get(tp); me=M["E"].get(tp)
        hold=None
        if mb is not None and mb>0 and (me is None or mb>=me): hold="B"
        elif me is not None and me>0: hold="E"
        r=0.0
        if hold=="B": r=btc[i].get("ac",btc[i]["c"])/btc[i-1].get("ac",btc[i-1]["c"])-1
        elif hold=="E":
            j=IDX["E"].get(t)
            if j and j>0: r=eth[j].get("ac",eth[j]["c"])/eth[j-1].get("ac",eth[j-1]["c"])-1
        out.append((C.uday(t), r-(cost*1e-4 if hold!=prev else 0.0))); prev=hold
    return out

# ---------------- build every edge ----------------
def build_edges():
    DB,VIXB,IRX=load()
    vix3m=yf("^VIX3M"); qqq=DB["QQQ"]; spy=DB["SPY"]
    tqqq=yf("TQQQ"); uvxy=yf("UVXY"); btc=yf("BTC-USD")
    vday={C.uday(r["t"]):r["c"] for r in VIXB}; v3day={C.uday(r["t"]):r["c"] for r in vix3m}
    qc=arr(qqq); qr2=C.RSI(qc,2); qs200=C.SMA(qc,200)
    sc_=arr(spy); ss200=C.SMA(sc_,200)
    vd=[C.uday(r["t"]) for r in VIXB]; vv=[r["c"] for r in VIXB]
    v10={vd[i]:sum(vv[i-9:i+1])/10 for i in range(10,len(vv))}
    def s1(i): return qs200[i] is not None and qc[i]>qs200[i] and qr2[i] is not None and qr2[i]<5
    def s2(i): return qs200[i] is not None and qc[i]>qs200[i] and i>=3 and qc[i]<qc[i-1]<qc[i-2]<qc[i-3]
    def s3(i):
        d=C.uday(qqq[i]["t"]); v=vday.get(d); m=v10.get(d); return bool(v and m and v>1.25*m)
    def s4(i): return qs200[i] is not None and qc[i]>qs200[i] and i>=1 and qc[i]/qc[i-1]-1<-0.025
    def burst_any(i): return s1(i) or s2(i) or s3(i) or s4(i)
    def vixreg(i):
        d=C.uday(spy[i]["t"]); v=vday.get(d)
        return ss200[i] is not None and sc_[i]>ss200[i] and bool(v and v<25)
    def backwd(i):
        d=C.uday(spy[i]["t"]); v=vday.get(d); v3=v3day.get(d)
        return bool(v and v3 and v3/v<0.97)
    bwk=window_flags(btc)  # unused months; weekend flag below
    def btc_wkend(i): return C.uday(btc[i+1]["t"]).weekday()>=5 if i+1<len(btc) else False
    qe=window_flags(spy, months={3,6,9,12}, last_n=5)
    me_tlt=window_flags(DB["TLT"], last_n=3)

    M=C.build_market(DB,{C.uday(r["t"]):r["c"] for r in VIXB})
    D=C.expert_decisions(M,div=C.ETF_DIV); HH,SS=C.expert_series(M,D,legacy=False)
    def expert(k): return [(C.uday(t),SS[k][t]) for t in M["dates"]]
    e,x,cc,_=C.fixed_router(M,SS,C.V11_WEIGHTS)
    v11=simulate((M,D,HH,SS,e,x,cc),None or load()[2],lev=2.0,max_gross=2.0,vol_target=0.16,cash_yield=True)

    SECT=["XLF","XLE","XLK","XLV","XLY","XLI"]
    E={
      "spy_bh":         ("baseline: US equity beta",                bh("SPY")),
      "qqq_bh":         ("baseline: NASDAQ beta",                   bh("QQQ")),
      "v11_core_2x":    ("deployed core (multi-edge blend, 2x vt16)", v11),
      "trend2_tsmom":   ("12-1 TSMOM, inv-vol, 8 assets",           expert("trend2")),
      "dip_etf":        ("RSI2 dip-buy in uptrend, ETFs",           expert("dip")),
      "core_qqx":       ("strongest of SPY/QQQ/XLK in uptrend",     expert("core")),
      "def_gldtlt":     ("stronger of GLD/TLT by momentum",         expert("def")),
      "tom_spy":        ("turn-of-month flows, SPY",                tom_series(spy)),
      "tom_upro":       ("turn-of-month on 3x SPY",                 tom_series(yf("UPRO"))),
      "vrp_svxy":       ("short vol only in contango",              vrp_series(yf("SVXY"),VIXB,vix3m)),
      "burst_tqqq":     ("panic-day 1-day holds, 3x NASDAQ",        sig_series(qqq,burst_any,tqqq)),
      "crypto_trend":   ("BTC/ETH above 200dma, inv-vol",           trend_sleeve(["BTC-USD","ETH-USD"],fee_bps=25)),
      "eth_trend":      ("ETH above 200dma",                        trend_sleeve(["ETH-USD"],fee_bps=25)),
      "ethbtc_relmom":  ("stronger of BTC/ETH by 63d mom",          relmom_crypto()),
      "turbo_trend":    ("TQQQ/SOXL above 200dma, inv-vol",         trend_sleeve(["SOXL","TQQQ"],fee_bps=5)),
      "sector_mom_wk":  ("weekly top-2 sector momentum",            rotation(DB,SECT,weekly=True)),
      "dual_momentum":  ("GEM: SPY/EFA vs T-bills, monthly",        dual_momentum(DB)),
      "qtr_end_spy":    ("last 5 days of quarter, SPY",             flag_series(spy,qe)),
      "tlt_monthend":   ("bond month-end duration flows, TLT",      flag_series(DB["TLT"],me_tlt)),
      "btc_weekend":    ("hold BTC weekends only",                  sig_series(btc,btc_wkend,None,cost_bps=25)),
      "uvxy_backwd":    ("long vol in backwardation (crash convex)",sig_series(spy,backwd,uvxy)),
      "tqqq_vix_reg":   ("TQQQ in uptrend + VIX<25 regime",         sig_series(spy,vixreg,tqqq)),
    }
    return E, load()[2]

def verdict(rets):
    sd,cd,_=sharpe_cagr_dd(sub(rets,DEV0,DEV1))
    sv,cv,_=sharpe_cagr_dd(sub(rets,VAL0,VAL1))
    if sd>=0.35 and sv>=0.35 and cd>0 and cv>0: return "PASS"
    if cd>0 and cv>0 and min(sd,sv)>0: return "MARGINAL"
    return "DEAD"

# ---------------- blend search (DEV+VAL only) ----------------
def blend_search(pool_named):
    names=[n for n,_ in pool_named]
    dates=sorted(set(d for _,r in pool_named for d,_ in r if DEV0<=d<=VAL1))
    di={d:i for i,d in enumerate(dates)}
    V=[[0.0]*len(dates) for _ in names]
    for k,(n,r) in enumerate(pool_named):
        for d,x in r:
            i=di.get(d)
            if i is not None: V[k][i]=x
    import itertools
    def score(w):
        rs=[sum(w[k]*V[k][i] for k in range(len(names)) if w[k]) for i in range(len(dates))]
        n=len(rs); mu=sum(rs)/n; var=sum((x-mu)**2 for x in rs)/n; sd=var**0.5
        eq=1.0; pk=1.0; dd=0.0
        for x in rs:
            eq*=(1+x); pk=max(pk,eq); dd=max(dd,1-eq/pk)
        years=(dates[-1]-dates[0]).days/365.25
        cagr=eq**(1/years)-1
        sharpe=mu/sd*math.sqrt(n/years) if sd>0 else 0
        return sharpe,cagr,dd
    best_rel=(None,-9); best_up=(None,-9)
    K=len(names)
    for r_ in range(1,min(4,K)+1):
        for combo in itertools.combinations(range(K),r_):
            for parts in itertools.combinations(range(1,10),r_-1):
                cuts=(0,)+parts+(10,)
                ws=[(cuts[j+1]-cuts[j])/10 for j in range(r_)]
                w=[0.0]*K
                for j,k in enumerate(combo): w[k]=ws[j]
                s,cg,dd=score(w)
                if s>best_rel[1]: best_rel=(list(w),s,cg,dd)
                if dd<=0.65 and cg>best_up[1]: best_up=(list(w),cg,s,dd)
    return names, best_rel, best_up

if __name__=="__main__":
    E,IRX=build_edges()
    print(f"{'edge':16s} {'rationale':44s} {'DEV S/C%':>12s} {'VAL S/C%':>12s} {'verdict':>8s} {'HOLD S/C%':>12s}")
    rows=[]
    for n,(why,r) in E.items():
        v=verdict(r)
        sd,cd,ddd=sharpe_cagr_dd(sub(r,DEV0,DEV1)); sv,cv,_=sharpe_cagr_dd(sub(r,VAL0,VAL1))
        hs=""
        if v=="PASS" and n not in ("spy_bh","qqq_bh"):
            sh,ch,_=sharpe_cagr_dd(sub(r,H0,TODAY)); hs=f"{sh:.2f}/{ch*100:+.0f}"
        rows.append((sd+sv,n,why,f"{sd:.2f}/{cd*100:+.0f}",f"{sv:.2f}/{cv*100:+.0f}",v,hs))
    rows.sort(reverse=True)
    lines=[f"{'edge':16s} {'rationale':44s} {'DEV S/CAGR':>12s} {'VAL S/CAGR':>12s} {'verdict':>8s} {'HOLDOUT':>12s}"]
    for _,n,why,a,b,v,h in rows: lines.append(f"{n:16s} {why:44s} {a:>12s} {b:>12s} {v:>8s} {h:>12s}")
    print("\n".join(lines[1:]))
    passers=[(n,E[n][1]) for _,n,_,_,_,v,_ in rows if v=="PASS" and n not in ("spy_bh","qqq_bh")]
    pool=passers[:8]
    print(f"\nblend pool ({len(pool)}): {[n for n,_ in pool]}")
    names,rel,up=blend_search(pool)
    def wstr(w): return " + ".join(f"{int(x*100)}% {names[k]}" for k,x in enumerate(w) if x>0)
    print(f"RELIABLE blend (max Sharpe dev+val): {wstr(rel[0])}  S={rel[1]:.2f} CAGR={rel[2]*100:.0f}% DD={rel[3]*100:.0f}%")
    print(f"UPSIDE   blend (max CAGR, DD<=65%):  {wstr(up[0])}  CAGR={up[1]*100:.0f}% S={up[2]:.2f} DD={up[3]*100:.0f}%")
    # one holdout look + rolling + MC for the two winners
    def mk(w): return combine([r for _,r in pool],[w[k] for k in range(len(pool))])
    results={}
    for tag,w in [("RELIABLE",rel[0]),("UPSIDE",up[0])]:
        r=mk(w)
        sh,ch,dh=sharpe_cagr_dd(sub(r,H0,TODAY))
        roll=rolling_5y_multiples([(d,x) for d,x in r if d>=datetime.date(2012,1,1)])
        mc=mc_5y([(d,x) for d,x in r if d>=datetime.date(2012,1,1)])
        results[tag]=(w,r,sh,ch,dh,roll,mc)
        print(f"\n{tag}: HOLDOUT S {sh:.2f} CAGR {ch*100:+.1f}% DD {dh*100:.0f}% | "
              f"rolling5y n={len(roll)} med {sorted(roll)[len(roll)//2] if roll else 0:.1f}x worst {min(roll) if roll else 0:.2f}x | "
              f"MC med {mc['median']:.1f}x P10x {mc['P10x']*100:.1f}% P100x {mc['P100x']*100:.2f}% P(-80%) {mc['P(-80%)']*100:.1f}%")
    with open(os.path.join(HERE,"edge_factory_results.md"),"w") as f:
        f.write("# Edge factory — ranked results (protocol in edge_factory.py)\n\n```\n"+"\n".join(lines)+"\n```\n\n")
        f.write(f"## Blends (chosen on DEV+VAL only)\n- RELIABLE: {wstr(rel[0])} — dev+val Sharpe {rel[1]:.2f}\n"
                f"- UPSIDE: {wstr(up[0])} — dev+val CAGR {up[1]*100:.0f}%\n\n")
        for tag,(w,r,sh,ch,dh,roll,mc) in results.items():
            f.write(f"### {tag} — holdout Sharpe {sh:.2f}, CAGR {ch*100:+.1f}%, DD {dh*100:.0f}%\n"
                    f"rolling 5y: n={len(roll)}, median {sorted(roll)[len(roll)//2] if roll else 0:.1f}x, worst {min(roll) if roll else 0:.2f}x, "
                    f"P(>=10x) {sum(1 for m in roll if m>=10)/len(roll)*100 if roll else 0:.0f}%\n"
                    f"MC 5y: median {mc['median']:.1f}x, P(10x) {mc['P10x']*100:.1f}%, P(100x) {mc['P100x']*100:.2f}%, "
                    f"P(-80%) {mc['P(-80%)']*100:.1f}%\n\n")
    json.dump({t:{"weights":{names[k]:results[t][0][k] for k in range(len(names)) if results[t][0][k]>0},
                  "mc":results[t][6],"holdout_sharpe":results[t][2]} for t in results},
              open(os.path.join(HERE,"edge_factory_winners.json"),"w"), indent=1, default=str)
    # save winner daily series for charting
    for tag in results:
        json.dump([[str(d),x] for d,x in results[tag][1]], open(os.path.join(HERE,f"series_{tag.lower()}.json"),"w"))
    print("\nwrote edge_factory_results.md, edge_factory_winners.json, series_*.json")
