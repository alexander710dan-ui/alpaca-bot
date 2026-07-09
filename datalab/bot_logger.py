#!/usr/bin/env python3
"""
Bot data logger -> datalab/bot_data.sqlite  (AI-training dataset #1)

Read-only snapshot of everything the trading account does, appended once per run.
Completely separate process from the bots: shares no code with them, places no orders.
Schema documented in datalab/README.md. Idempotent: safe to run any number of times.
"""
import os, sys, json, sqlite3, datetime, urllib.request

HERE=os.path.dirname(os.path.abspath(__file__))
ROOT=os.path.dirname(HERE)
DB=os.path.join(HERE,"bot_data.sqlite")

def keys():
    k=os.environ.get("ALPACA_KEY"); s=os.environ.get("ALPACA_SECRET"); sf=os.path.join(ROOT,"secrets.env")
    if (not k or not s) and os.path.exists(sf):
        for line in open(sf):
            if line.startswith("ALPACA_KEY="): k=line.split("=",1)[1].strip()
            if line.startswith("ALPACA_SECRET="): s=line.split("=",1)[1].strip()
    return k,s

def api(path,k,s,base="https://paper-api.alpaca.markets"):
    req=urllib.request.Request(base+path, headers={"APCA-API-KEY-ID":k,"APCA-API-SECRET-KEY":s})
    return json.load(urllib.request.urlopen(req,timeout=30))

SCHEMA="""
CREATE TABLE IF NOT EXISTS account_snapshots(
  ts TEXT NOT NULL,               -- UTC ISO timestamp of the snapshot
  equity REAL, last_equity REAL, cash REAL, buying_power REAL, positions_count INTEGER);
CREATE TABLE IF NOT EXISTS positions(
  ts TEXT NOT NULL, symbol TEXT NOT NULL,
  qty REAL, market_value REAL, avg_entry REAL, current_price REAL,
  unrealized_pl REAL, unrealized_plpc REAL);
CREATE TABLE IF NOT EXISTS orders(
  id TEXT PRIMARY KEY,            -- Alpaca order id (upserted; terminal state wins)
  submitted_at TEXT, filled_at TEXT, symbol TEXT, side TEXT,
  qty REAL, notional REAL, filled_qty REAL, filled_avg_price REAL,
  status TEXT, client_order_id TEXT);
CREATE TABLE IF NOT EXISTS daily_equity(
  date TEXT PRIMARY KEY,          -- session date; note Alpaca stamps rows at session START
  equity REAL);
CREATE INDEX IF NOT EXISTS idx_pos_ts ON positions(ts);
CREATE INDEX IF NOT EXISTS idx_pos_sym ON positions(symbol);
"""

def main():
    k,s=keys()
    if not k: print("bot_logger: no keys"); return 1
    con=sqlite3.connect(DB); con.executescript(SCHEMA)
    now=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    a=api("/v2/account",k,s)
    pos=api("/v2/positions",k,s)
    con.execute("INSERT INTO account_snapshots VALUES(?,?,?,?,?,?)",
        (now,float(a["equity"]),float(a.get("last_equity") or 0),float(a["cash"]),
         float(a.get("buying_power") or 0),len(pos)))
    for p in pos:
        con.execute("INSERT INTO positions VALUES(?,?,?,?,?,?,?,?)",
            (now,p["symbol"],float(p["qty"]),float(p["market_value"]),float(p["avg_entry_price"]),
             float(p["current_price"]),float(p["unrealized_pl"]),float(p["unrealized_plpc"])))
    since=(datetime.date.today()-datetime.timedelta(days=10)).isoformat()
    for o in api(f"/v2/orders?status=all&limit=200&after={since}T00:00:00Z",k,s):
        con.execute("""INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET filled_at=excluded.filled_at,
                       filled_qty=excluded.filled_qty, filled_avg_price=excluded.filled_avg_price,
                       status=excluded.status""",
            (o["id"],o.get("submitted_at"),o.get("filled_at"),o["symbol"],o["side"],
             float(o["qty"]) if o.get("qty") else None, float(o["notional"]) if o.get("notional") else None,
             float(o.get("filled_qty") or 0), float(o["filled_avg_price"]) if o.get("filled_avg_price") else None,
             o["status"],o.get("client_order_id")))
    h=api("/v2/account/portfolio/history?period=3M&timeframe=1D",k,s)
    for t,v in zip(h["timestamp"],h["equity"]):
        if v:
            con.execute("INSERT INTO daily_equity VALUES(?,?) ON CONFLICT(date) DO UPDATE SET equity=excluded.equity",
                (datetime.date.fromtimestamp(t).isoformat(),float(v)))
    con.commit()
    n={t:con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
       for t in ("account_snapshots","positions","orders","daily_equity")}
    con.close()
    print(f"bot_logger: {n}")
    return 0

if __name__=="__main__":
    sys.exit(main())
