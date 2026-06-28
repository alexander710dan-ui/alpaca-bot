#!/usr/bin/env python3
"""
Hedged PUT-WRITE bot for Alpaca — PAPER (fake money), CASH-SECURED on-ramp.

Strategy (the consistent-monthly-income engine from STRATEGY.md):
  - Sell ~1-month at-the-money SPY puts to harvest the volatility risk premium.
  - Park the rest in a defensive sleeve (stronger of GLD/TLT by momentum) as a crash hedge.
  - Roll the put when it gets close to expiry.

SAFETY — read this:
  * PAPER = True (fake money) is hard-coded.
  * CONTRACTS starts at 1 (cash-secured ~1x). This is the SAFE on-ramp.
  * The backtested "x5" version raises CONTRACTS to use margin — that is where both the
    huge returns AND the blow-up risk live. Leveraged short puts can lose far more than the
    backtest in an overnight gap-crash (see XIV, Feb 2018, -96% in a day). Do NOT raise
    leverage until you've watched this run through a real down month and understand it.

Run:
  python3 putwrite_bot.py --test     # dry run: show what it would do, no orders
  python3 putwrite_bot.py            # one real check (paper)
"""
import os, sys, datetime, logging, logging.handlers, math

PAPER     = True       # fake money. Do not change.
UNDERLYING= "SPY"
CONTRACTS = 1          # 1 = cash-secured on-ramp. Raising this = leverage = danger.
DTE_MIN, DTE_MAX = 25, 40   # target ~1-month expiry
ROLL_DTE  = 7          # roll the put when fewer than this many days to expiry
DEF_FRACTION = 0.0     # fraction of spare cash in GLD/TLT hedge (0 while learning; raise later)

HERE = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger("pw"); log.setLevel(logging.INFO)
_f = logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S")
for h in (logging.handlers.RotatingFileHandler(os.path.join(HERE,"putwrite.log"),maxBytes=1_000_000,backupCount=3),
          logging.StreamHandler()):
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
from alpaca.trading.requests import GetOptionContractsRequest, MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import ContractType, OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest
trade = TradingClient(K,S,paper=PAPER)
data  = StockHistoricalDataClient(K,S)

def spy_price():
    t=data.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=UNDERLYING))
    return float(t[UNDERLYING].price)

def find_atm_put(px):
    today=datetime.date.today()
    req=GetOptionContractsRequest(underlying_symbols=[UNDERLYING], type=ContractType.PUT,
        expiration_date_gte=(today+datetime.timedelta(days=DTE_MIN)).isoformat(),
        expiration_date_lte=(today+datetime.timedelta(days=DTE_MAX)).isoformat(),
        strike_price_gte=str(px*0.90), strike_price_lte=str(px*1.02), limit=200)
    cs=trade.get_option_contracts(req).option_contracts
    if not cs: return None
    return min(cs, key=lambda c: abs(float(c.strike_price)-px))   # closest to ATM

def open_short_puts():
    return [p for p in trade.get_all_positions() if p.asset_class=="us_option" and float(p.qty)<0]

def run(dry):
    acct=trade.get_account()
    clock=trade.get_clock()
    px=spy_price()
    shorts=open_short_puts()
    log.info(f"{'DRY ' if dry else ''}check | equity ${float(acct.equity):,.0f} | {UNDERLYING} ${px:.2f} | market {'OPEN' if clock.is_open else 'closed'} | short puts: {[p.symbol for p in shorts]}")
    # decide: roll if existing put near expiry, else open if none
    need_new = not shorts
    for p in shorts:
        exp=p.symbol[len(UNDERLYING):len(UNDERLYING)+6]   # YYMMDD in OCC symbol
        try:
            ed=datetime.datetime.strptime(exp,"%y%m%d").date(); dte=(ed-datetime.date.today()).days
            if dte<=ROLL_DTE:
                log.info(f"  put {p.symbol} has {dte} DTE -> roll (buy to close)")
                if not dry and clock.is_open:
                    trade.submit_order(MarketOrderRequest(symbol=p.symbol, qty=abs(float(p.qty)), side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
                need_new=True
        except Exception as e: log.info(f"  parse exp err {e}")
    if need_new:
        c=find_atm_put(px)
        if not c: log.info("  no suitable put found"); return
        log.info(f"  SELL {CONTRACTS}x {c.symbol} (strike ${float(c.strike_price):.0f}, exp {c.expiration_date}) — cash-secured put-write")
        if not dry and clock.is_open:
            trade.submit_order(MarketOrderRequest(symbol=c.symbol, qty=CONTRACTS, side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
    else:
        log.info("  holding current put, nothing to do")

if __name__=="__main__":
    run("--test" in sys.argv or "--dryrun" in sys.argv)
