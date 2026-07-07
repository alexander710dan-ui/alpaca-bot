#!/usr/bin/env python3
"""
MoE v10 live bot for Alpaca — PAPER (fake money).

v10 = fixed-weight blend of the experts that keep a REAL edge under honest signal timing:
  trend2 50%  per-asset 12-1 time-series momentum, inverse-vol weights, monthly rebalance
  core   30%  strongest of SPY/QQQ/XLK while SPY is above its 200-day average
  dip    20%  RSI-2 dip-buying in uptrends, ETF universe only (no single-name survivorship)
plus a realized-vol-target overlay and idle cash parked in BIL. The old v8 adaptive router is
retained for research (STRAT="v8") but its backtest edge was same-day lookahead — see
research/results.md before believing any of its numbers.

ALL strategy math lives in moe_core.py and is SHARED with the backtester
(research/backtest.py), so what is backtested is exactly what trades.

The bot is stateless: each run refetches ~15y of daily bars, replays the whole router on
COMPLETED bars only, and rebalances to the resulting target book through guardrails.py
(see SAFETY.md for every safety layer and the kill switch).

Signal timing is honest by default (LEGACY=False): decide on close t-1, trade morning of t —
the only thing a once-a-day bot can actually do. LEGACY=True replays the original v8 timing
(same-day signal application) for comparison only; do not trade it.

Run: python3 moe_bot.py --test  (dry run, no orders) | python3 moe_bot.py  (live, paper).
"""
import os, sys, time, json, datetime, logging, logging.handlers, urllib.request
import guardrails as G
import moe_core as C

PAPER  = True
LEV    = 2.0                     # <<< deploy leverage. Set 1.0 for the unleveraged version.
LEGACY = False                   # False = honest one-day-lag signals (what live can actually do)
STRAT  = "v12"                   # "v12"/"v11"/"v10" fixed blends (holdout-validated) | "v8" old router

# ---- risk overlays (validated out-of-sample in research/backtest.py; see results.md) ----
USE_VOL_TARGET = True            # scale exposure to a constant realized-vol target
USE_DD_SCALE   = False           # tested: hurts on both dev and holdout — keep off
VOL_TARGET     = 0.16            # annualized vol target for the levered book
BIL_IDLE_CASH  = True            # park idle cash (when overlay cuts gross <1) in BIL (T-bills)

# ---------------- safety config (see SAFETY.md) ----------------
MAX_GROSS       = 2.0            # hard cap on gross exposure
MAX_DAILY_LOSS  = 0.04           # halt new orders if equity is down >4% vs yesterday's close
MAX_DRAWDOWN    = 0.25           # flatten + halt beyond this drawdown (v10 2x volT16 worst backtest DD ~27%)
MAX_ORDER_FRAC  = 0.70           # no single order may exceed 70% of equity
MAX_ORDERS      = 25             # max order actions per run
STALE_DAYS      = 6              # refuse to trade if freshest SPY/VIX bar is older than this
MIN_SYMBOLS     = 20             # refuse to trade if fewer symbols than this survived the fetch
MAX_SANE_MOVE   = 0.40           # drop a symbol whose bar-to-bar move exceeds this (bad data)
REBAL_BAND      = 0.015          # only trade if target differs from current by >1.5% of equity
IGNORE_SYMBOLS  = {"BTCUSD","ETHUSD","BTC/USD","ETH/USD","TQQQ","SOXL","SVXY","UPRO"}   # crypto_bot.py's sleeves

HERE = os.path.dirname(os.path.abspath(__file__))
log=logging.getLogger("moe"); log.setLevel(logging.INFO)
_f=logging.Formatter("%(asctime)s  %(message)s","%Y-%m-%d %H:%M:%S")
for h in (logging.handlers.RotatingFileHandler(os.path.join(HERE,"moe.log"),maxBytes=1_000_000,backupCount=3), logging.StreamHandler()):
    h.setFormatter(_f); log.addHandler(h)

