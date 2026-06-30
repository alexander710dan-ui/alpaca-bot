#!/usr/bin/env python3
"""
MoE v8 live bot for Alpaca — PAPER (fake money). The best system from the project.

Five regime-routed "experts" combined daily:
  - dip  : buy washed-out dips (RSI2<10 / gap-down>3% / below lower band) in an uptrend, exit on bounce
  - trend: monthly cross-asset momentum rotation (top-2 of SPY/QQQ/EFA/EEM/GLD/TLT/DBC/XLK)
  - def  : stronger of GLD/TLT by momentum (cash if both falling)
  - crash: short SPY when SPY is below its 200-day average
  - core : long the strongest of SPY/QQQ/XLK while SPY is above its 200-day average (rides calm grinds)

Router (v8): online Hedge weighting by trailing expert performance -> sparse top-3 -> 20% shared expert
(core in bull / def in bear) -> Muon-style correlation whitening -> per-expert vol-targeting ->
confidence-gated exposure -> constant-vol overlay -> x2 leverage.

Signals come from Yahoo (exactly as backtested); execution is Alpaca market orders. The bot is STATELESS:
each run it refetches ~2.5y of daily bars and replays the whole router, so there is no fragile state file.

Backtest (15y, costs in): x1 ~34%/yr @ 11% DD, Sharpe 2.09 (DSR-passed); x2 ~76%/yr @ 21% DD.
Run: python3 moe_bot.py --test  (dry run, no orders) | python3 moe_bot.py  (live, paper).
"""
import os, sys, math, json, datetime, logging, logging.handlers, urllib.request

PAPER = True
LEV   = 2.0                      # <<< deploy leverage (user choice). Set 1.0 for the unleveraged version.
HERE  = os.path.dirname(os.path.abspath(__file__))
DIV   = ["SPY","QQQ","IWM","DIA","XLF","XLE","XLK","EEM","EFA","XLV","XLY","XLI",
         "AAPL","MSFT","AMZN","NVDA","JPM","XOM","KO","WMT"]          # dip universe
ROT   = ["SPY","QQQ","EFA","EEM","GLD","TLT","DBC","XLK"]            # rotation universe
CORE  = ["SPY","QQQ","XLK"]
EXTRA = ["GLD","TLT"]
SYMS  = sorted(set(DIV+ROT+CORE+EXTRA))
REBAL_BAND = 0.015              # only trade a symbol if target notional differs from current by >1.5% of equity

log=logging.getLogger("moe"); log.setLevel(logging.INFO)
_f=logging.Formatter("%(asctime)s  %(message)s","%Y-%m-%d %H:%M:%S")
for h in (logging.handlers.RotatingFileHandler(os.path.join(HERE,"moe.log"),maxBytes=1_000_000,backupCount=3), logging.StreamHandler()):
    h.setFormatter(_f); log.addHandler(h)

# ---------------- data (Yahoo, same source as the backtest) ----------------
def yf(sym, rng="3y"):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
    for attempt in range(3):
        try:
            req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
            raw=json.load(urllib.request.urlopen(req, timeout=30))
            res=raw["chart"]["result"][0]; ts=res["timestamp"]; q=res["indicators"]["quote"][0]
            out=[]
            for i in range(len(ts)):
                c=q["close"][i]
                if c is None: continue
                out.append({"t":ts[i],"c":c})
            if out: return out
        except Exception as e:
            if attempt==2: log.info(f"  yahoo fail {sym}: {e}")
    return []

def SMA(x,n):
    out=[None]*len(x); s=0.0
    for i in range(len(x)):
        s+=x[i]
        if i>=n: s-=x[i-n]
        if i>=n-1: out[i]=s/n
    return out
def RSI(x,n):
    out=[None]*len(x)
    for i in range(n,len(x)):
        g=l=0.0
        for j in range(i-n+1,i+1):
            ch=x[j]-x[j-1]; g+=max(ch,0); l+=max(-ch,0)
        out[i]=100.0 if l==0 else (0.0 if g==0 else 100-100/(1+(g/n)/(l/n)))
    return out

# ---------------- fetch + align to SPY spine ----------------
DB={s:yf(s) for s in SYMS}; DB={s:b for s,b in DB.items() if len(b)>=300}
VIXB=yf("^VIX")
if "SPY" not in DB: log.info("no SPY data; abort"); sys.exit(0)
SPY=DB["SPY"]; spt=[r["t"] for r in SPY]; spc=[r["c"] for r in SPY]
spm200=SMA(spc,200); spm=spm200
RET={s:{} for s in DB}
for s,b in DB.items():
    for i in range(1,len(b)): RET[s][b[i]["t"]]=(b[i]["c"]-b[i-1]["c"])/b[i-1]["c"]
