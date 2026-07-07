#!/usr/bin/env python3
"""
MOON sleeve bot — PAPER. The aggressive satellite that runs NEXT TO the v10 core.

Design (research/moonshot.py, honest lag-1 timing, costs in — see moonshot_results.md):
  60%  crypto trend : long BTC/ETH while above their 200-day average, inverse-vol split,
                      cash when below (this is what dodges the -80% crypto winters)
  40%  turbo trend  : long TQQQ/SOXL while above their 200-day average, inverse-vol split
Sized at MOON_FRACTION of account equity; moe_bot ignores these symbols (IGNORE_SYMBOLS)
so the two bots never fight over positions.

Honest expectations (1993/2010/2014-2026 data, block-bootstrap Monte Carlo):
  median 5y multiple ~10x historically, worst historical 5y entry +40%, MaxDD ~59%,
  P(100x in 5y) ~0.1-5% and only if crypto's past drift roughly repeats. This sleeve makes
  $1k->$100k POSSIBLE, not likely. Anyone promising more is selling lookahead bias.

Run: python3 crypto_bot.py --test  (dry run) | python3 crypto_bot.py  (live, paper)
Crypto trades every day; the turbo leg only when the stock market is open.
"""
import os, sys, json, time, datetime, logging, logging.handlers, urllib.request
import guardrails as G
import moe_core as C

PAPER         = True
MOON_FRACTION = 0.20            # of account equity given to this sleeve (core keeps the rest)
# splits frozen on DEV in research/ (moonshot.py + edges.py): crypto trend / leveraged-ETF
# trend / contango-gated short-vol. VRP leg: hold SVXY only while VIX3M/VIX > 1 — selling
# insurance only when the curve visibly pays a premium (Sharpe 0.88 dev / 0.66 holdout).
CRYPTO_W, TURBO_W, VRP_W = 0.50, 0.30, 0.20
CRYPTO = ["BTC-USD","ETH-USD"]  # Yahoo symbols
TURBO  = ["TQQQ","SOXL"]
VRP_SYM= "SVXY"
# burst leg (day-wins): cash most days; on panic-day triggers (moe_core.burst_trigger) hold a
# 3x ETF for the day. UPRO (not TQQQ) so it never collides with the turbo leg's symbols.
# Validated research/daywins.py: dev 15%/yr Sharpe 0.66 -> holdout 23%/yr Sharpe 0.74.
BURST_FRACTION = 0.10           # of account equity, separate from MOON_FRACTION
BURST_SYM = "UPRO"
# vix-regime leg (edge factory PASS, Sharpe 1.10/0.37/0.68 dev/val/holdout): long TQQQ only
# while SPY is above its 200dma AND VIX<25. Lives here because this bot owns TQQQ.
VIXREG_FRACTION = 0.10
TO_ALPACA = {"BTC-USD":"BTC/USD","ETH-USD":"ETH/USD"}          # order symbols
FROM_POS  = {"BTCUSD":"BTC/USD","ETHUSD":"ETH/USD"}            # position symbols -> order symbols
MA, VOL_N = 200, 60
MAX_ORDERS, MAX_ORDER_FRAC, REBAL_BAND, STALE_DAYS = 10, 0.25, 0.02, 4

HERE=os.path.dirname(os.path.abspath(__file__))
log=logging.getLogger("moon"); log.setLevel(logging.INFO)
_f=logging.Formatter("%(asctime)s  %(message)s","%Y-%m-%d %H:%M:%S")
for h in (logging.handlers.RotatingFileHandler(os.path.join(HERE,"moon.log"),maxBytes=500_000,backupCount=2), logging.StreamHandler()):
    h.setFormatter(_f); log.addHandler(h)

def yf(sym, rng="2y"):
    for attempt in range(4):                    # alternate hosts + backoff: GH runner IPs get rate-limited
        host="query1" if attempt%2==0 else "query2"
        url=f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
        try:
            req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
            raw=json.load(urllib.request.urlopen(req, timeout=30))
            res=raw["chart"]["result"][0]; ts=res["timestamp"]; q=res["indicators"]["quote"][0]
            out=[{"t":ts[i],"c":q["close"][i]} for i in range(len(ts)) if q["close"][i] and q["close"][i]>0]
            out=G.drop_partial_bar(out)         # completed bars only, crypto included
            if out: return out
        except Exception as e:
            if attempt==3: log.info(f"  yahoo fail {sym}: {e}")
            else: time.sleep(1+2*attempt)
    return []