# ---------------- data (Yahoo; raw close for signals, adjclose for P&L/dividends) ----------------
def yf(sym, rng="10y"):    # NOTE: range=max silently degrades to MONTHLY bars — never use it here
    for attempt in range(4):               # alternate hosts + backoff: GH runner IPs get rate-limited
        host="query1" if attempt%2==0 else "query2"
        url=f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
        try:
            if attempt: time.sleep(2*attempt)
            req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
            raw=json.load(urllib.request.urlopen(req, timeout=30))
            res=raw["chart"]["result"][0]; ts=res["timestamp"]; q=res["indicators"]["quote"][0]
            adj=(res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
            out=[]
            for i in range(len(ts)):
                c=q["close"][i]
                if c is None or c<=0: continue
                a=adj[i] if adj and i<len(adj) and adj[i] else c
                out.append({"t":ts[i],"c":c,"ac":a})
            out=G.drop_partial_bar(out)      # signals must only see COMPLETED daily bars
            if out: return out
        except Exception as e:
            if attempt==3: log.info(f"  yahoo fail {sym}: {e}")
    return []

# ---------------- fetch + data-quality gates ----------------
SYMS=C.all_symbols()
DB={s:yf(s) for s in SYMS}; DB={s:b for s,b in DB.items() if len(b)>=300}
VIXB=yf("^VIX")

def _insane(b):
    for i in range(max(1,len(b)-5),len(b)):
        if abs(b[i]["c"]/b[i-1]["c"]-1)>MAX_SANE_MOVE: return True
    return False
for s in [x for x in DB if x!="SPY" and _insane(DB[x])]:
    log.info(f"DATA GATE: {s} has a >{MAX_SANE_MOVE:.0%} bar-to-bar move in the last 5 bars — dropped as bad data")
    del DB[s]

_now=time.time(); _fatal=[]
if "SPY" not in DB: _fatal.append("no SPY data")
else:
    if not G.data_fresh(DB["SPY"][-1]["t"], _now, STALE_DAYS): _fatal.append("SPY data is stale")
    if _insane(DB["SPY"][-2:]) or abs(DB["SPY"][-1]["c"]/DB["SPY"][-2]["c"]-1)>0.20:
        _fatal.append("SPY moved >20% in one bar — data error or crash; refusing to trade")
if len(DB)<MIN_SYMBOLS: _fatal.append(f"only {len(DB)}/{len(SYMS)} symbols fetched (need {MIN_SYMBOLS})")
if not VIXB or not G.data_fresh(VIXB[-1]["t"], _now, STALE_DAYS): _fatal.append("VIX data missing/stale")
if _fatal:
    for m in _fatal: log.info(f"DATA GATE FAILED: {m}")
    log.info("refusing to trade on bad data; exiting with error status.")
    sys.exit(1)

# ---------------- strategy (shared core — identical code path to the backtest) ----------------
M   = C.build_market(DB, {C.uday(r["t"]):r["c"] for r in VIXB})
D   = C.expert_decisions(M, div=(C.ETF_DIV if STRAT in ("v10","v11","v12") else None))
HELD,SER = C.expert_series(M, D, legacy=LEGACY)
if STRAT in ("v10","v11","v12"):
    W = {"v10":C.V10_WEIGHTS,"v11":C.V11_WEIGHTS,"v12":C.V12_WEIGHTS}[STRAT]
    effS,expoS,sclS,(eff,expo,scl) = C.fixed_router(M, SER, W)
else:
    effS,expoS,sclS,(eff,expo,scl) = C.router(M, SER, legacy=LEGACY)
dl  = M["dates"]; KS=list(SER)

# risk overlays: multipliers come from PAST base-strategy returns only (no lookahead)
base=[min(LEV*sclS[t]*expoS[t],MAX_GROSS)*sum(effS[t].get(k,0.0)*SER[k][t] for k in KS) for t in dl]
m_next=1.0; onote=[]
if USE_VOL_TARGET:
    mv=C.vol_target_multipliers(base+[0.0], target=VOL_TARGET)[-1]; m_next*=mv; onote.append(f"volT {mv:.2f}")
if USE_DD_SCALE:
    md=C.dd_scale_multipliers(base+[0.0])[-1]; m_next*=md; onote.append(f"ddS {md:.2f}")

gross,_capped = G.cap_gross(LEV*scl*expo*m_next, MAX_GROSS)
if _capped: log.info(f"gross exposure capped: {LEV*scl*expo*m_next:.2f}x -> {MAX_GROSS:.2f}x (MAX_GROSS)")

tw={}
for k in KS:
    ek=eff.get(k,0.0)
    if not ek: continue
    for sym,pw in D[k][dl[-1]].items():
        tw[sym]=tw.get(sym,0.0)+gross*ek*pw
tw={s:round(v,4) for s,v in tw.items() if abs(v)>1e-4}
if BIL_IDLE_CASH:
    idle=1.0-sum(abs(v) for v in tw.values())
    if idle>0.02: tw["BIL"]=round(idle,4)          # idle cash earns T-bill yield instead of 0
regime="BULL" if M["RISKON"].get(dl[-1],True) else "BEAR"
log.info(f"{STRAT} | regime {regime} | VIX {M['VX'][dl[-1]]:.1f} | expo {expo:.2f} x vol {scl:.2f} x lev {LEV:.0f}"
         + (f" x overlay {m_next:.2f} [{', '.join(onote)}]" if onote else "") + f" = gross {gross:.2f}"
         + (" | LEGACY TIMING (do not trade)" if LEGACY else ""))
log.info(f"  expert weights: " + " ".join(f"{k}={eff.get(k,0.0):.2f}" for k in KS if eff.get(k)))
log.info(f"  TARGET book ({len(tw)} positions): " + ", ".join(f"{s} {w*100:+.0f}%" for s,w in sorted(tw.items(),key=lambda x:-abs(x[1]))))

# ---------------- execution (Alpaca, through guardrails) ----------------
def keys():
    k=os.environ.get("ALPACA_KEY"); s=os.environ.get("ALPACA_SECRET"); sf=os.path.join(HERE,"secrets.env")
    if (not k or not s) and os.path.exists(sf):
        for line in open(sf):
            if line.startswith("ALPACA_KEY="): k=line.split("=",1)[1].strip()
            if line.startswith("ALPACA_SECRET="): s=line.split("=",1)[1].strip()
    return k,s

def portfolio_history_equities(k,s):
    """Daily equity curve from Alpaca (drawdown breaker). None on failure -> FAIL CLOSED."""
    base_url="https://paper-api.alpaca.markets" if PAPER else "https://api.alpaca.markets"
    try:
        req=urllib.request.Request(base_url+"/v2/account/portfolio/history?period=1A&timeframe=1D",
            headers={"APCA-API-KEY-ID":k,"APCA-API-SECRET-KEY":s})
        d=json.load(urllib.request.urlopen(req,timeout=30))
        return [float(v) for v in d.get("equity",[]) if v]
    except Exception as e:
        log.info(f"  portfolio history unavailable ({e})")
        return None

def main(dry):
    if dry:
        log.info("DRY RUN — no orders placed. (target book above is what it WOULD hold.)")
        return
    if LEGACY:
        log.info("LEGACY=True is for research comparison only; refusing to trade."); sys.exit(1)
    K,S=keys()
    if not K or not S:
        log.info("no API keys (ALPACA_KEY/ALPACA_SECRET or secrets.env); aborting."); sys.exit(1)
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    trade=TradingClient(K,S,paper=PAPER)
    clock=trade.get_clock()
    if not clock.is_open:
        log.info(f"market closed (next {clock.next_open}); no trades."); return

    # ---- circuit breakers, checked before ANY order ----
    if os.path.exists(os.path.join(HERE,"KILL")):
        log.info("KILL file present — trading halted by operator. Delete the KILL file to resume."); return
    acct=trade.get_account(); equity=float(acct.equity); last_eq=float(acct.last_equity or equity)
    if G.daily_loss_breached(equity, last_eq, MAX_DAILY_LOSS):
        log.info(f"DAILY LOSS BREAKER: equity ${equity:,.0f} is down {(equity/last_eq-1)*100:.1f}% "
                 f"vs yesterday (limit {MAX_DAILY_LOSS:.0%}). No orders today."); return
    hist=portfolio_history_equities(K,S)
    if hist is None:
        log.info("  cannot verify drawdown (fail-closed); no orders this run."); return
    breached,dd = G.drawdown_breached(hist, equity, MAX_DRAWDOWN)
    if breached:
        log.info(f"MAX DRAWDOWN BREAKER: {dd:.1%} >= {MAX_DRAWDOWN:.0%} — flattening everything and halting.")
        try: trade.close_all_positions(cancel_orders=True)
        except Exception as e: log.info(f"  flatten failed: {e}")
        log.info("  add a KILL file / review before resuming."); return

    # ---- clean slate: cancel stale unfilled orders so rebalance math is correct ----
    try:
        cancelled=trade.cancel_orders()
        if cancelled: log.info(f"  cancelled {len(cancelled)} stale open order(s)")
    except Exception as e:
        log.info(f"  cancel_orders failed: {e}; aborting run (unknown open-order state)"); return

    pos={p.symbol:p for p in trade.get_all_positions() if p.symbol not in IGNORE_SYMBOLS}
    positions={s:(float(p.market_value),float(p.qty)) for s,p in pos.items()}
    moon_mv=sum(abs(float(p.market_value)) for p in trade.get_all_positions() if p.symbol in IGNORE_SYMBOLS)
    if moon_mv:                                  # size the core on what the moon sleeve isn't using
        equity=max(0.0, equity-moon_mv)
        log.info(f"  moon sleeve holds ${moon_mv:,.0f} (ignored); core sizes on ${equity:,.0f}")
    log.info(f"equity ${equity:,.0f} | current {len(pos)} core positions")
    def last_price(s):
        try: return float(pos[s].current_price)
        except Exception: return M["CL"][s].get(dl[-1]) if s in M["CL"] else None
    prices={s:last_price(s) for s in set(list(tw)+list(pos))}

    actions,warnings = G.plan_orders(tw, equity, positions, prices,
                                     rebal_band=REBAL_BAND, max_order_frac=MAX_ORDER_FRAC, max_orders=MAX_ORDERS)
    for w in warnings: log.info(f"  WARNING: {w}")

    # ---- execute (risk-reducing first; each order isolated; duplicate-protected per day) ----
    today=datetime.datetime.now(datetime.timezone.utc).strftime("%y%m%d")
    for a in actions:
        kind,s=a[0],a[1]
        try:
            if kind=="close":
                mv=positions.get(s,(0,0))[0]
                log.info(f"  CLOSE {s} (${mv:,.0f})"); trade.close_position(s)
                continue
            side=OrderSide.BUY if kind in ("buy","cover") else OrderSide.SELL
            oid=f"moe9-{today}-{s}-{kind}"          # broker rejects a repeat -> no double orders on re-runs
            if kind in ("short","cover"):
                log.info(f"  {kind.upper()} {s} {a[2]} sh")
                trade.submit_order(MarketOrderRequest(symbol=s, qty=a[2], side=side,
                                   time_in_force=TimeInForce.DAY, client_order_id=oid))
            else:
                log.info(f"  {kind.upper()} {s} ${a[2]:,.0f} -> target ${tw.get(s,0.0)*equity:,.0f}")
                trade.submit_order(MarketOrderRequest(symbol=s, notional=a[2], side=side,
                                   time_in_force=TimeInForce.DAY, client_order_id=oid))
        except Exception as e:
            msg=str(e)
            if "client_order_id" in msg or "duplicate" in msg.lower():
                log.info(f"    {s}: same order already sent today (duplicate protection) — skipped")
            else:
                log.info(f"    order failed {s}: {e}")
    log.info("done.")

if __name__=="__main__":
    main("--test" in sys.argv or "--dryrun" in sys.argv)