def closes_by_t(s): return {r["t"]:r["c"] for r in DB[s]}
CL={s:closes_by_t(s) for s in DB}
# momentum (63d) per symbol by date
MOM={s:{} for s in DB}
for s,b in DB.items():
    c=[r["c"] for r in b]
    for i in range(63,len(b)): MOM[s][b[i]["t"]]=c[i]/c[i-63]-1
def ma200_at(s,t):
    b=DB.get(s);
    if not b: return None
    idx={r["t"]:i for i,r in enumerate(b)}
    if t not in idx or idx[t]<200: return None
    i=idx[t]; return sum(x["c"] for x in b[i-200:i])/200
# regime
TZ={}; RISKON={}
for i in range(len(SPY)):
    TZ[spt[i]] = (spc[i]/spm[i]-1) if spm[i] else 0.0
    RISKON[spt[i]] = (spm[i] is not None and spc[i]>spm[i])
vixmap={r["t"]:r["c"] for r in VIXB}
def vx(t):
    best=18.0
    for dt in spt:
        if dt<=t and dt in vixmap: best=vixmap[dt]
    return best
DATES=spt[:]                                   # spine
dl=DATES

# ---------------- experts: daily return series + today positions ----------------
def dip_state(sym):
    b=DB[sym]; c=[r["c"] for r in b]; r2=RSI(c,2); s200=SMA(c,200); s5=SMA(c,5); s20=SMA(c,20); n=len(b)
    pb=[None]*n
    for i in range(20,n):
        m=s20[i]; sd=(sum((c[j]-m)**2 for j in range(i-19,i+1))/20)**0.5
        if sd>0: pb[i]=(c[i]-(m-2*sd))/(4*sd)
    pos=[0]*n; sc=[99.]*n; cur=0
    for i in range(n):
        up=s200[i] is not None and c[i]>s200[i]
        sig=up and ((r2[i] is not None and r2[i]<10) or (c[i]<c[i-1]*0.97) or (pb[i] is not None and pb[i]<0))
        ex=s5[i] is not None and c[i]>s5[i]
        cur=1 if (cur==0 and sig) else (0 if (cur==1 and ex) else cur); pos[i]=cur
        if cur: sc[i]=r2[i] if r2[i] is not None else 50
    return b,pos,sc
DIP={}
for s in DIV:
    if s in DB: DIP[s]=dip_state(s)
def dip_ret_and_pos():
    # return series over spine + today held positions (top-4 by oversold)
    ser={}
    for t in dl:
        held=[]
        for s,(b,pos,sc) in DIP.items():
            idx={r["t"]:i for i,r in enumerate(b)}
            if t in idx and idx[t]>=1 and pos[idx[t]-1]==1:
                held.append((s, RET[s].get(t,0.0), sc[idx[t]-1]))
        held.sort(key=lambda x:x[2])
        ser[t]= (sum(x[1] for x in held[:4])/min(len(held),4)) if held else 0.0
    # today positions
    last=dl[-1]; held=[]
    for s,(b,pos,sc) in DIP.items():
        idx={r["t"]:i for i,r in enumerate(b)}
        if last in idx and pos[idx[last]]==1: held.append((s, sc[idx[last]]))
    held.sort(key=lambda x:x[1]); held=[s for s,_ in held[:4]]
    posw={s:1.0/len(held) for s in held} if held else {}
    return ser, posw
def trend_ret_and_pos():
    ser={}; hold=[]; prevm=None
    idxs={s:{r["t"]:i for i,r in enumerate(DB[s])} for s in ROT if s in DB}
    for t in dl:
        m=datetime.datetime.utcfromtimestamp(t).month
        if m!=prevm:
            elig=[]
            for s in ROT:
                if s in DB and s in idxs and t in idxs[s]:
                    ma=ma200_at(s,t); cl=CL[s].get(t)
                    if ma and cl and cl>ma and MOM[s].get(t,-9)>0: elig.append((s,MOM[s].get(t,-9)))
            elig.sort(key=lambda x:-x[1]); hold=[s for s,_ in elig[:2]]; prevm=m
        ser[t]= sum(RET[s].get(t,0.0) for s in hold)/len(hold) if hold else 0.0
    posw={s:1.0/len(hold) for s in hold} if hold else {}
    return ser, posw
def def_ret_and_pos():
    ser={}
    for t in dl:
        g=MOM["GLD"].get(t,0) if "GLD" in DB else -9; l=MOM["TLT"].get(t,0) if "TLT" in DB else -9
        if g<=0 and l<=0: ser[t]=0.0
        else: ser[t]=RET["GLD"].get(t,0.0) if g>=l else RET["TLT"].get(t,0.0)
    last=dl[-1]; g=MOM["GLD"].get(last,0); l=MOM["TLT"].get(last,0)
    posw={} if (g<=0 and l<=0) else ({"GLD":1.0} if g>=l else {"TLT":1.0})
    return ser, posw
