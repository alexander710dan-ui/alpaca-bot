# Moonshot designs — P($1k->$100k in 5y), honest timing & costs

```
BTC buy & hold                             2014-09-18 .. 2026-06-30  CAGR    51.0%  Sharpe  0.95  MaxDD  83.4%
    rolling 5y entries n=2478: P(>=100x)   4.2%  P(>=10x)  58.2%  median 11.7x  worst 0.85x  best 150x
    MC 20k paths:  P(>=100x)   5.9%  P(>=10x)  46.0%  P(>=3x)  75.3%  median 8.5x  p5 0.69x  P(-80%)  0.7%
crypto trend (BTC/ETH, MA200, 1x spot)     2014-09-17 .. 2026-06-30  CAGR    56.1%  Sharpe  1.08  MaxDD  82.9%
    rolling 5y entries n=2479: P(>=100x)   0.1%  P(>=10x)  58.7%  median 12.5x  worst 1.30x  best 102x
    MC 20k paths:  P(>=100x)   4.9%  P(>=10x)  48.2%  P(>=3x)  78.6%  median 9.4x  p5 0.88x  P(-80%)  0.3%
crypto trend HAIRCUT50 (drift halved)      2014-09-17 .. 2026-06-30  CAGR    15.1%  Sharpe  0.54  MaxDD  91.7%
    rolling 5y entries n=2479: P(>=100x)   0.0%  P(>=10x)  11.0%  median 2.7x  worst 0.28x  best 22x
    MC 20k paths:  P(>=100x)   0.4%  P(>=10x)  13.4%  P(>=3x)  39.4%  median 2.0x  p5 0.19x  P(-80%)  5.3%
TQQQ trend (MA200)                         2010-02-11 .. 2026-06-30  CAGR    30.2%  Sharpe  0.84  MaxDD  50.1%
    rolling 5y entries n=2866: P(>=100x)   0.0%  P(>=10x)   1.3%  median 4.1x  worst 1.76x  best 12x
    MC 20k paths:  P(>=100x)   0.0%  P(>=10x)  13.6%  P(>=3x)  60.1%  median 3.8x  p5 0.83x  P(-80%)  0.1%
SOXL+TQQQ trend (MA200, inv-vol)           2010-02-11 .. 2026-06-30  CAGR    36.6%  Sharpe  0.88  MaxDD  62.8%
    rolling 5y entries n=2866: P(>=100x)   0.0%  P(>=10x)  13.1%  median 4.4x  worst 1.54x  best 15x
    MC 20k paths:  P(>=100x)   0.2%  P(>=10x)  24.0%  P(>=3x)  66.1%  median 4.7x  p5 0.77x  P(-80%)  0.2%
v10 2x volT16 (the validated core)         1993-01-29 .. 2026-06-30  CAGR     9.6%  Sharpe  0.65  MaxDD  29.7%
    rolling 5y entries n=7157: P(>=100x)   0.0%  P(>=10x)   0.0%  median 1.4x  worst 0.96x  best 3x
    MC 20k paths:  P(>=100x)   0.0%  P(>=10x)   0.0%  P(>=3x)   2.5%  median 1.6x  p5 0.92x  P(-80%)  0.0%
-- barbells --
BARBELL 85% v10 / 15% crypto trend         1993-01-29 .. 2026-06-30  CAGR    11.6%  Sharpe  0.81  MaxDD  30.4%
    rolling 5y entries n=7927: P(>=100x)   0.0%  P(>=10x)   0.0%  median 1.7x  worst 0.99x  best 4x
    MC 20k paths:  P(>=100x)   0.0%  P(>=10x)   0.0%  P(>=3x)   4.2%  median 1.7x  p5 1.02x  P(-80%)  0.0%
BARBELL 70% v10 / 30% crypto trend         1993-01-29 .. 2026-06-30  CAGR    13.3%  Sharpe  0.88  MaxDD  37.9%
    rolling 5y entries n=7927: P(>=100x)   0.0%  P(>=10x)   0.0%  median 1.6x  worst 1.00x  best 8x
    MC 20k paths:  P(>=100x)   0.0%  P(>=10x)   0.0%  P(>=3x)   9.9%  median 1.9x  p5 1.03x  P(-80%)  0.0%
BARBELL 50% v10 / 50% crypto trend         1993-01-29 .. 2026-06-30  CAGR    15.1%  Sharpe  0.83  MaxDD  52.7%
    rolling 5y entries n=7927: P(>=100x)   0.0%  P(>=10x)   5.2%  median 1.5x  worst 1.00x  best 19x
    MC 20k paths:  P(>=100x)   0.0%  P(>=10x)   0.1%  P(>=3x)  20.2%  median 2.0x  p5 0.93x  P(-80%)  0.0%
BARBELL 50/50 HAIRCUT50 on crypto          1993-01-29 .. 2026-06-30  CAGR     9.1%  Sharpe  0.55  MaxDD  66.9%
    rolling 5y entries n=7927: P(>=100x)   0.0%  P(>=10x)   0.0%  median 1.4x  worst 0.72x  best 9x
    MC 20k paths:  P(>=100x)   0.0%  P(>=10x)   0.0%  P(>=3x)   8.3%  median 1.5x  p5 0.71x  P(-80%)  0.0%
MAX: 60% crypto tr / 40% SOXL+TQQQ tr      2010-02-11 .. 2026-06-30  CAGR    44.7%  Sharpe  1.19  MaxDD  58.8%
    rolling 5y entries n=3636: P(>=100x)   0.0%  P(>=10x)  55.0%  median 10.9x  worst 1.40x  best 66x
    MC 20k paths:  P(>=100x)   0.1%  P(>=10x)  30.9%  P(>=3x)  79.2%  median 6.3x  p5 1.39x  P(-80%)  0.0%
MAX HAIRCUT50 on crypto leg                2010-02-11 .. 2026-06-30  CAGR    26.9%  Sharpe  0.83  MaxDD  73.2%
    rolling 5y entries n=3636: P(>=100x)   0.0%  P(>=10x)  15.2%  median 4.5x  worst 0.93x  best 27x
    MC 20k paths:  P(>=100x)   0.0%  P(>=10x)  11.2%  P(>=3x)  54.0%  median 3.3x  p5 0.73x  P(-80%)  0.1%
```
