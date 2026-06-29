#!/usr/bin/env python3
"""
Shadow accounting for the live put-write bot.

The account only TRADES 1x (all the margin allows). But each run this reads the day's actual
strategy return and projects what 1x / 2x / 5x WOULD have done, from both a $100k and a $10k
start. Nothing extra is traded — it's pure math on the real daily move, logged + saved so you
can compare all the leverage and account-size variants side by side.

(Leverage scaling is a first-order projection: a 5x version earns ~5x the day's 1x return.
Real leverage would also pay extra margin costs and carry the crash tail we keep flagging.)
"""
import os, json, datetime
HERE=os.path.dirname(os.path.abspath(__file__))
def keys():
    k=os.environ.get("ALPACA_KEY"); s=os.environ.get("ALPACA_SECRET")
    sf=os.path.join(HERE,"secrets.env")
    if (not k or not s) and os.path.exists(sf):
        for line in open(sf):
            if line.startswith("ALPACA_KEY="): k=line.split("=",1)[1].strip()
            if line.startswith("ALPACA_SECRET="): s=line.split("=",1)[1].strip()
    return k,s
K,S=keys()
from alpaca.trading.client import TradingClient
trade=TradingClient(K,S,paper=True)
E=float(trade.get_account().equity)

LEVS=[1,2,5]; BASES=[100000,10000]
sf=os.path.join(HERE,"shadow_state.json")
if os.path.exists(sf):
    st=json.load(open(sf))
else:
    st={"last_equity":E,"curves":{f"{lev}x_{b}":float(b) for lev in LEVS for b in BASES},"history":[]}

r = (E-st["last_equity"])/st["last_equity"] if st["last_equity"] else 0.0
for lev in LEVS:
    for b in BASES:
        st["curves"][f"{lev}x_{b}"] *= (1 + lev*r)
st["last_equity"]=E
st["history"].append([datetime.date.today().isoformat(), round(r*100,3)])
st["history"]=st["history"][-400:]
json.dump(st, open(sf,"w"), indent=1)

def m(x): return "$"+format(round(x),",")
print(f"=== SHADOW ACCOUNTING  (today's actual 1x move: {r*100:+.3f}%) ===")
print(f"{'leverage':>9s} | {'from $100,000':>14s} | {'from $10,000':>13s}")
for lev in LEVS:
    print(f"{str(lev)+'x':>9s} | {m(st['curves'][f'{lev}x_100000']):>14s} | {m(st['curves'][f'{lev}x_10000']):>13s}")
days=len(st["history"])
print(f"(tracking since {st['history'][0][0]}, {days} day{'s' if days!=1 else ''} of real moves)")