def crash_ret_and_pos():
    ser={t:(-RET["SPY"].get(t,0.0) if not RISKON.get(t,True) else 0.0) for t in dl}
    posw={"SPY":-1.0} if not RISKON.get(dl[-1],True) else {}
    return ser, posw
def core_ret_and_pos():
    ser={}
    for i in range(1,len(dl)):
        tp,t=dl[i-1],dl[i]
        if RISKON.get(tp,True):
            cand=sorted([(x,MOM[x].get(tp,-9)) for x in CORE if x in DB],key=lambda z:-z[1])
            s,mm=cand[0]; ser[t]=RET[s].get(t,0.0) if mm>0 else 0.0
        else: ser[t]=0.0
    ser[dl[0]]=0.0
    last=dl[-1]; posw={}
    if RISKON.get(last,True):
        cand=sorted([(x,MOM[x].get(last,-9)) for x in CORE if x in DB],key=lambda z:-z[1]); s,mm=cand[0]
        if mm>0: posw={s:1.0}
    return ser, posw

dipS,dipP   = dip_ret_and_pos()
trS,trP     = trend_ret_and_pos()
defS,defP   = def_ret_and_pos()
crS,crP     = crash_ret_and_pos()
coS,coP     = core_ret_and_pos()
SER={'dip':dipS,'trend':trS,'def':defS,'crash':crS,'core':coS}
POS={'dip':dipP,'trend':trP,'def':defP,'crash':crP,'core':coP}
KS=list(SER.keys())

# ---------------- router replay (v8) ----------------
def scores(t):
    tz=TZ.get(t,0); v=vx(t); risk_on=1/(1+math.exp(-tz*25)); stress=max(0,min(1,(v-15)/22)); trans=math.exp(-((tz/0.04)**2))
    s={'dip':risk_on*(1-stress),'trend':risk_on*(1-0.5*stress)*0.7,
       'def':(1-risk_on)*0.6+stress*0.4+trans*0.35+0.08,'crash':(1-risk_on)*0.6+stress*0.5+trans*0.15}
    s['core']=max(0.0,math.tanh(max(0,tz)*18))*(1-stress)*1.6
    return s
def replay():
    SHARED_W=0.20; K=3; eta=6.0; alpha=0.04; tgt=0.008; beta=0.02
    ewma={k:0.0 for k in KS}; var={k:tgt*tgt for k in KS}; mu={k:0.0 for k in KS}
    cov={(a,b):0.0 for a in KS for b in KS}; var2=0.009**2
    last_eff=None; last_expo=1.0; last_scl=1.0
    for t in dl:
        pr=scores(t); comb={k:pr[k]*math.exp(eta*ewma[k]) for k in KS}
        scale={k:min(3.0,max(0.3, tgt/(var[k]**0.5 if var[k]>1e-9 else tgt))) for k in KS}
        top=sorted(comb.items(),key=lambda x:-x[1])[:K]; tt=sum(v for _,v in top); w={}
        for k,v in top: w[k]=w.get(k,0)+(v/tt)*(1-SHARED_W)
        shared='core' if RISKON.get(t,True) else 'def'; w[shared]=w.get(shared,0)+SHARED_W
        redun={}
        for k in w:
            ssum=0.0
            for j in w:
                if j==k: continue
                vk=cov[(k,k)]**0.5; vj=cov[(j,j)]**0.5
                c=cov[(k,j)]/(vk*vj) if vk>1e-6 and vj>1e-6 else 0.0
                ssum+=max(0.0,c)*w[j]
            redun[k]=1.0/(1.0+ssum)
        w={k:w[k]*redun[k] for k in w}
        eff={k:w.get(k,0)*scale[k] for k in KS}; g=sum(eff.values()) or 1.0; eff={k:v/g for k,v in eff.items()}
        expo=0.85+(1.30-0.85)*max(0.0,min(1.0,(max(eff.values())-0.45)/0.35))
        sg=var2**0.5; scl=min(1.6,max(0.5,0.009/sg if sg>1e-9 else 1.0))
        last_eff,last_expo,last_scl=eff,expo,scl
        # update trailing stats with realized expert returns (no lookahead for next day)
        rc={k:SER[k].get(t,0.0) for k in KS}
        port=expo*sum(eff[k]*rc[k] for k in KS)
        for k in KS:
            r=rc[k]; ewma[k]=(1-alpha)*ewma[k]+alpha*r; var[k]=(1-beta)*var[k]+beta*r*r; mu[k]=(1-beta)*mu[k]+beta*r
        for a in KS:
            for b in KS: cov[(a,b)]=(1-beta)*cov[(a,b)]+beta*(rc[a]-mu[a])*(rc[b]-mu[b])
        var2=0.96*var2+0.04*port*port
    return last_eff,last_expo,last_scl

