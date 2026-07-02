#!/usr/bin/env python3
"""
Goal charts — the three deliverables for the $1k->$100k question:

  best_reliable_5y.html   the DEPLOYED full system (60% v12 core 2x/vt16 + 20% moon
                          + 10% burst + 10% vix-regime TQQQ), 20k MC paths
  moonshot_5y.html        the highest-upside implementable sleeve (100% moon), 20k MC paths
  path_to_100k.html       per system: P($10k), P($100k), median — against the hard math:
                          100x in 5y needs 151%/yr; full-Kelly growth ceiling is
                          exp(5*Sharpe^2/2), so Sharpe >= 1.36 is REQUIRED. Bars show how
                          far each honest system is from that line and why.
"""
import sys, os, json, math, datetime
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import moe_core as C
from backtest import load, yf, metrics, in_window, fmt, HDR, simulate
from edges import vrp_series
from daywins import sig_series, arr
from moonshot import trend_sleeve, combine, rolling_5y_multiples, mc_5y, buyhold
from final_projection import mc_paths, HTML_TMPL

H0=datetime.date(2020,1,1); TODAY=datetime.date(2026,6,30); ALL0=datetime.date(2014,9,17)

def build():
    DB,VIXB,IRX=load()
    vix3m=yf("^VIX3M"); qqq=DB["QQQ"]; spy=DB["SPY"]; tqqq=yf("TQQQ")
    vday={C.uday(r["t"]):r["c"] for r in VIXB}
    qc=arr(qqq); qr2=C.RSI(qc,2); qs200=C.SMA(qc,200)
    sc=arr(spy); ss200=C.SMA(sc,200)
    vd=[C.uday(r["t"]) for r in VIXB]; vv=[r["c"] for r in VIXB]
    v10={vd[i]:sum(vv[i-9:i+1])/10 for i in range(10,len(vv))}
    def burst_any(i):
        up=qs200[i] is not None and qc[i]>qs200[i]
        d=C.uday(qqq[i]["t"]); v=vday.get(d); m=v10.get(d)
        return ((up and qr2[i] is not None and qr2[i]<5) or
                (up and i>=3 and qc[i]<qc[i-1]<qc[i-2]<qc[i-3]) or
                bool(v and m and v>1.25*m) or
                (up and i>=1 and qc[i]/qc[i-1]-1<-0.025))
    def vixreg(i):
        d=C.uday(spy[i]["t"]); v=vday.get(d)
        return ss200[i] is not None and sc[i]>ss200[i] and bool(v and v<25)
    burst=sig_series(qqq,burst_any,yf("UPRO"))
    vreg=sig_series(spy,vixreg,tqqq)
    M=C.build_market(DB,{C.uday(r["t"]):r["c"] for r in VIXB})
    D=C.expert_decisions(M,div=C.ETF_DIV); HH,SS=C.expert_series(M,D,legacy=False)
    e,x,cc,_=C.fixed_router(M,SS,C.V12_WEIGHTS)
    v12=simulate((M,D,HH,SS,e,x,cc),IRX,lev=2.0,max_gross=2.0,vol_target=0.16,cash_yield=True)
    moon=combine([trend_sleeve(["BTC-USD","ETH-USD"],fee_bps=25),
                  trend_sleeve(["SOXL","TQQQ"],fee_bps=5),
                  vrp_series(yf("SVXY"),VIXB,vix3m)],[0.5,0.3,0.2])
    full=combine([v12,moon,burst,vreg],[0.60,0.20,0.10,0.10])
    return DB,v12,moon,burst,vreg,full

def kelly_ceiling(sharpe, cap_vol=0.60):
    """(unconstrained 5y median multiple at full Kelly, constrained at implementable vol cap)"""
    g_star=sharpe*sharpe/2.0
    sig=min(max(sharpe,0.0),cap_vol)
    g_cap=sharpe*sig-sig*sig/2.0
    return math.exp(5*g_star), math.exp(5*max(0.0,g_cap))

BAR_TMPL="""<!DOCTYPE html><html><head><meta charset="utf-8"><title>What it takes to reach $100k</title>
<style>body{font-family:-apple-system,Segoe UI,sans-serif;background:#0e1117;color:#e6e6e6;margin:24px}
h1{font-size:20px}.sub{color:#9aa0a6;font-size:13px;max-width:940px;line-height:1.5}
table{border-collapse:collapse;margin-top:14px;font-size:13px}td,th{border:1px solid #2a2f3a;padding:7px 12px;text-align:right}
th{background:#161b26}td:first-child,th:first-child{text-align:left}
.req{color:#e8b339;font-weight:bold}.bad{color:#e06c75}.ok{color:#98c379}</style></head><body>
<h1>What it takes: $1,000 &rarr; $100,000 in 5 years</h1>
<div class="sub"><b>The requirement:</b> 100x in 5y = <span class="req">151%/yr CAGR</span>.
The maximum long-run growth any strategy can compound (betting optimally, full Kelly) is
Sharpe&sup2;/2 per year &mdash; so the goal REQUIRES a true out-of-sample <span class="req">Sharpe &ge; 1.36</span>
traded at full Kelly (which means routine 60&ndash;80% drawdowns and ~100%+ annualized vol,
beyond what spot crypto (1x) and 3x ETFs can even express). Every honest system below is
measured after costs, lag-1 signals, no lookahead. MC = 20,000 block-bootstrap 5y paths.</div>
__TABLE__
<div class="sub" style="margin-top:14px"><b>Reading it:</b> "Kelly ceiling" is the best MEDIAN
5y multiple the strategy's honest Sharpe could deliver with unlimited, perfectly-sized leverage;
"implementable" caps volatility at 60% (3x ETFs / spot crypto reality). The goal line is 100x.
No honest system clears it; the gap is the evidence. Raising the ceiling requires a higher true
Sharpe: more independent edges, intraday data/execution, or options convexity &mdash; not more leverage.</div>
</body></html>"""

