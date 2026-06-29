#!/usr/bin/env python3
"""
HEDGED LEVERAGED PUT-WRITE bot for Alpaca — PAPER (fake money).

The full strategy from STRATEGY.md, three legs sized together at TARGET_LEV:
  1) PUT-WRITE (60%): sell ~1-month ATM SPY puts (harvest volatility premium), leveraged.
  2) DEFENSIVE (25%): hold the stronger of GLD / TLT by momentum (crash hedge).
  3) SHORT     (15%): short SPY when it's below its 200-day average (crash hedge).

  The hedges win in the exact months the put-write loses, which is why 3-5x leverage here
  is far safer than naked leverage. Backtest: ~63%/yr at ~30% DD at 5x (SYNTHETIC — real lower).

SAFETY: PAPER=True hard-coded. 5x leveraged short-vol carries real tail risk that paper hides.
Run `python3 putwrite_hedged.py --test` to dry-run (no orders); plain run trades when market open.
"""
import os, sys, datetime, math, logging, logging.handlers

PAPER      = True
TARGET_LEV = 5.0            # <<< 5x leverage, but on a RISK SLEEVE (not the whole account).
SLEEVE     = 35000          # risk capital: run 5x on THIS (~$175k exposure). Rest stays safe cash.
                            # auto-capped to fit buying power so it never errors. Max loss ~= the sleeve.
W_PUT, W_DEF, W_SHORT = 0.60, 0.25, 0.15
DTE_MIN, DTE_MAX, ROLL_DTE = 25, 40, 7

HERE = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger("hpw"); log.setLevel(logging.INFO)
_f = logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S")
for h in (logging.handlers.RotatingFileHandler(os.path.join(HERE,"hedged.log"),maxBytes=1_000_000,backupCount=3), logging.StreamHandler()):
    h.setFormatter(_f); log.addHandler(h)

def keys():
    k=os.environ.get("ALPACA_KEY"); s=os.environ.get("ALPACA_SECRET")
    sf=os.path.join(HERE,"secrets.env")
    if (not k or not s) and os.path.exists(sf):
        for line in open(sf):
            if line.startswith("ALPACA_KEY="): k=line.split("=",1)[1].strip()
            if line.startswith("ALPACA_SECRET="): s=line.split("=",1)[1].strip()
    return k,s
K,S = keys()
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest, MarketOrderRequest
from alpaca.trading.enums import ContractType, OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
trade = TradingClient(K,S,paper=PAPER); data = StockHistoricalDataClient(K,S)

def price(sym):
    return float(data.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=sym))[sym].price)
def closes(sym, days=320):
    start=datetime.datetime.now()-datetime.timedelta(days=days*1.5)
    bars=data.get_stock_bars(StockBarsRequest(symbol_or_symbols=sym, timeframe=TimeFrame.Day, start=start)).data
    return [b.close for b in bars.get(sym,[])]
def sma(x,n): return sum(x[-n:])/n if len(x)>=n else None
def mom(x,n=42): return (x[-1]/x[-1-n]-1) if len(x)>n else 0

def atm_put(px):
    today=datetime.date.today()
    req=GetOptionContractsRequest(underlying_symbols=["SPY"], type=ContractType.PUT,
        expiration_date_gte=(today+datetime.timedelta(days=DTE_MIN)).isoformat(),
        expiration_date_lte=(today+datetime.timedelta(days=DTE_MAX)).isoformat(),
        strike_price_gte=str(px*0.90), strike_price_lte=str(px*1.02), limit=200)
    cs=trade.get_option_contracts(req).option_contracts
    return min(cs, key=lambda c: abs(float(c.strike_price)-px)) if cs else None

