# Safety & risk controls

The live bot is `moe_bot.py` (MoE v8, paper, deployed by `.github/workflows/putwrite.yml`).
Every layer below is enforced in code (`guardrails.py`, unit-tested in `tests/`) and checked
**before any order is sent**. Tunables live in the config block at the top of `moe_bot.py`.

## Emergency kill switch

Create a file named `KILL` in the repo root and push it (from any device, even the GitHub
web editor). The next run logs "trading halted by operator" and places no orders. Delete the
file to resume. Positions are NOT closed by the kill switch — close them in the Alpaca
dashboard if that's the intent.

## Automatic circuit breakers (per run, before any order)

| Breaker | Default | On trip |
|---|---|---|
| Data gates: SPY/VIX fresh (≤6 days), ≥20 symbols fetched | `STALE_DAYS`, `MIN_SYMBOLS` | exits non-zero → CI fails → GitHub emails you; no orders |
| Daily loss vs yesterday's close | 4% (`MAX_DAILY_LOSS`) | no orders today, positions kept |
| Drawdown from high-water mark (Alpaca portfolio history) | 25% (`MAX_DRAWDOWN`) | **flattens everything** and halts (fail-closed: if the history endpoint is unreadable, no orders) |
| Gross exposure cap | 2.0× (`MAX_GROSS`) | book scaled down (router can request up to ~4.2×) |
| Per-order size | 70% of equity (`MAX_ORDER_FRAC`) | order clipped, warning logged |
| Orders per run | 25 (`MAX_ORDERS`) | excess dropped, warning logged |

## Order-level protections

- **Completed bars only**: Yahoo's in-progress daily bar is dropped, so live signals match the
  close-to-close convention the backtest used (no partial-bar lookahead).
- **Stale orders cancelled** at the start of each run, so rebalance math is never based on
  phantom fills; if cancel fails, the run aborts.
- **Duplicate protection**: every order carries a deterministic `client_order_id`
  (`moe8-<date>-<sym>-<kind>`); the broker rejects a same-day repeat, so overlapping or
  re-triggered runs cannot double the book.
- **No unpriced orders**: short sizing with a missing price is skipped with a warning (the old
  code fell back to $1.00/share, which could have produced a multi-million-dollar order).
- **Sign flips close first**: long→short (or reverse) closes this run and opens next run — a
  single order crossing zero is rejected by Alpaca and would leave a half-rebalanced book.
- **Risk-reducing orders execute first** (closes → sells/covers → shorts/buys), so buying
  power is freed before it's used.

## Independent watchdog

`.github/workflows/monitor.yml` runs `monitor.py` after every US close: a read-only account
check that shares NO code with the bot (plain REST, no alpaca-py). It fails the CI run — and
GitHub emails you — on daily loss >3.5%, drawdown >20%, unreadable account, or a pile-up of
open orders. A bug that blinds the bot cannot blind the watchdog.

## Strategy honesty (read research/results.md)

The old v8 claim (34%/yr @ 1×, Sharpe 2.09) reproduces in the engine ONLY with same-day
signal application (lookahead). With honest one-day-lag timing it is ~5%/yr with a 33%
drawdown. The deployed v10 numbers in results.md are honest: costs, financing, dividends,
holdout-validated. Expect live to be at or below them.

## Moon sleeve (crypto_bot.py)

Capped at `MOON_FRACTION` (20%) + `BURST_FRACTION` (10%) of equity; long-only, so its worst
case is roughly losing the sleeves, not the account. Four legs, all gated: BTC/ETH trend
(50% of moon), TQQQ/SOXL trend (30%), SVXY only while the VIX curve is in contango (20%),
plus the day-wins BURST leg — cash most days, UPRO for one day when a panic-day setup fires
(RSI2<5 / 3 down closes / VIX spike / >2.5% down day; research/daywins.py, holdout Sharpe 0.74). The core bot sizes itself on
equity MINUS the sleeve and never touches its symbols. Honest odds:
`research/moonshot_results.md` + `research/final_results.md` — sleeve holdout 2020+:
30.8%/yr, Sharpe 1.00, MaxDD 48%; median 5y multiple ~9x, P(100x in 5y) well under 1% —
possible, never promised. The same KILL file halts it.

## Known residual risks (deliberately not hidden)

- **Once-daily market orders**: no intraday stop-loss; a crash between runs is only handled by
  the next day's breakers. At 2× gross this is a real gap risk.
- **Yahoo is an unauthenticated free feed** — the data gates catch outages/staleness and wild
  prints, but not subtly wrong prices.
- **v10's expected worst-case drawdown (~27% at 2× with the vol overlay) sits close to the
  25% flatten breaker** — in a 2022-scale event the breaker may fire and require a manual
  restart. That is intentional.

## Before ever going live with real money (checklist)

1. ≥3 months of live paper results, compared against SPY buy-and-hold and research/results.md.
2. Start at 1× (`LEV=1.0`), a small account, and `MAX_GROSS=1.0`.
3. Verify the kill-switch procedure end-to-end once, on purpose.
4. Real Alpaca data subscription (or second source) instead of Yahoo for signals.
5. Re-run `python3 research/backtest.py --refresh` and confirm live months track the engine.
