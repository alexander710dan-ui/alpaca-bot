#!/usr/bin/env python3
"""
Writes moe_history.json each run — the growing record the live dashboard reads.

Pulls the account's daily equity curve (Alpaca portfolio history), current positions with
entry prices + P&L, and recent daily candles for each holding (Yahoo). The dashboard
(moe_live.html) fetches this file from GitHub raw, so it updates itself every day with no
new HTML. Base is the real $100k paper account; the dashboard scales to $10k / $1k views.
"""
import os, json, datetime, urllib.request
HERE=os.path.dirname(os.path.abspath(__file__))
def keys():
    k=os.environ.get("ALPACA_KEY"); s=os.environ.get("ALPACA_SECRET"); sf=os.path.join(HERE,"secrets.env")
    if (not k or not s) and os.path.exists(sf):
        for line in open(sf):
            if line.startswith("ALPACA_KEY="): k=line.split("=",1)[1].strip()
            if line.startswith("ALPACA_SECRET="): s=line.split("=",1)[1].strip()
    return k,s
K,S=keys()
H={"APCA-API-KEY-ID":K,"APCA-API-SECRET-KEY":S}
def api(path):
    r=urllib.request.Request("https://paper-api.alpaca.markets"+path, headers=H)
    return json.load(urllib.request.urlopen(r,timeout=30))
def yf(sym,rng="3mo"):
    try:
        url=f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
        r=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        raw=json.load(urllib.request.urlopen(r,timeout=30)); res=raw["chart"]["result"][0]
        ts=res["timestamp"]; q=res["indicators"]["quote"][0]; out=[]
        for i in range(len(ts)):
            o,h,l,c=q["open"][i],q["high"][i],q["low"][i],q["close"][i]
            if None in (o,h,l,c): continue
            out.append([ts[i],round(o,2),round(h,2),round(l,2),round(c,2)])
        return out
    except Exception: return []

acct=api("/v2/account"); eq=float(acct["equity"]); le=float(acct["last_equity"])
# daily equity curve (grows over time)
ph=api("/v2/account/portfolio/history?period=1A&timeframe=1D&extended_hours=true")
daily=[[t,round(v,2)] for t,v in zip(ph["timestamp"],ph["equity"]) if v]
# current positions + candles
from alpaca.trading.client import TradingClient
tc=TradingClient(K,S,paper=True)
pos={}
for p in tc.get_all_positions():
    pos[p.symbol]={"qty":float(p.qty),"entry":float(p.avg_entry_price),"cur":float(p.current_price),
                   "mv":float(p.market_value),"pl":float(p.unrealized_intraday_pl),
                   "plpc":float(p.unrealized_intraday_plpc)*100,"ohlc":yf(p.symbol)}
hist={"generated":datetime.datetime.utcnow().isoformat()+"Z","base":100000,"moe_start":"2026-06-30",
      "eq":eq,"le":le,"today_pl":eq-le,"today_pct":(eq/le-1)*100 if le else 0.0,
      "daily":daily,"pos":pos}
json.dump(hist, open(os.path.join(HERE,"moe_history.json"),"w"))
print(f"tracker: equity ${eq:,.0f} today {hist['today_pct']:+.2f}% | {len(daily)} daily pts | {len(pos)} positions")