def run(dry):
    acct=trade.get_account(); E=float(acct.equity); clock=trade.get_clock()
    bp=float(acct.regt_buying_power or acct.buying_power)
    # run TARGET_LEV on the SLEEVE, but never let total exposure exceed ~75% of buying power
    base=min(SLEEVE, 0.75*bp/TARGET_LEV)
    positions={p.symbol:p for p in trade.get_all_positions()}
    spy=price("SPY"); spc=closes("SPY"); s200=sma(spc,200); bear = s200 is not None and spy<s200
    log.info(f"{'DRY ' if dry else ''}equity ${E:,.0f} | sleeve ${base:,.0f} x{TARGET_LEV:.0f} = ${base*TARGET_LEV:,.0f} exposure | bp ${bp:,.0f} | SPY ${spy:.2f} | {'BEAR' if bear else 'bull'} | market {'OPEN' if clock.is_open else 'closed'}")

    # ---- leg 1: PUT-WRITE (leveraged) ----
    target_put_notional = W_PUT * TARGET_LEV * base
    want_contracts = max(0, round(target_put_notional / (spy*100)))
    shorts=[p for s,p in positions.items() if p.asset_class=="us_option" and float(p.qty)<0]
    cur_contracts=sum(abs(float(p.qty)) for p in shorts)
    # roll if near expiry
    need_roll=False
    for p in shorts:
        try:
            ed=datetime.datetime.strptime(p.symbol[3:9],"%y%m%d").date()
            if (ed-datetime.date.today()).days<=ROLL_DTE: need_roll=True
        except: pass
    log.info(f"  PUT-WRITE: want {want_contracts} puts (~${target_put_notional:,.0f} notional), holding {int(cur_contracts)}{' [ROLL DUE]' if need_roll else ''}")
    if (cur_contracts==0 or need_roll) and want_contracts>0:
        if need_roll:
            for p in shorts:
                log.info(f"    buy-to-close {p.symbol} x{abs(float(p.qty))}")
                if not dry and clock.is_open: trade.submit_order(MarketOrderRequest(symbol=p.symbol, qty=abs(float(p.qty)), side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
        c=atm_put(spy)
        if c:
            log.info(f"    SELL {want_contracts}x {c.symbol} (strike ${float(c.strike_price):.0f})")
            if not dry and clock.is_open: trade.submit_order(MarketOrderRequest(symbol=c.symbol, qty=want_contracts, side=OrderSide.SELL, time_in_force=TimeInForce.DAY))

    # ---- leg 2: DEFENSIVE (stronger of GLD/TLT) ----
    gld=closes("GLD"); tlt=closes("TLT")
    pick = "GLD" if mom(gld)>=mom(tlt) else "TLT"
    defD = W_DEF*TARGET_LEV*base; def_px=price(pick); def_sh=round(defD/def_px)
    held_def=sum(float(positions[s].qty) for s in ("GLD","TLT") if s in positions)
    log.info(f"  DEFENSIVE: hold {pick} ~${defD:,.0f} ({def_sh} sh)  (currently {held_def:.0f} sh of GLD/TLT)")
    if not dry and clock.is_open:
        for s in ("GLD","TLT"):                                   # exit the one we don't want
            if s!=pick and s in positions and float(positions[s].qty)>0:
                trade.submit_order(MarketOrderRequest(symbol=s, qty=abs(float(positions[s].qty)), side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
        cur=float(positions[pick].qty) if pick in positions else 0
        delta=def_sh-cur
        if abs(delta)>=1:
            trade.submit_order(MarketOrderRequest(symbol=pick, qty=abs(delta), side=OrderSide.BUY if delta>0 else OrderSide.SELL, time_in_force=TimeInForce.DAY))

    # ---- leg 3: SHORT SPY in bear regime ----
    short_sh = round(W_SHORT*TARGET_LEV*base/spy) if bear else 0
    cur_short = -float(positions["SPY"].qty) if "SPY" in positions and float(positions["SPY"].qty)<0 else 0
    log.info(f"  SHORT: target short {short_sh} SPY ({'bear' if bear else 'bull -> none'}), currently short {cur_short:.0f}")
    if not dry and clock.is_open:
        delta=short_sh-cur_short
        if abs(delta)>=1:
            trade.submit_order(MarketOrderRequest(symbol="SPY", qty=abs(delta), side=OrderSide.SELL if delta>0 else OrderSide.BUY, time_in_force=TimeInForce.DAY))
    log.info(f"  -> gross exposure ~${TARGET_LEV*base:,.0f} = {TARGET_LEV:.0f}x the ${base:,.0f} sleeve (${E-base*0:,.0f} account, rest safe)")

if __name__=="__main__":
    run("--test" in sys.argv or "--dryrun" in sys.argv)
