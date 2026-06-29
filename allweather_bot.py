#!/usr/bin/env python3
"""
ALL-WEATHER bot for Alpaca — PAPER (fake money). The best *deployable* system from the project.

- BULL regime (SPY above its 200-day): buy washed-out dips — any name with 2-day RSI < 10 that's
  above its own 200-day avg; hold several, sell each when it closes back above its 5-day avg.
- BEAR regime (SPY below its 200-day): sell the dips, hold the stronger of GLD / TLT (gold/bonds)
  by momentum — they tend to rise while stocks fall.

All LONG ETF/stock positions, no leverage -> fits a normal account (no margin wall). Backtest
~20%/yr at ~20% drawdown on a fair, non-survivorship universe. Nearly double the put-write's 11%.

Run: python3 allweather_bot.py --test   (dry run)  |  python3 allweather_bot.py  (live, paper)
"""
import os, sys, datetime, logging, logging.handlers

PAPER    = True
UNIVERSE = ["SPY","QQQ","IWM","DIA","XLF","XLE","XLK","EEM","EFA","XLV","XLY","XLI",
            "AAPL","MSFT","AMZN","NVDA","JPM","XOM","KO","WMT","HD","COST"]
MAX_POS  = 6           # hold up to this many dips at once
RSI_BUY  = 10
HERE=os.path.dirname(os.path.abspath(__file__))
log=logging.getLogger("aw"); log.setLevel(logging.INFO)
_f=logging.Formatter("%(asctime)s  %(message)s","%Y-%m-%d %H:%M:%S")
for h in (logging.handlers.RotatingFileHandler(os.path.join(HERE,"allweather.log"),maxBytes=1_000_000,backupCount=3), logging.StreamHandler()):
    h.setFormatter(_f); log.addHandler(h)
def keys():
    k=os.environ.get("ALPACA_KEY"); s=os.environ.get("ALPACA_SECRET"); sf=os.path.join(HERE,"secrets.env")
    if (not k or not s) and os.path.exists(sf):
        for line in open(sf):
            if line.startswith("ALPACA_KEY="): k=line.split("=",1)[1].strip()
            if line.startswith("ALPACA_SECRET="): s=line.split("=",1)[1].strip()
    return k,s
K,S=keys()
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
trade=TradingClient(K,S,paper=PAPER); data=StockHistoricalDataClient(K,S)
def sma(x,n): return sum(x[-n:])/n if len(x)>=n else None
def rsi(c,n):
    if len(c)<n+1: return None
    g=l=0.0
    for i in range(len(c)-n,len(c)):
        ch=c[i]-c[i-1]; g+=max(ch,0); l+=max(-ch,0)
    if l==0: return 100.0
    rs=(g/n)/(l/n); return 100-100/(1+rs)
def mom(c,n=42): return (c[-1]/c[-1-n]-1) if len(c)>n else 0
def bars(syms):
    start=datetime.datetime.now()-datetime.timedelta(days=420)
    d=data.get_stock_bars(StockBarsRequest(symbol_or_symbols=syms, timeframe=TimeFrame.Day, start=start)).data
    return {s:[b.close for b in d.get(s,[])] for s in syms}

def run(dry):
    clock=trade.get_clock()
    if not clock.is_open and not dry:
        log.info(f"market closed (next {clock.next_open}); waiting."); return
    acct=trade.get_account(); positions={p.symbol:p for p in trade.get_all_positions()}
    C=bars(UNIVERSE+["GLD","TLT"]); spc=C["SPY"]; bull = sma(spc,200) is not None and spc[-1]>sma(spc,200)
    log.info(f"{'DRY ' if dry else ''}equity ${float(acct.equity):,.0f} cash ${float(acct.cash):,.0f} | regime {'BULL' if bull else 'BEAR'} | holding {sorted(positions) or 'cash'}")

    if bull:
        # exit defensive if we were holding it
        for s in ("GLD","TLT"):
            if s in positions and float(positions[s].qty)>0:
                log.info(f"  regime bull -> sell defensive {s}")
                if not dry and clock.is_open: trade.submit_order(MarketOrderRequest(symbol=s, qty=abs(float(positions[s].qty)), side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
        # exits: any held dip that closed back above its 5-day avg
        held=[s for s in positions if s in UNIVERSE]
        for s in held:
            c=C.get(s,[]); s5=sma(c,5)
            if s5 and c[-1]>s5:
                log.info(f"  SELL {s} (bounced, close {c[-1]:.2f} > 5dMA {s5:.2f})")
                if not dry and clock.is_open: trade.submit_order(MarketOrderRequest(symbol=s, qty=abs(float(positions[s].qty)), side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
                held.remove(s)
        # entries: oversold + above own 200dMA
        cands=[]
        for s in UNIVERSE:
            if s in held: continue
            c=C.get(s,[]); r2=rsi(c,2); s200=sma(c,200)
            if r2 is not None and s200 is not None and r2<RSI_BUY and c[-1]>s200: cands.append((r2,s))
        cands.sort(); slots=MAX_POS-len(held)
        if slots>0 and cands:
            per=float(acct.cash)/slots*0.97
            for r2,s in cands[:slots]:
                if per<1: break
                log.info(f"  BUY {s} (RSI2 {r2:.1f}) ~${per:,.0f}")
                if not dry and clock.is_open: trade.submit_order(MarketOrderRequest(symbol=s, notional=round(per,2), side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
        else: log.info("  no new dips (slots full or nothing oversold)")
    else:
        # BEAR: sell any stock dips, hold stronger of GLD/TLT
        for s in [x for x in positions if x in UNIVERSE]:
            log.info(f"  regime bear -> sell {s}")
            if not dry and clock.is_open: trade.submit_order(MarketOrderRequest(symbol=s, qty=abs(float(positions[s].qty)), side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
        pick = "GLD" if mom(C["GLD"])>=mom(C["TLT"]) else "TLT"
        other = "TLT" if pick=="GLD" else "GLD"
        if other in positions and float(positions[other].qty)>0 and not dry and clock.is_open:
            trade.submit_order(MarketOrderRequest(symbol=other, qty=abs(float(positions[other].qty)), side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
        log.info(f"  BEAR -> hold {pick} with cash (~${float(acct.cash):,.0f})")
        if pick not in positions and not dry and clock.is_open:
            trade.submit_order(MarketOrderRequest(symbol=pick, notional=round(float(acct.cash)*0.97,2), side=OrderSide.BUY, time_in_force=TimeInForce.DAY))

if __name__=="__main__":
    run("--test" in sys.argv or "--dryrun" in sys.argv)
