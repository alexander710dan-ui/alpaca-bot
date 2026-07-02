#!/usr/bin/env python3
"""
FINAL strategy validation + the 5-year $1k projection chart.

Full account = 80% v11 core (2x, volT16, honest timing) + 20% moon sleeve
               (50% BTC/ETH trend + 30% TQQQ/SOXL trend + 20% contango-gated SVXY).

1. One holdout look (2020+) for the frozen v11 and moon-v2 configs.
2. 20,000 block-bootstrap Monte Carlo 5y paths of the combined account, resampling the
   2014+ era (all sleeves alive). Percentile bands -> research/projection_5y.html.
   HONESTY NOTE: the resampled era contains crypto's golden years and an exceptional
   equity bull; treat the upper band as optimistic, the median as "if history rhymes".
"""
import sys, os, json, math, random, datetime
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import moe_core as C
from backtest import load, yf, metrics, in_window, fmt, HDR, EVAL_START, DEV_END, simulate, spy_bh
from edges import vrp_series
from moonshot import trend_sleeve, combine

START_ALL=datetime.date(2014,9,17)   # first day every sleeve component exists

def build_all():
    DB,VIXB,IRX=load()
    M=C.build_market(DB,{C.uday(r["t"]):r["c"] for r in VIXB})
    D=C.expert_decisions(M,div=C.ETF_DIV)
    H,S=C.expert_series(M,D,legacy=False)
    e,x,c,_=C.fixed_router(M,S,C.V11_WEIGHTS)
    v11=simulate((M,D,H,S,e,x,c),IRX,lev=2.0,max_gross=2.0,vol_target=0.16,cash_yield=True)
    moon=combine([trend_sleeve(["BTC-USD","ETH-USD"],fee_bps=25),
                  trend_sleeve(["SOXL","TQQQ"],fee_bps=5),
                  vrp_series(yf("SVXY"),VIXB,yf("^VIX3M"))],[0.5,0.3,0.2])
    full=combine([v11,moon],[0.8,0.2])
    return DB,v11,moon,full

