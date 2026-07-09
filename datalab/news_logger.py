#!/usr/bin/env python3
"""
News -> price-reaction logger -> datalab/news_data.sqlite  (AI-training dataset #2)

Two passes per run, fully independent of the trading bots:
  1. COLLECT — pull new articles (Alpaca news API, Benzinga feed) for the watchlist since
     the newest article already stored (first run backfills 30 days), and create one
     reaction row per (article, watched symbol).
  2. FILL — for reaction rows whose horizons have matured, compute what the stock DID:
     px_before   last 15-min close at/before the article timestamp
     r_30m/r_2h  first 15-min close >= event+30m / +2h, vs px_before
     r_1d/r_3d   1st / 3rd daily close AFTER the article date, vs px_before
     (news outside market hours naturally uses the next session's bars — which is the
      first tradeable reaction anyway). Rows are marked complete when r_3d is known or
      after 10 days (partial data kept, NULLs preserved).

Label semantics for training: r_* are simple returns; sign/magnitude = the reaction.
"""
import os, sys, json, sqlite3, datetime, urllib.parse, urllib.request

HERE=os.path.dirname(os.path.abspath(__file__))
ROOT=os.path.dirname(HERE)
DB=os.path.join(HERE,"news_data.sqlite")
WATCH=["SPY","QQQ","AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","TQQQ","GLD","TLT","XLK","JPM","XOM"]
BACKFILL_DAYS=30

def keys():
    k=os.environ.get("ALPACA_KEY"); s=os.environ.get("ALPACA_SECRET"); sf=os.path.join(ROOT,"secrets.env")
    if (not k or not s) and os.path.exists(sf):
        for line in open(sf):
            if line.startswith("ALPACA_KEY="): k=line.split("=",1)[1].strip()
            if line.startswith("ALPACA_SECRET="): s=line.split("=",1)[1].strip()
    return k,s

def api(url,k,s):
    req=urllib.request.Request(url, headers={"APCA-API-KEY-ID":k,"APCA-API-SECRET-KEY":s})
    return json.load(urllib.request.urlopen(req,timeout=30))

SCHEMA="""
CREATE TABLE IF NOT EXISTS news(
  id INTEGER PRIMARY KEY,         -- Alpaca/Benzinga article id
  created_at TEXT, updated_at TEXT,
  headline TEXT, summary TEXT, author TEXT, source TEXT, url TEXT,
  symbols TEXT);                  -- comma-separated, ALL symbols tagged on the article
CREATE TABLE IF NOT EXISTS reactions(
  news_id INTEGER NOT NULL, symbol TEXT NOT NULL,
  event_ts TEXT NOT NULL,         -- article created_at (UTC ISO)
  px_before REAL, r_30m REAL, r_2h REAL, r_1d REAL, r_3d REAL,
  complete INTEGER DEFAULT 0,
  PRIMARY KEY(news_id,symbol));
CREATE INDEX IF NOT EXISTS idx_news_created ON news(created_at);
CREATE INDEX IF NOT EXISTS idx_re_sym ON reactions(symbol,event_ts);
"""

def collect(con,k,s):
    row=con.execute("SELECT MAX(created_at) FROM news").fetchone()
    start=row[0] or (datetime.datetime.now(datetime.timezone.utc)
                     -datetime.timedelta(days=BACKFILL_DAYS)).isoformat(timespec="seconds")
    token=""; added=0
    while True:
        url=("https://data.alpaca.markets/v1beta1/news?symbols="+",".join(WATCH)
             +f"&start={urllib.parse.quote(start)}&limit=50&sort=asc&include_content=false"
             +(f"&page_token={urllib.parse.quote(token)}" if token else ""))
        d=api(url,k,s)
        for a in d.get("news",[]):
            cur=con.execute("""INSERT OR IGNORE INTO news VALUES(?,?,?,?,?,?,?,?,?)""",
                (a["id"],a["created_at"],a.get("updated_at"),a.get("headline"),a.get("summary"),
                 a.get("author"),a.get("source"),a.get("url"),",".join(a.get("symbols",[]))))
            added+=cur.rowcount
            for sym in a.get("symbols",[]):
                if sym in WATCH:
                    con.execute("INSERT OR IGNORE INTO reactions(news_id,symbol,event_ts) VALUES(?,?,?)",
                                (a["id"],sym,a["created_at"]))
        token=d.get("next_page_token")
        if not token: break
    con.commit()
    return added

