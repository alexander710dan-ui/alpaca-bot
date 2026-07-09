# datalab — AI-training datasets (SQLite)

Two independent SQLite databases, refreshed daily by `.github/workflows/datalab.yml`
(22:15 UTC weekdays) and committed to the repo. **Completely separate process from the
trading bots** — read-only API access, no shared code, no orders.

## bot_data.sqlite — what OUR bot does (by `bot_logger.py`)

| table | grain | contents |
|---|---|---|
| `account_snapshots` | one row per run | ts, equity, last_equity, cash, buying_power, positions_count |
| `positions` | one row per position per run | ts, symbol, qty, market_value, avg_entry, current_price, unrealized_pl(+pc) |
| `orders` | one row per order (upserted) | id, submitted_at, filled_at, symbol, side, qty/notional, filled_qty, filled_avg_price, status, client_order_id |
| `daily_equity` | one row per session | date, equity — NOTE: Alpaca stamps rows at session START (row "Jul 8" = close of Jul 7) |

`orders.client_order_id` encodes which sleeve traded (`moe9-*` = core, `moon-*` = satellite).

## news_data.sqlite — news and what the stock DID next (by `news_logger.py`)

| table | grain | contents |
|---|---|---|
| `news` | one row per article | id, created_at (UTC), headline, summary, author, source, url, symbols (comma-sep) |
| `reactions` | one row per (article, watched symbol) | event_ts, px_before, r_30m, r_2h, r_1d, r_3d, complete |

- Source: Alpaca news API (Benzinga feed), watchlist of 15 liquid names in `WATCH`.
- `px_before` = last 15-min bar close at/before the article; `r_X` = simple return from
  `px_before` to the first bar at/after each horizon (30 min, 2 h) or the 1st/3rd daily
  close after the article date. Off-hours news measures against the next session — the
  first tradeable reaction.
- `complete=0` rows are awaiting horizon maturity; each run fills what has matured.
- Training tip: join `news` to `reactions` on `news_id`; features = headline/summary text
  (+source, +time-of-day), labels = r_30m/r_2h/r_1d/r_3d. Beware: Benzinga headlines can
  be published AFTER the move they describe — r_30m is the safest causally-clean label.

```sql
-- example: training pairs for AAPL
SELECT n.created_at, n.headline, r.r_30m, r.r_1d
FROM news n JOIN reactions r ON r.news_id=n.id
WHERE r.symbol='AAPL' AND r.complete=1;
```