def mc_paths(rets, n_paths=20000, block=20, seed=23, waypoints=60):
    rs=[r for _,r in rets]; days=len(rs)
    years=(rets[-1][0]-rets[0][0]).days/365.25; af=days/years
    horizon=int(af*5); step=max(1,horizon//waypoints)
    rng=random.Random(seed)
    grid=[[] for _ in range(waypoints+1)]
    finals=[]; samples=[]
    for p in range(n_paths):
        m=1.0; k=0; wp=[1.0]
        while k<horizon:
            st=rng.randrange(0,days-block)
            for b in range(block):
                m*=(1+rs[st+b]); k+=1
                if k%step==0 and len(wp)<=waypoints: wp.append(m)
                if k>=horizon: break
        while len(wp)<=waypoints: wp.append(m)
        finals.append(m)
        for i,v in enumerate(wp): grid[i].append(v)
        if p<40: samples.append([round(v,4) for v in wp])
    pct={}
    for q in (5,25,50,75,95):
        pct[q]=[round(sorted(col)[int(q/100*len(col))],4) for col in grid]
    finals.sort()
    def P(x): return sum(1 for v in finals if v>=x)/len(finals)
    stats={"P100x":P(100),"P10x":P(10),"P3x":P(3),"P2x":P(2),"Ploss":1-P(1),
           "median":sorted(finals)[len(finals)//2]}
    return pct,samples,stats

HTML_TMPL="""<!DOCTYPE html><html><head><meta charset="utf-8"><title>$1k — 5-year projection (honest Monte Carlo)</title>
<style>body{font-family:-apple-system,Segoe UI,sans-serif;background:#0e1117;color:#e6e6e6;margin:24px}
h1{font-size:20px} .sub{color:#9aa0a6;font-size:13px;max-width:900px;line-height:1.5}
canvas{background:#12161f;border:1px solid #2a2f3a;border-radius:8px;margin-top:14px}
.stats{display:flex;gap:22px;margin-top:12px;flex-wrap:wrap} .card{background:#161b26;border:1px solid #2a2f3a;border-radius:8px;padding:10px 16px}
.card b{font-size:19px;display:block} .card span{color:#9aa0a6;font-size:12px}</style></head><body>
<h1>$1,000 &rarr; 5-year Monte Carlo projection &mdash; v11 core (80%) + moon sleeve (20%)</h1>
<div class="sub">20,000 block-bootstrap paths resampled from the strategy's honest daily returns
(2014&ndash;2026, all costs, lag-1 signals, no lookahead). Shaded bands: where 90% / 50% of simulated
futures land. <b>Honesty note:</b> the resampled era includes crypto's golden years and an exceptional
equity bull &mdash; read the upper band as "if that repeats", the lower band as a normal bad draw.</div>
<div class="stats">
<div class="card"><b>$__MED__</b><span>median outcome</span></div>
<div class="card"><b>__P2__%</b><span>P(&ge; 2x &rarr; $2k)</span></div>
<div class="card"><b>__P3__%</b><span>P(&ge; 3x &rarr; $3k)</span></div>
<div class="card"><b>__P10__%</b><span>P(&ge; 10x &rarr; $10k)</span></div>
<div class="card"><b>__P100__%</b><span>P(&ge; 100x &rarr; $100k &mdash; the goal)</span></div>
<div class="card"><b>__PL__%</b><span>P(ending below $1k)</span></div>
</div>
<canvas id="c" width="1160" height="600"></canvas>
<script>
const pct=__PCT__, samples=__SAMPLES__;
const W=1160,H=600,L=70,R=20,T=20,B=40,n=pct["50"].length;
const ymin=200, ymax=Math.max(200000, 1000*Math.max(...pct["95"])*1.2);
const x=i=>L+(W-L-R)*i/(n-1), y=v=>T+(H-T-B)*(1-(Math.log(v)-Math.log(ymin))/(Math.log(ymax)-Math.log(ymin)));
const cx=document.getElementById("c").getContext("2d");
function band(lo,hi,fill){cx.beginPath();cx.moveTo(x(0),y(1000*pct[lo][0]));
for(let i=1;i<n;i++)cx.lineTo(x(i),y(1000*pct[lo][i]));
for(let i=n-1;i>=0;i--)cx.lineTo(x(i),y(1000*pct[hi][i]));cx.closePath();cx.fillStyle=fill;cx.fill();}
function line(a,color,wd,dash){cx.beginPath();cx.setLineDash(dash||[]);cx.strokeStyle=color;cx.lineWidth=wd;
cx.moveTo(x(0),y(1000*a[0]));for(let i=1;i<n;i++)cx.lineTo(x(i),y(1000*a[i]));cx.stroke();cx.setLineDash([]);}
cx.font="12px sans-serif";
for(const g of [300,1000,3000,10000,30000,100000]){if(g<ymin||g>ymax)continue;
cx.strokeStyle=(g===100000)?"#7a5c20":(g===10000?"#3f5a3f":"#1f2530");
cx.beginPath();cx.moveTo(L,y(g));cx.lineTo(W-R,y(g));cx.stroke();
cx.fillStyle="#9aa0a6";cx.fillText("$"+g.toLocaleString(),8,y(g)+4);}
for(let yr=0;yr<=5;yr++){const i=Math.round((n-1)*yr/5);cx.strokeStyle="#1f2530";cx.beginPath();cx.moveTo(x(i),T);cx.lineTo(x(i),H-B);cx.stroke();
cx.fillStyle="#9aa0a6";cx.fillText("year "+yr,x(i)-18,H-B+18);}
for(const s of samples) line(s,"rgba(120,140,180,0.10)",1);
band("5","95","rgba(70,110,200,0.16)"); band("25","75","rgba(70,110,200,0.24)");
line(pct["50"],"#e8b339",2.5);
line(pct["95"],"rgba(140,180,255,0.5)",1,[4,4]); line(pct["5"],"rgba(140,180,255,0.5)",1,[4,4]);
cx.fillStyle="#e8b339";cx.fillText("median",x(n-1)-52,y(1000*pct["50"][n-1])-6);
cx.fillStyle="#7a5c20";cx.fillText("$100k GOAL",W-R-88,y(100000)-6);
cx.fillStyle="#3f5a3f";cx.fillText("$10k",W-R-40,y(10000)-6);
</script></body></html>"""

if __name__=="__main__":
    DB,v11,moon,full=build_all()
    spy=spy_bh(DB)
    today=datetime.date(2026,6,30); h0=datetime.date(2020,1,1)
    lines=[]
    for title,a,b in [("DEV (selection allowed)",EVAL_START,DEV_END),("HOLDOUT 2020+ (one look)",h0,today)]:
        lines.append(f"\n== {title} ==\n{HDR}")
        for name,r in [("SPY buy&hold",spy),("v11 core 2x volT16",v11),
                       ("moon sleeve (50/30/20)",moon),("FULL 80% core + 20% moon",full)]:
            lines.append(fmt(name, metrics(in_window(r,a,b))))
    print("\n".join(lines))
    frets=in_window(full,START_ALL,today)
    pct,samples,st=mc_paths(frets)
    print(f"\nMC 5y from $1k: median ${st['median']*1000:,.0f} | P(2x) {st['P2x']*100:.0f}% | "
          f"P(3x) {st['P3x']*100:.0f}% | P(10x) {st['P10x']*100:.1f}% | P(100x) {st['P100x']*100:.2f}% | "
          f"P(loss) {st['Ploss']*100:.0f}%")
    html=HTML_TMPL.replace("__PCT__",json.dumps({str(k):v for k,v in pct.items()}))\
        .replace("__SAMPLES__",json.dumps(samples))\
        .replace("__MED__",f"{st['median']*1000:,.0f}")\
        .replace("__P2__",f"{st['P2x']*100:.0f}").replace("__P3__",f"{st['P3x']*100:.0f}")\
        .replace("__P10__",f"{st['P10x']*100:.1f}").replace("__P100__",f"{st['P100x']*100:.2f}")\
        .replace("__PL__",f"{st['Ploss']*100:.0f}")
    out=os.path.join(HERE,"projection_5y.html")
    open(out,"w").write(html)
    # aggressive alternative: 100% moon sleeve (the aspirational, lottery-odds configuration)
    mrets=in_window(moon,START_ALL,today)
    mpct,msamples,mst=mc_paths(mrets,seed=29)
    print(f"MC 5y $1k, 100% MOON: median ${mst['median']*1000:,.0f} | P(3x) {mst['P3x']*100:.0f}% | "
          f"P(10x) {mst['P10x']*100:.1f}% | P(100x) {mst['P100x']*100:.2f}% | P(loss) {mst['Ploss']*100:.0f}%")
    mhtml=HTML_TMPL.replace("__PCT__",json.dumps({str(k):v for k,v in mpct.items()}))\
        .replace("__SAMPLES__",json.dumps(msamples))\
        .replace("__MED__",f"{mst['median']*1000:,.0f}")\
        .replace("__P2__",f"{mst['P2x']*100:.0f}").replace("__P3__",f"{mst['P3x']*100:.0f}")\
        .replace("__P10__",f"{mst['P10x']*100:.1f}").replace("__P100__",f"{mst['P100x']*100:.2f}")\
        .replace("__PL__",f"{mst['Ploss']*100:.0f}")\
        .replace("v11 core (80%) + moon sleeve (20%)","100% MOON SLEEVE (max aggression)")
    open(os.path.join(HERE,"projection_5y_moon.html"),"w").write(mhtml)
    with open(os.path.join(HERE,"final_results.md"),"w") as f:
        f.write("# FINAL strategy (v11 80% + moon 20%) — honest validation\n```"+ "\n".join(lines)+"\n```\n")
        f.write(f"\nMC 5y from $1k: median ${st['median']*1000:,.0f}, P(2x) {st['P2x']*100:.0f}%, P(3x) {st['P3x']*100:.0f}%, "
                f"P(10x) {st['P10x']*100:.1f}%, P(100x) {st['P100x']*100:.2f}%, P(loss) {st['Ploss']*100:.0f}%\n")
    print(f"\nwrote {out} and final_results.md")
