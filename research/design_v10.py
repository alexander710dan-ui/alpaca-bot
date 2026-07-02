#!/usr/bin/env python3
"""
v10 design — DEV WINDOW ONLY (2007-2019). The holdout (2020+) is not printed here on purpose;
it gets exactly ONE look, in backtest.py, after the configuration below is frozen.

Question 1: which fixed expert blend? (4 predefined candidates, no optimizer)
Question 2: full dip universe (survivorship-biased single names) vs ETF-only?
Question 3: which risk overlay? (none / vol-target / vol-target+ddScale)
All with costs: 5bp/side + IRX+150bp financing, dividends in, honest timing.
"""
import sys, os, datetime
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import moe_core as C
from backtest import load, metrics, in_window, fmt, HDR, EVAL_START, DEV_END, simulate

DB,VIXB,IRX=load()
M=C.build_market(DB,{C.uday(r["t"]):r["c"] for r in VIXB})

def blend_pipe(weights, div=None):
    D=C.expert_decisions(M, div=div)
    HELD,SER=C.expert_series(M,D,legacy=False)
    effS,expoS,sclS,nxt=C.fixed_router(M,SER,weights)
    return (M,D,HELD,SER,effS,expoS,sclS)

W1={"dip":.40,"trend":.25,"core":.20,"def":.15}
W2={"dip":.35,"trend":.30,"core":.15,"def":.20}
W3={"dip":.25,"trend":.25,"core":.25,"def":.25}
W4={"dip":.50,"trend":.30,"def":.20}

def dev(name, rets):
    print(fmt(name, metrics(in_window(rets, EVAL_START, DEV_END))))

print("== DEV 2007-2019 only ==")
print(HDR)
print("-- Q1: blends (full dip universe, 1x, no overlay) --")
P1=blend_pipe(W1); P2=blend_pipe(W2); P3=blend_pipe(W3); P4=blend_pipe(W4)
dev("W1 dip40/tr25/core20/def15", simulate(P1,IRX,lev=1.0))
dev("W2 dip35/tr30/core15/def20", simulate(P2,IRX,lev=1.0))
dev("W3 equal 25x4",              simulate(P3,IRX,lev=1.0))
dev("W4 dip50/tr30/def20",        simulate(P4,IRX,lev=1.0))
print("-- Q2: ETF-only dip universe (same blends) --")
P1e=blend_pipe(W1,div=C.ETF_DIV); P4e=blend_pipe(W4,div=C.ETF_DIV)
dev("W1 ETF-dip",                 simulate(P1e,IRX,lev=1.0))
dev("W4 ETF-dip",                 simulate(P4e,IRX,lev=1.0))
print("-- Q3: trend2 (per-asset 12-1 TSMOM, inv-vol) blends, ETF dip, idle cash in T-bills --")
V1={"trend2":.35,"dip":.25,"core":.25,"def":.15}
V2={"trend2":.45,"dip":.25,"core":.30}
V3={"trend2":.30,"dip":.30,"core":.20,"def":.20}
V4={"trend2":.50,"dip":.20,"core":.30}
PV={n:blend_pipe(w,div=C.ETF_DIV) for n,w in [("V1",V1),("V2",V2),("V3",V3),("V4",V4)]}
D2=C.expert_decisions(M,div=C.ETF_DIV); H2,S2=C.expert_series(M,D2,legacy=False)
r2=[(C.uday(t),S2["trend2"][t]) for t in M["dates"]]
dev("trend2 standalone (no costs)", r2)
for n,P in PV.items():
    dev(f"{n} 1x", simulate(P,IRX,lev=1.0,cash_yield=True))
print("-- Q4: overlays/leverage on leading V-blends --")
for n in ("V1","V2","V3","V4"):
    P=PV[n]
    dev(f"{n} 1x volT12",     simulate(P,IRX,lev=1.0,vol_target=0.12,cash_yield=True))
    dev(f"{n} 2x cap2",       simulate(P,IRX,lev=2.0,max_gross=2.0,cash_yield=True))
    dev(f"{n} 2x volT16",     simulate(P,IRX,lev=2.0,max_gross=2.0,vol_target=0.16,cash_yield=True))
    dev(f"{n} 2x volT20",     simulate(P,IRX,lev=2.0,max_gross=2.0,vol_target=0.20,cash_yield=True))