if __name__=="__main__":
    DB,v12,moon,burst,vreg,full=build()
    systems=[
        ("DEPLOYED full (60/20/10/10)", full),
        ("v12 core alone (2x vt16)",    v12),
        ("MOON sleeve (aspirational)",  moon),
        ("burst (day-wins)",            burst),
        ("vix-regime TQQQ",             vreg),
        ("BTC buy&hold (reference)",    buyhold("BTC-USD")),
    ]
    print(HDR)
    rowdata=[]
    for name,r in systems:
        m=metrics(in_window(r,H0,TODAY)); print(fmt(f"{name} [HOLDOUT]",m))
        rr=[(d,x) for d,x in r if d>=ALL0]
        mc=mc_5y(rr); roll=rolling_5y_multiples(rr)
        ceil_u,ceil_c=kelly_ceiling(m["Sharpe"] if m else 0)
        rowdata.append((name,m,mc,roll,ceil_u,ceil_c))
        print(f"    MC: med {mc['median']:.1f}x P10k {mc['P10x']*100:5.1f}% P100k {mc['P100x']*100:5.2f}% "
              f"P(-80%) {mc['P(-80%)']*100:4.1f}% | roll5y med {sorted(roll)[len(roll)//2] if roll else 0:.1f}x "
              f"worst {min(roll) if roll else 0:.2f}x | Kelly ceiling {ceil_u:,.0f}x (impl. {ceil_c:,.0f}x)")
    # charts 1+2: fan charts
    for fname,title,series,seed in [("best_reliable_5y.html","DEPLOYED full system (60% v12 + 20% moon + 10% burst + 10% vix-regime)",full,31),
                                    ("moonshot_5y.html","100% MOON SLEEVE (highest implementable upside)",moon,37)]:
        rr=[(d,x) for d,x in series if d>=ALL0]
        pct,samples,st=mc_paths(rr,seed=seed)
        html=HTML_TMPL.replace("__PCT__",json.dumps({str(k):v for k,v in pct.items()}))\
            .replace("__SAMPLES__",json.dumps(samples))\
            .replace("__MED__",f"{st['median']*1000:,.0f}")\
            .replace("__P2__",f"{st['P2x']*100:.0f}").replace("__P3__",f"{st['P3x']*100:.0f}")\
            .replace("__P10__",f"{st['P10x']*100:.1f}").replace("__P100__",f"{st['P100x']*100:.2f}")\
            .replace("__PL__",f"{st['Ploss']*100:.0f}")\
            .replace("v11 core (80%) + moon sleeve (20%)",title)
        open(os.path.join(HERE,fname),"w").write(html)
    # chart 3: what it takes
    rows=["<table><tr><th>system (honest, OOS)</th><th>holdout Sharpe</th><th>holdout CAGR</th><th>MaxDD</th>"
          "<th>MC median 5y</th><th>P($10k)</th><th>P($100k)</th><th>Kelly ceiling</th><th>implementable</th></tr>"]
    for name,m,mc,roll,cu,ccap in rowdata:
        p100=mc['P100x']*100
        rows.append(f"<tr><td>{name}</td><td>{m['Sharpe']:.2f}</td><td>{m['CAGR']*100:+.1f}%</td>"
                    f"<td>{m['MaxDD']*100:.0f}%</td><td>{mc['median']:.1f}x</td><td>{mc['P10x']*100:.1f}%</td>"
                    f"<td class=\"{'ok' if p100>=1 else 'bad'}\">{p100:.2f}%</td>"
                    f"<td>{cu:,.0f}x</td><td>{ccap:,.0f}x</td></tr>")
    rows.append("<tr><td class='req'>REQUIRED for the goal</td><td class='req'>&ge;1.36</td><td class='req'>151%/yr</td>"
                "<td class='req'>60-80%</td><td class='req'>100x</td><td>&mdash;</td><td class='req'>&ge;50%</td><td>&mdash;</td><td>&mdash;</td></tr></table>")
    open(os.path.join(HERE,"path_to_100k.html"),"w").write(BAR_TMPL.replace("__TABLE__","".join(rows)))
    print("\nwrote best_reliable_5y.html, moonshot_5y.html, path_to_100k.html")