def leg_weights(syms, leg_total):
    """({yahoo_sym: weight}, frozen_syms) — MA200 trend + inverse-60d-vol on completed bars.
    A symbol whose DATA is missing/stale goes to `frozen`: its existing position must be
    left untouched (a data outage is not a sell signal — see 2026-07-06 incident)."""
    iv={}; frozen=[]
    now=time.time()
    for s in syms:
        b=yf(s)
        if len(b)<MA+VOL_N+2 or not G.data_fresh(b[-1]["t"], now, STALE_DAYS):
            log.info(f"  {s}: no fresh data — FROZEN (position untouched)"); frozen.append(s); continue
        c=[r["c"] for r in b]; m=C.SMA(c,MA)[-1]
        if m and c[-1]>m:
            rs=[c[i]/c[i-1]-1 for i in range(len(c)-VOL_N,len(c))]
            mu=sum(rs)/len(rs); v=(sum((x-mu)**2 for x in rs)/len(rs))**0.5
            if v>1e-9: iv[s]=1.0/v
    tot=sum(iv.values())
    return ({s:leg_total*w/tot for s,w in iv.items()} if tot else {}), frozen

def apply_freeze(targets, positions, frozen):
    """Remove frozen symbols from BOTH targets and positions so the planner can neither
    trade nor close them this run. Pure function (tested)."""
    t={s:w for s,w in targets.items() if s not in frozen}
    p={s:v for s,v in positions.items() if s not in frozen}
    return t,p

def vrp_weight():
    """({SVXY: w}, frozen) — SVXY while the VIX curve is in contango (completed bars).
    Data outage freezes SVXY (existing position untouched); a real backwardation signal closes it."""
    vix=yf("^VIX","6mo"); v3m=yf("^VIX3M","6mo")
    now=time.time()
    if not vix or not v3m or not G.data_fresh(vix[-1]["t"],now,STALE_DAYS) or not G.data_fresh(v3m[-1]["t"],now,STALE_DAYS):
        log.info("  VRP: VIX term-structure data missing/stale — FROZEN"); return {},[VRP_SYM]
    contango=v3m[-1]["c"]/vix[-1]["c"]
    log.info(f"  VRP: VIX3M/VIX = {contango:.3f} ({'contango — sell vol' if contango>1 else 'backwardation — CASH'})")
    return ({VRP_SYM: MOON_FRACTION*VRP_W} if contango>1.0 else {}), []

def burst_weight():
    """({UPRO: w}, frozen) — one-day hold when a panic-day setup fired on completed bars.
    Data outage freezes UPRO rather than closing it mid-trade."""
    qqq=yf("QQQ","2y"); vix=yf("^VIX","6mo")
    now=time.time()
    if len(qqq)<205 or not G.data_fresh(qqq[-1]["t"],now,STALE_DAYS):
        log.info("  BURST: QQQ data missing/stale — FROZEN"); return {},[BURST_SYM]
    vlast=v10=None
    if vix and G.data_fresh(vix[-1]["t"],now,STALE_DAYS) and len(vix)>=10:
        vlast=vix[-1]["c"]; v10=sum(r["c"] for r in vix[-10:])/10
    on=C.burst_trigger([r["c"] for r in qqq], vlast, v10)
    log.info(f"  BURST: trigger {'FIRED — deploy' if on else 'quiet — cash'}"
             + (f" (VIX {vlast:.1f} vs 10d {v10:.1f})" if vlast else ""))
    return ({BURST_SYM: BURST_FRACTION} if on else {}), []

def vixreg_weight():
    """({TQQQ: w}, frozen) — TQQQ while SPY>200dma and VIX<25 (completed bars).
    Data outage freezes TQQQ (which also pauses the turbo leg's TQQQ adjustments — conservative)."""
    spy=yf("SPY","2y"); vix=yf("^VIX","6mo")
    now=time.time()
    if len(spy)<201 or not G.data_fresh(spy[-1]["t"],now,STALE_DAYS) or not vix:
        log.info("  VIXREG: data missing/stale — FROZEN"); return {},["TQQQ"]
    on=C.vixreg_on([r["c"] for r in spy], vix[-1]["c"])
    log.info(f"  VIXREG: {'risk-on — hold TQQQ' if on else 'gate closed — cash'} (VIX {vix[-1]['c']:.1f})")
    return ({"TQQQ": VIXREG_FRACTION} if on else {}), []

