#!/usr/bin/env python3
"""
Strategy core shared by the LIVE bot (moe_bot.py) and the BACKTESTER (research/backtest.py).

Pure functions only — no network, no Alpaca, no side effects — so the exact code that trades
is the exact code that gets backtested. This kills live/backtest drift, the biggest source of
"backtest was great, live wasn't" in the old design.

legacy flag
-----------
legacy=True  reproduces the ORIGINAL v8 replay bit-for-bit, including its same-day lookaheads:
             the trend/def/crash experts and the router's regime prior all used day t's CLOSE
             to weight/select returns earned DURING day t — information no live trader has.
legacy=False (default) applies every signal with a one-day lag (decide at close t-1, earn day t),
             which is exactly what the live bot can actually do (it trades the morning after
             the signal bar completes). Expect lower — i.e. honest — backtest numbers.
"""
import math, datetime

# ---------------- universes (single source of truth) ----------------
DIV   = ["SPY","QQQ","IWM","DIA","XLF","XLE","XLK","EEM","EFA","XLV","XLY","XLI",
         "AAPL","MSFT","AMZN","NVDA","JPM","XOM","KO","WMT"]          # dip universe
ETF_DIV = ["SPY","QQQ","IWM","DIA","XLF","XLE","XLK","EEM","EFA","XLV","XLY","XLI"]
# ^ dip universe without single names: the 8 megacaps above were picked in hindsight
#   (survivorship bias); the ETF-only version is the honest default for v10.
ROT   = ["SPY","QQQ","EFA","EEM","GLD","TLT","DBC","XLK"]            # rotation universe
CORE  = ["SPY","QQQ","XLK"]
EXTRA = ["GLD","TLT"]
def all_symbols(): return sorted(set(DIV+ROT+CORE+EXTRA))

EXPERT_LAG_LEGACY = {"dip":1, "trend":0, "def":0, "crash":0, "core":1, "trend2":0, "tom":1}

# ---------------- indicators ----------------
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

def uday(t): return datetime.datetime.fromtimestamp(t,datetime.timezone.utc).date()

# ---------------- market state ----------------
def build_market(DB, vix_by_day):
    """DB: {sym: [{"t":unix,"c":raw_close[,"ac":adj_close]}]} — needs "SPY".
    vix_by_day: {datetime.date: vix_close}. Returns the market dict M used everywhere.
    Signals (RSI/SMA/momentum/regime) use RAW closes (what the live bot sees on its charts);
    P&L returns ("ARET") use ADJUSTED closes so dividends are counted (TLT/GLD/KO matter)."""
    SPY=DB["SPY"]; spt=[r["t"] for r in SPY]; spc=[r["c"] for r in SPY]
    spm=SMA(spc,200)
    M={"dates":spt,"DB":DB}
    M["IDX"]={s:{r["t"]:i for i,r in enumerate(b)} for s,b in DB.items()}
    M["CL"]={s:{r["t"]:r["c"] for r in b} for s,b in DB.items()}
    RET={}; ARET={}
    for s,b in DB.items():
        RET[s]={}; ARET[s]={}
        for i in range(1,len(b)):
            RET[s][b[i]["t"]]=b[i]["c"]/b[i-1]["c"]-1
            a0=b[i-1].get("ac",b[i-1]["c"]); a1=b[i].get("ac",b[i]["c"])
            ARET[s][b[i]["t"]]=a1/a0-1 if a0 else 0.0
    M["RET"]=RET; M["ARET"]=ARET
    MOM={}; MA200={}
    for s,b in DB.items():
        c=[r["c"] for r in b]; MOM[s]={}; m2=SMA(c,200); MA200[s]={}
        for i in range(len(b)):
            if i>=63: MOM[s][b[i]["t"]]=c[i]/c[i-63]-1
            MA200[s][b[i]["t"]]=m2[i]
    M["MOM"]=MOM; M["MA200"]=MA200
    TZ={}; RISKON={}
    for i in range(len(spt)):
        TZ[spt[i]]=(spc[i]/spm[i]-1) if spm[i] else 0.0
        RISKON[spt[i]]=(spm[i] is not None and spc[i]>spm[i])
    M["TZ"]=TZ; M["RISKON"]=RISKON
    VX={}; b=None
    for t in spt:
        b=vix_by_day.get(uday(t),b)
        VX[t]=b if b is not None else 18.0
    M["VX"]=VX
    return M