def bars15(sym,start,end,k,s):
    out=[]; token=""
    while True:
        url=(f"https://data.alpaca.markets/v2/stocks/{sym}/bars?timeframe=15Min"
             f"&start={urllib.parse.quote(start)}&end={urllib.parse.quote(end)}&feed=iex&limit=10000"
             +(f"&page_token={urllib.parse.quote(token)}" if token else ""))
        d=api(url,k,s)
        out+=[(b["t"],b["c"]) for b in d.get("bars") or []]
        token=d.get("next_page_token")
        if not token: break
    return out

def bars_daily(sym,start,k,s):
    url=(f"https://data.alpaca.markets/v2/stocks/{sym}/bars?timeframe=1Day"
         f"&start={start}&adjustment=split&feed=iex&limit=10000")
    return [(b["t"][:10],b["c"]) for b in (api(url,k,s).get("bars") or [])]

def fill(con,k,s):
    now=datetime.datetime.now(datetime.timezone.utc)
    rows=con.execute("SELECT news_id,symbol,event_ts FROM reactions WHERE complete=0").fetchall()
    bysym={}
    for nid,sym,ts in rows: bysym.setdefault(sym,[]).append((nid,ts))
    filled=0
    for sym,items in bysym.items():
        tmin=min(ts for _,ts in items)
        start=(datetime.datetime.fromisoformat(tmin.replace("Z","+00:00"))-datetime.timedelta(days=2))
        try:
            b15=bars15(sym,start.isoformat().replace("+00:00","Z"),now.isoformat(timespec="seconds").replace("+00:00","Z"),k,s)
            bd=bars_daily(sym,start.date().isoformat(),k,s)
        except Exception as e:
            print(f"  {sym}: bar fetch failed ({e}); skipped"); continue
        for nid,ts in items:
            ev=datetime.datetime.fromisoformat(ts.replace("Z","+00:00"))
            age_days=(now-ev).total_seconds()/86400
            before=[c for t,c in b15 if t<=ev.isoformat().replace("+00:00","Z")]
            px=before[-1] if before else None
            def horizon(minutes):
                cut=(ev+datetime.timedelta(minutes=minutes)).isoformat().replace("+00:00","Z")
                after=[c for t,c in b15 if t>=cut]
                return (after[0]/px-1) if (px and after) else None
            dcl=[c for d_,c in bd if d_>ev.date().isoformat()]
            r30=horizon(30); r2h=horizon(120)
            r1d=(dcl[0]/px-1) if (px and len(dcl)>=1) else None
            r3d=(dcl[2]/px-1) if (px and len(dcl)>=3) else None
            complete=1 if (r3d is not None or age_days>10) else 0
            con.execute("""UPDATE reactions SET px_before=?,r_30m=?,r_2h=?,r_1d=?,r_3d=?,complete=?
                           WHERE news_id=? AND symbol=?""",(px,r30,r2h,r1d,r3d,complete,nid,sym))
            filled+=complete
    con.commit()
    return filled

def main():
    k,s=keys()
    if not k: print("news_logger: no keys"); return 1
    con=sqlite3.connect(DB); con.executescript(SCHEMA)
    added=collect(con,k,s)
    done=fill(con,k,s)
    n_news=con.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    n_re=con.execute("SELECT COUNT(*) FROM reactions").fetchone()[0]
    n_done=con.execute("SELECT COUNT(*) FROM reactions WHERE complete=1").fetchone()[0]
    con.execute("VACUUM"); con.close()
    print(f"news_logger: +{added} articles this run | total {n_news} articles, "
          f"{n_re} reactions ({n_done} complete)")
    return 0

if __name__=="__main__":
    sys.exit(main())