def merge_targets(*legs):
    """Sum weights per symbol — a plain dict merge would OVERWRITE when legs share a symbol
    (turbo and vixreg both trade TQQQ)."""
    out={}
    for leg in legs:
        for s,w in leg.items(): out[s]=out.get(s,0.0)+w
    return out

def keys():
    k=os.environ.get("ALPACA_KEY"); s=os.environ.get("ALPACA_SECRET"); sf=os.path.join(HERE,"secrets.env")
    if (not k or not s) and os.path.exists(sf):
        for line in open(sf):
            if line.startswith("ALPACA_KEY="): k=line.split("=",1)[1].strip()
            if line.startswith("ALPACA_SECRET="): s=line.split("=",1)[1].strip()
    return k,s

def main(dry):
    cw,f1=leg_weights(CRYPTO, MOON_FRACTION*CRYPTO_W)
    tw_eq,f2=leg_weights(TURBO, MOON_FRACTION*TURBO_W)
    vw,f3=vrp_weight(); bw,f4=burst_weight(); xw,f5=vixreg_weight()
    targets={TO_ALPACA.get(s,s):w for s,w in merge_targets(cw, tw_eq, vw, bw, xw).items()}
    frozen={TO_ALPACA.get(s,s) for s in f1+f2+f3+f4+f5}
    if frozen: log.info(f"  FROZEN this run (data outage — positions untouched): {sorted(frozen)}")
    log.info("moon sleeve targets: " + (", ".join(f"{s} {w*100:.1f}%" for s,w in targets.items()) or "ALL CASH (nothing trending)"))
    if dry:
        log.info("DRY RUN — no orders."); return
    K,S=keys()
    if not K or not S: log.info("no API keys; aborting."); sys.exit(1)
    if os.path.exists(os.path.join(HERE,"KILL")):
        log.info("KILL file present — halted."); return
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    trade=TradingClient(K,S,paper=PAPER)
    acct=trade.get_account(); equity=float(acct.equity); last_eq=float(acct.last_equity or equity)
    if G.daily_loss_breached(equity, last_eq, 0.05):
        log.info(f"account down {(equity/last_eq-1)*100:.1f}% today — moon sleeve stands down."); return
    market_open=trade.get_clock().is_open
    mine=set(targets)|set(FROM_POS.values())|set(TURBO)|{VRP_SYM,BURST_SYM}
    # cancel only OUR stale orders (never touch the core bot's)
    try:
        for o in trade.get_orders():
            if o.symbol in mine or o.symbol in FROM_POS: trade.cancel_order_by_id(o.id)
    except Exception as e:
        log.info(f"  order scan failed: {e}; aborting run"); return
    pos={}
    for p in trade.get_all_positions():
        sym=FROM_POS.get(p.symbol, p.symbol)
        if sym in mine: pos[sym]=(float(p.market_value), float(p.qty))
    targets,pos=apply_freeze(targets, pos, frozen)      # frozen symbols: neither traded nor closed
    prices={s:None for s in mine}                       # sleeve is long-only; no short sizing needed
    actions,warnings=G.plan_orders(targets, equity, pos, prices,
                                   rebal_band=REBAL_BAND, max_order_frac=MAX_ORDER_FRAC, max_orders=MAX_ORDERS)
    for w in warnings: log.info(f"  WARNING: {w}")
    today=datetime.datetime.now(datetime.timezone.utc).strftime("%y%m%d")
    for a in actions:
        kind,s=a[0],a[1]
        is_crypto="/" in s
        if not is_crypto and not market_open:
            log.info(f"  skip {kind} {s} (stock market closed; crypto leg still trades)"); continue
        try:
            if kind=="close":
                log.info(f"  CLOSE {s} (${pos.get(s,(0,0))[0]:,.0f})")
                trade.close_position(s.replace("/",""))
                continue
            side=OrderSide.BUY if kind=="buy" else OrderSide.SELL
            tif=TimeInForce.GTC if is_crypto else TimeInForce.DAY
            log.info(f"  {kind.upper()} {s} ${a[2]:,.0f}")
            trade.submit_order(MarketOrderRequest(symbol=s, notional=a[2], side=side,
                               time_in_force=tif, client_order_id=f"moon-{today}-{s.replace('/','')}-{kind}"))
        except Exception as e:
            msg=str(e)
            if "client_order_id" in msg or "duplicate" in msg.lower():
                log.info(f"    {s}: already sent today — skipped")
            else:
                log.info(f"    order failed {s}: {e}")
    log.info("done.")

if __name__=="__main__":
    main("--test" in sys.argv or "--dryrun" in sys.argv)