# ---------------- turn-of-month calendar ----------------
def tom_flags(days, pre=4, post=3):
    """flag[i]: day i is one of the last `pre` or first `post` trading days of its month."""
    n=len(days); mo=[d.month for d in days]
    first=[0]*n; k=0
    for i in range(n):
        k=1 if (i==0 or mo[i]!=mo[i-1]) else k+1
        first[i]=k
    rem=[0]*n; k=0
    for i in range(n-1,-1,-1):
        k=0 if (i==n-1 or mo[i]!=mo[i+1]) else k+1
        rem[i]=k
    return [(first[i]<=post) or (rem[i]<pre) for i in range(n)]

def _tom_flag_next(d, pre=4, post=3):
    """Approximate the flag for the next trading day after date d using weekdays
    (exchange holidays can shift the window by a day — acceptable for a ±1-day-wide edge)."""
    nd=d+datetime.timedelta(days=1)
    while nd.weekday()>=5: nd+=datetime.timedelta(days=1)
    k=sum(1 for x in range(1,nd.day+1)
          if datetime.date(nd.year,nd.month,x).weekday()<5)          # trading day # in month
    r=0; x=nd+datetime.timedelta(days=1)
    while x.month==nd.month:
        if x.weekday()<5: r+=1
        x+=datetime.timedelta(days=1)
    return k<=post or r<pre

# ---------------- experts: decision books ----------------
def _dip_state(bars):
    c=[r["c"] for r in bars]; r2=RSI(c,2); s200=SMA(c,200); s5=SMA(c,5); s20=SMA(c,20); n=len(bars)
    pb=[None]*n
    for i in range(20,n):
        m=s20[i]; sd=(sum((c[j]-m)**2 for j in range(i-19,i+1))/20)**0.5
        if sd>0: pb[i]=(c[i]-(m-2*sd))/(4*sd)
    pos=[0]*n; sc=[99.]*n; cur=0
    for i in range(n):
        up=s200[i] is not None and c[i]>s200[i]
        sig=up and ((r2[i] is not None and r2[i]<10) or (i>=1 and c[i]<c[i-1]*0.97) or (pb[i] is not None and pb[i]<0))
        ex=s5[i] is not None and c[i]>s5[i]
        cur=1 if (cur==0 and sig) else (0 if (cur==1 and ex) else cur); pos[i]=cur
        if cur: sc[i]=r2[i] if r2[i] is not None else 50
    return pos,sc

def expert_decisions(M, div=None):
    """For each expert: D[t] = target book {sym:weight} DECIDED at close t (held from t+1)."""
    DB=M["DB"]; dl=M["dates"]; IDX=M["IDX"]; MOM=M["MOM"]; MA200=M["MA200"]; CL=M["CL"]
    D={k:{} for k in ("dip","trend","def","crash","core","trend2","tom")}
    dipst={s:_dip_state(DB[s]) for s in (div or DIV) if s in DB}
    for t in dl:
        held=[]
        for s,(pos,sc) in dipst.items():
            j=IDX[s].get(t)
            if j is not None and pos[j]==1: held.append((sc[j],s))
        held.sort(); top=[s for _,s in held[:4]]
        D["dip"][t]={s:1.0/len(top) for s in top} if top else {}
    hold=[]; prevm=None
    for t in dl:
        m=uday(t).month
        if m!=prevm:
            elig=[]
            for s in ROT:
                if s in DB and t in IDX[s]:
                    ma=MA200[s].get(t); cl=CL[s].get(t)
                    if ma and cl and cl>ma and MOM[s].get(t,-9)>0: elig.append((s,MOM[s].get(t,-9)))
            elig.sort(key=lambda x:-x[1]); hold=[s for s,_ in elig[:2]]; prevm=m
        D["trend"][t]={s:1.0/len(hold) for s in hold} if hold else {}
    # trend2: per-asset 12-1 time-series momentum, inverse-60d-vol weights, monthly rebalance.
    # Canonical parameters (Moskowitz/Ooi/Pedersen TSMOM); nothing here is fitted to this data.
    t2={}
    for s in ROT:
        if s not in DB: continue
        b=DB[s]; c=[r["c"] for r in b]; t2[s]={}
        for i in range(252,len(b)):
            mom=c[i-21]/c[i-252]-1
            rs=[c[j]/c[j-1]-1 for j in range(i-59,i+1)]
            mu=sum(rs)/len(rs); v=(sum((x-mu)**2 for x in rs)/len(rs))**0.5
            t2[s][b[i]["t"]]=(mom, v if v>1e-6 else None)
    hold2={}; prevm2=None
    for t in dl:
        m=uday(t).month
        if m!=prevm2:
            iv={}
            for s,d_ in t2.items():
                mom,v=d_.get(t,(None,None))
                if mom is not None and mom>0 and v: iv[s]=1.0/v
            tot=sum(iv.values())
            hold2={s:w/tot for s,w in iv.items()} if tot else {}
            prevm2=m
        D["trend2"][t]=dict(hold2)
    # tom: turn-of-month — hold SPY only the last 4 + first 3 trading days of each month
    # (pension/payroll flow anomaly, Lakonishok-Smidt 1988; the calendar is known in advance,
    # so this expert has zero lookahead by construction). D[t] answers: is the NEXT trading
    # day inside the window? (engine convention: book decided at t is held during t+1)
    days=[uday(t) for t in dl]
    flags=tom_flags(days)
    for i,t in enumerate(dl):
        nxt=flags[i+1] if i+1<len(dl) else _tom_flag_next(days[i])
        D["tom"][t]={"SPY":1.0} if nxt else {}
    for t in dl:
        g=MOM["GLD"].get(t,0) if "GLD" in DB else -9; l=MOM["TLT"].get(t,0) if "TLT" in DB else -9
        D["def"][t]={} if (g<=0 and l<=0) else ({"GLD":1.0} if g>=l else {"TLT":1.0})
        D["crash"][t]={"SPY":-1.0} if not M["RISKON"].get(t,True) else {}
        if M["RISKON"].get(t,True):
            cand=sorted([(x,MOM[x].get(t,-9)) for x in CORE if x in DB],key=lambda z:-z[1])
            s,mm=cand[0] if cand else (None,-9)
            D["core"][t]={s:1.0} if (s and mm>0) else {}
        else: D["core"][t]={}
    return D