eff,expo,scl = replay()
gross = LEV*scl*expo
# aggregate to per-symbol target weights
tw={}
for k in KS:
    for sym,pw in POS[k].items():
        tw[sym]=tw.get(sym,0.0)+gross*eff[k]*pw
tw={s:round(v,4) for s,v in tw.items() if abs(v)>1e-4}
regime="BULL" if RISKON.get(dl[-1],True) else "BEAR"
log.info(f"v8 router | regime {regime} | VIX {vx(dl[-1]):.1f} | exposure {expo:.2f} x volscale {scl:.2f} x lev {LEV:.0f} = gross {gross:.2f}")
log.info(f"  expert weights: " + " ".join(f"{k}={eff[k]:.2f}" for k in KS))
log.info(f"  TARGET book ({len(tw)} positions): " + ", ".join(f"{s} {w*100:+.0f}%" for s,w in sorted(tw.items(),key=lambda x:-abs(x[1]))))

# ---------------- execution (Alpaca) ----------------
def keys():
    k=os.environ.get("ALPACA_KEY"); s=os.environ.get("ALPACA_SECRET"); sf=os.path.join(HERE,"secrets.env")
    if (not k or not s) and os.path.exists(sf):
        for line in open(sf):
            if line.startswith("ALPACA_KEY="): k=line.split("=",1)[1].strip()
            if line.startswith("ALPACA_SECRET="): s=line.split("=",1)[1].strip()
    return k,s

def main(dry):
    if dry:
        log.info("DRY RUN — no orders placed. (target book above is what it WOULD hold.)")
        return
    K,S=keys()
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    trade=TradingClient(K,S,paper=PAPER)
    clock=trade.get_clock()
    if not clock.is_open:
        log.info(f"market closed (next {clock.next_open}); no trades."); return
    acct=trade.get_account(); equity=float(acct.equity)
    pos={p.symbol:p for p in trade.get_all_positions()}
    curmv={s:float(p.market_value) for s,p in pos.items()}
    log.info(f"equity ${equity:,.0f} | current {len(pos)} positions")
    want={s:tw.get(s,0.0)*equity for s in set(list(tw)+list(pos))}
    def last_price(s):
        try: return float(pos[s].current_price)
        except: return CL[s].get(dl[-1]) if s in CL else None
    # 1) fully close anything not in the target book — by EXACT qty (close_position), never notional
    for s in list(pos):
        if abs(want.get(s,0.0))<1:
            try: log.info(f"  CLOSE {s} (${curmv.get(s,0):,.0f})"); trade.close_position(s)
            except Exception as e: log.info(f"    close failed {s}: {e}")
    # 2) adjust / open the rest (each order isolated so one failure can't abort the run)
    for s,wnot in want.items():
        if abs(wnot)<1: continue
        delta=wnot-curmv.get(s,0.0)
        if abs(delta) < REBAL_BAND*equity: continue
        try:
            if wnot<0:                                   # short target -> whole shares (no fractional shorts)
                px=last_price(s) or 1.0; cur_sh=float(pos[s].qty) if s in pos else 0.0
                d=int(-abs(wnot)/px)-int(cur_sh)
                if abs(d)>=1:
                    log.info(f"  {'SHORT' if d<0 else 'COVER'} {s} {abs(d)} sh")
                    trade.submit_order(MarketOrderRequest(symbol=s, qty=abs(d), side=(OrderSide.SELL if d<0 else OrderSide.BUY), time_in_force=TimeInForce.DAY))
            elif delta<0 and abs(delta) >= abs(curmv.get(s,0.0))*0.98:
                log.info(f"  CLOSE {s} (reduce~0)"); trade.close_position(s)
            else:
                log.info(f"  {'BUY' if delta>0 else 'SELL'} {s} ${abs(delta):,.0f} -> target ${wnot:,.0f}")
                trade.submit_order(MarketOrderRequest(symbol=s, notional=round(abs(delta),2), side=(OrderSide.BUY if delta>0 else OrderSide.SELL), time_in_force=TimeInForce.DAY))
        except Exception as e:
            log.info(f"    order failed {s}: {e}")
    log.info("done.")

if __name__=="__main__":
    main("--test" in sys.argv or "--dryrun" in sys.argv)
