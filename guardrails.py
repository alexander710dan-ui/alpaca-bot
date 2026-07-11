#!/usr/bin/env python3
"""
Guardrails for the live bots: pure, dependency-free functions that gate every order.

Everything here is unit-tested offline (tests/test_guardrails.py) and has no network
or Alpaca dependency, so the safety logic can be verified without touching an account.

Layers (in the order the bot applies them):
  1. Data quality  — data_fresh / drop_partial_bar: never trade on stale or in-progress bars.
  2. Account level — daily_loss_breached / drawdown_breached / cap_gross: circuit breakers.
  3. Order level   — plan_orders: turns target weights into a bounded, ordered action list
                     (risk-reducing first), with per-order caps and no unpriced orders.
"""
import datetime

# ---------------- data quality ----------------

def data_fresh(last_bar_ts, now_ts, max_age_days):
    """True if the most recent bar is within max_age_days of now (both unix seconds)."""
    if not last_bar_ts:
        return False
    return (now_ts - last_bar_ts) <= max_age_days * 86400

def drop_partial_bar(bars, now=None):
    """Remove the final bar if it belongs to the current UTC day.

    Yahoo includes the live, in-progress bar during market hours. The backtest was built
    on completed daily closes, so signals must only ever see completed bars.
    bars: list of dicts with a unix-seconds "t" key. Returns a (possibly shorter) list.
    """
    if not bars:
        return bars
    now = now or datetime.datetime.now(datetime.timezone.utc)
    last_day = datetime.datetime.fromtimestamp(bars[-1]["t"], datetime.timezone.utc).date()
    if last_day == now.date():
        return bars[:-1]
    return bars

# ---------------- account-level circuit breakers ----------------

def daily_loss_breached(equity, last_equity, max_daily_loss):
    """True if today's loss vs yesterday's close exceeds max_daily_loss (e.g. 0.04 = 4%)."""
    if not last_equity or last_equity <= 0:
        return False
    return (equity / last_equity - 1.0) <= -abs(max_daily_loss)

def drawdown_breached(equity_history, equity, max_drawdown):
    """(breached, drawdown) vs the high-water mark of equity_history + current equity.

    equity_history: list of past equity values (may be empty -> never breached).
    """
    peak = max(equity_history + [equity]) if equity_history else equity
    if peak <= 0:
        return False, 0.0
    dd = (peak - equity) / peak
    return dd >= abs(max_drawdown), dd

def cap_gross(gross, max_gross):
    """Clamp gross exposure. Returns (capped_gross, was_capped)."""
    if gross > max_gross:
        return max_gross, True
    return gross, False

# ---------------- order planning ----------------

def plan_orders(targets, equity, positions, prices, rebal_band=0.015,
                max_order_frac=0.70, max_orders=25, band_overrides=None):
    """Turn target weights into a bounded list of order actions.

    targets:   {sym: weight}  (negative weight = short target)
    equity:    account equity in dollars
    positions: {sym: (market_value, qty)} for currently held positions
    prices:    {sym: last price or None}
    Returns (actions, warnings). Actions, already sorted risk-reducing-first:
      ("close", sym)           close the whole position by exact qty
      ("cover", sym, shares)   buy back N whole shares of a short
      ("sell",  sym, notional) reduce a long by $notional
      ("short", sym, shares)   sell short N whole shares
      ("buy",   sym, notional) add to a long by $notional

    Rules enforced:
      - a sign flip (long->short or short->long) only CLOSES this run; the new side
        opens next run (a single order crossing zero is rejected by the broker)
      - short/cover orders are SKIPPED (with a warning) if no reliable price exists —
        never fall back to a fake price for sizing
      - every order is capped at max_order_frac * equity
      - at most max_orders actions; the rest are dropped with a warning
    """
    warnings = []
    closes, reduces, adds = [], [], []
    want = {s: targets.get(s, 0.0) * equity for s in set(targets) | set(positions)}
    cap_notional = max_order_frac * equity

    for s in sorted(want):
        wnot = want[s]
        mv, qty = positions.get(s, (0.0, 0.0))
        if abs(wnot) < 1:                               # not in target book
            if s in positions:
                closes.append(("close", s))
            continue
        if (mv > 1 and wnot < -1) or (mv < -1 and wnot > 1):    # sign flip
            closes.append(("close", s))
            warnings.append(f"{s}: target flips sign; closing now, opening next run")
            continue
        delta = wnot - mv
        band = (band_overrides or {}).get(s, rebal_band)
        if abs(delta) < band * equity:                  # inside the (per-symbol) rebalance band
            continue
        if wnot < 0:                                    # short book: whole shares only
            px = prices.get(s)
            if not px or px <= 0:
                warnings.append(f"{s}: no reliable price for short sizing; order SKIPPED")
                continue
            tgt_sh = int(min(abs(wnot), cap_notional) / px)
            cur_sh = int(abs(qty)) if qty < 0 else 0
            d = tgt_sh - cur_sh
            if d >= 1:
                adds.append(("short", s, d))
            elif d <= -1:
                reduces.append(("cover", s, -d))
        else:                                           # long book: notional (fractional ok)
            if delta < 0:
                if abs(delta) >= abs(mv) * 0.98:
                    closes.append(("close", s))
                else:
                    reduces.append(("sell", s, round(min(abs(delta), cap_notional), 2)))
            else:
                amt = min(delta, cap_notional)
                if amt < delta - 1:
                    warnings.append(f"{s}: buy capped at {max_order_frac:.0%} of equity "
                                    f"(${amt:,.0f} of ${delta:,.0f})")
                adds.append(("buy", s, round(amt, 2)))

    actions = closes + reduces + adds                   # risk-reducing first
    if len(actions) > max_orders:
        warnings.append(f"{len(actions)} actions planned; only first {max_orders} kept "
                        f"(runaway-trading protection)")
        actions = actions[:max_orders]
    return actions, warnings