def expert_series(M, D, legacy=False):
    """HELD[k][t] = book earning day t's return; SER[k][t] = that book's day-t return."""
    dl=M["dates"]; R=M["RET"] if legacy else M["ARET"]
    HELD={}; SER={}
    for k,dk in D.items():
        lag=EXPERT_LAG_LEGACY[k] if legacy else 1
        HELD[k]={}; SER[k]={}
        for i,t in enumerate(dl):
            book=dk.get(dl[i-lag],{}) if i-lag>=0 else {}
            HELD[k][t]=book
            SER[k][t]=sum(w*R[s].get(t,0.0) for s,w in book.items())
    return HELD,SER

# ---------------- router (v8, unchanged constants) ----------------
def _scores(tz,v):
    risk_on=1/(1+math.exp(-tz*25)); stress=max(0,min(1,(v-15)/22)); trans=math.exp(-((tz/0.04)**2))
    s={'dip':risk_on*(1-stress),'trend':risk_on*(1-0.5*stress)*0.7,
       'def':(1-risk_on)*0.6+stress*0.4+trans*0.35+0.08,'crash':(1-risk_on)*0.6+stress*0.5+trans*0.15}
    s['core']=max(0.0,math.tanh(max(0,tz)*18))*(1-stress)*1.6
    return s

