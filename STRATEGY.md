# Strategy research — discoveries log

This bot currently trades RSI-2 mean-reversion (see `alpaca_bot.py`). Below is the research
that beats it, for when we're ready to upgrade. **All numbers are backtests — real results
will be lower, and the leveraged versions carry genuine tail risk.**

## The best system found: HEDGED PUT-WRITE (volatility risk premium + crash hedges)

Sell ~1-month at-the-money SPY puts (harvest the volatility risk premium — implied vol runs
~3–4 points above realized, the most robust premium in markets), and **hedge the crash months**
with two negatively-correlated sleeves:
- **DEF** — hold the stronger of gold/bonds (2-month momentum), cash if both falling.
- **SHORT** — short SPY when it's below its 200-day average.

Weights: **60% put-write / 25% defensive / 15% short**, rebalanced monthly. The hedges are
−0.46 correlated to the put-write, so they win in the exact months the put-write loses.

### Results (15-year backtest, synthetic Black-Scholes pricing from VIX)
| Version | Mo+ | Mo ≥ +5% | Worst mo | CAGR | MaxDD | Years ≥ 9/12 |
|---|---|---|---|---|---|---|
| Aggressive 5× | 83% | 54% | −22% | +63% | 30% | 11 / 14 |
| Balanced 5× (+10% tail) | 82% | 46% | −19% | +54% | 25% | 10 / 14 |
| Safer 4× (+18% tail) | 80% | 29% | −14% | +37% | 16% | 10 / 14 |

**$10,000 over time (aggressive 5×):** 5 yr → ~$102k, 10 yr → ~$970k (30% drawdown).

### Refinements tested
- ✅ **Crash-insurance sleeve** (long 5% OTM monthly puts): a tunable risk dial — cuts worst
  month −22% → −14% and DD 30% → 16%, improves return/DD ratio (2.1 → 2.3), costs raw CAGR.
- ❌ **Regime-gating** (only sell puts when SPY > 200-day): made it *worse* (−48% month, 89% DD).
  Always-on hedging beats timing the regime.

## Honest risks
- **Synthetic backtest** — real options have spreads/slippage; live returns lower.
- **Tail risk is real** — leveraged short-volatility has blown up funds (XIV → ~0 in a day, 2018).
  The hedges shrink the tail (worst −14% to −22%) but a sudden overnight gap-crash could exceed it.
- **Not every year** — 2022 only hit 7/12. Crisis years still bite.
- **Needs options** — deploy via Alpaca options (paper first, always).

## Baseline comparison
- Plain RSI-2 (current bot, leveraged ETFs): survivorship-biased; a fair mix nets ~0%/yr.
- All-weather (dip-buy + gold/bonds), unleveraged: 20%/yr at 20% DD — the robust fair-universe option.