def router(M, SER, legacy=False):
    """Replay the v8 router over the whole spine.
    Returns (effS, expoS, sclS, nxt) where effS[t]/expoS[t]/sclS[t] applied DURING day t,
    and nxt=(eff,expo,scl) is tomorrow's — what the live bot should trade today."""
    KS=[k for k in SER if k in ("dip","trend","def","crash","core")]   # v8 routes only its 5 experts
    dl=M["dates"]
    SHARED_W=0.20; K=3; eta=6.0; alpha=0.04; tgt=0.008; beta=0.02
    ewma={k:0.0 for k in KS}; var={k:tgt*tgt for k in KS}; mu={k:0.0 for k in KS}
    cov={(a,b):0.0 for a in KS for b in KS}; var2=0.009**2
    effS={}; expoS={}; sclS={}
    def step(tz,v,riskon):
        pr=_scores(tz,v); comb={k:pr[k]*math.exp(eta*ewma[k]) for k in KS}
        scale={k:min(3.0,max(0.3, tgt/(var[k]**0.5 if var[k]>1e-9 else tgt))) for k in KS}
        top=sorted(comb.items(),key=lambda x:-x[1])[:K]; tt=sum(v_ for _,v_ in top); w={}
        for k,v_ in top: w[k]=w.get(k,0)+(v_/tt)*(1-SHARED_W)
        shared='core' if riskon else 'def'; w[shared]=w.get(shared,0)+SHARED_W
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
        eff={k:w.get(k,0)*scale[k] for k in KS}; g=sum(eff.values()) or 1.0; eff={k:v_/g for k,v_ in eff.items()}
        expo=0.85+(1.30-0.85)*max(0.0,min(1.0,(max(eff.values())-0.45)/0.35))
        sg=var2**0.5; scl=min(1.6,max(0.5,0.009/sg if sg>1e-9 else 1.0))
        return eff,expo,scl
    for i,t in enumerate(dl):
        tsig=t if legacy else (dl[i-1] if i>0 else None)
        tz=M["TZ"].get(tsig,0.0) if tsig else 0.0
        v=M["VX"].get(tsig,18.0) if tsig else 18.0
        riskon=M["RISKON"].get(tsig,True) if tsig else True
        eff,expo,scl=step(tz,v,riskon)
        effS[t],expoS[t],sclS[t]=eff,expo,scl
        rc={k:SER[k].get(t,0.0) for k in KS}
        port=expo*sum(eff[k]*rc[k] for k in KS)
        for k in KS:
            r=rc[k]; ewma[k]=(1-alpha)*ewma[k]+alpha*r; var[k]=(1-beta)*var[k]+beta*r*r; mu[k]=(1-beta)*mu[k]+beta*r
        for a in KS:
            for b in KS: cov[(a,b)]=(1-beta)*cov[(a,b)]+beta*(rc[a]-mu[a])*(rc[b]-mu[b])
        var2=0.96*var2+0.04*port*port
    t=dl[-1]
    nxt=step(M["TZ"].get(t,0.0),M["VX"].get(t,18.0),M["RISKON"].get(t,True))
    return effS,expoS,sclS,nxt

# ---------------- v10: fixed-weight blend (no adaptive router) ----------------
# The v8 router's adaptivity was where the overfitting lived: under honest one-day-lag timing
# it turned ~0.8-Sharpe ingredients into a 0.4-Sharpe portfolio. v10 blends the experts that
# keep a REAL edge when honestly timed, with fixed weights. crash is excluded: honest Sharpe
# is negative (-0.26); its backtest "edge" was same-day lookahead.
# Frozen on DEV 2007-2019 (research/design_v10.py), verified once on HOLDOUT 2020+.
# dip uses ETF_DIV (no single-name survivorship). def/crash/trend excluded: def & old trend are
# dominated by trend2 (which holds GLD/TLT/DBC when they trend); crash has negative honest edge.
V10_WEIGHTS={"trend2":0.50,"dip":0.20,"core":0.30}
# v11 adds the turn-of-month expert (stable OOS: Sharpe 0.59 dev / 0.57 holdout standalone).
# Chosen on DEV among tom weights {.10,.20,.25}; frozen 2026-07-02, then ONE holdout look.
V11_WEIGHTS={"trend2":0.35,"dip":0.15,"core":0.25,"tom":0.25}

def fixed_router(M, SER, weights=None):
    """Constant expert weights; same return shape as router() so engines are interchangeable."""
    w=weights or V10_WEIGHTS
    eff={k:w.get(k,0.0) for k in SER}
    effS={t:eff for t in M["dates"]}; ones={t:1.0 for t in M["dates"]}
    return effS,ones,ones,(eff,1.0,1.0)

# ---------------- risk overlays (v9/v10): scale exposure from PAST returns only ----------------
def vol_target_multipliers(rets, target=0.12, lam=0.94, lo=0.4, hi=1.5):
    """m[i] for day i from EWMA vol of rets[0..i-1]. target = annualized vol target."""
    m=[1.0]*len(rets); var=(target/15.87)**2
    for i in range(1,len(rets)):
        var=lam*var+(1-lam)*rets[i-1]*rets[i-1]
        vol=(var**0.5)*15.87                      # sqrt(252)
        m[i]=min(hi,max(lo, target/vol if vol>1e-9 else 1.0))
    return m

def dd_scale_multipliers(rets, start=0.05, full=0.20, floor=0.30):
    """m[i] from the drawdown of the compounded curve through i-1: 1.0 until `start` drawdown,
    linear down to `floor` at `full` drawdown. Cuts exposure while losing, restores on recovery."""
    m=[1.0]*len(rets); eq=1.0; peak=1.0
    for i in range(1,len(rets)):
        eq*=(1+rets[i-1]); peak=max(peak,eq)
        dd=1-eq/peak
        m[i]=1.0 if dd<=start else max(floor, 1.0-(dd-start)/(full-start)*(1.0-floor))
    return m
