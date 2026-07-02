# Backtest results (generated 2026-06-30, costs: 5bp/side + IRX+150bp financing, dividends in)
```

== FULL 2007-now ==
variant                               CAGR    Vol Sharpe Sortino  MaxDD WorstMo   Mo+    PF
SPY buy & hold                        10.9%   19.6%   0.63    0.88   55.2%   -16.5%    66%  1.74
v8 legacy timing 1x (old backtest)    33.4%   14.7%   2.04    3.12   11.3%    -7.4%    74%  5.49
v8 legacy + VIX=18 (as deployed) 1x    30.3%   14.7%   1.87    2.82   11.8%    -7.8%    73%  4.84
v8 HONEST timing 1x                    5.1%   15.0%   0.41    0.55   33.1%   -11.0%    52%  1.36
v8 HONEST 2x (gross cap 2)             6.6%   25.1%   0.38    0.52   39.4%   -15.2%    53%  1.32
v10 1x                                 7.2%   12.2%   0.63    0.87   21.9%    -8.7%    62%  1.64
v10 2x (gross cap 2)                  10.3%   24.3%   0.53    0.72   41.0%   -16.9%    59%  1.50
v10 2x + volT16  << DEPLOY             7.9%   16.6%   0.54    0.73   27.4%   -12.3%    59%  1.50

== DEV 2007-2019 incl GFC (selection allowed) ==
variant                               CAGR    Vol Sharpe Sortino  MaxDD WorstMo   Mo+    PF
SPY buy & hold                         8.7%   19.3%   0.53    0.75   55.2%   -16.5%    67%  1.63
v8 legacy timing 1x (old backtest)    35.1%   14.5%   2.15    3.30   10.9%    -7.4%    76%  5.98
v8 legacy + VIX=18 (as deployed) 1x    32.6%   14.5%   2.02    3.07   10.9%    -7.5%    75%  5.42
v8 HONEST timing 1x                    4.6%   14.8%   0.38    0.52   33.1%   -11.0%    52%  1.32
v8 HONEST 2x (gross cap 2)             5.7%   23.8%   0.35    0.48   39.4%   -15.2%    55%  1.29
v10 1x                                 6.2%   11.0%   0.61    0.83   18.1%    -8.7%    60%  1.60
v10 2x (gross cap 2)                   9.4%   21.9%   0.52    0.71   35.8%   -16.9%    58%  1.48
v10 2x + volT16  << DEPLOY             7.7%   16.3%   0.54    0.73   26.8%   -12.3%    58%  1.49

== HOLDOUT 2020-now (untouched) ==
variant                               CAGR    Vol Sharpe Sortino  MaxDD WorstMo   Mo+    PF
SPY buy & hold                        15.5%   20.3%   0.81    1.15   33.7%   -12.5%    64%  1.94
v8 legacy timing 1x (old backtest)    30.2%   15.1%   1.82    2.76   11.3%    -6.4%    71%  4.67
v8 legacy + VIX=18 (as deployed) 1x    25.8%   15.1%   1.60    2.35   11.8%    -7.8%    68%  3.91
v8 HONEST timing 1x                    6.0%   15.2%   0.46    0.63   24.2%    -8.1%    51%  1.45
v8 HONEST 2x (gross cap 2)             8.4%   27.5%   0.43    0.59   33.8%   -14.3%    50%  1.40
v10 1x                                 9.1%   14.2%   0.68    0.93   21.9%    -8.1%    64%  1.72
v10 2x (gross cap 2)                  12.1%   28.5%   0.55    0.74   41.0%   -16.0%    63%  1.52
v10 2x + volT16  << DEPLOY             8.3%   17.3%   0.55    0.73   27.4%    -9.7%    60%  1.51
```

## Yearly returns: honest v8 2x vs v10 2x volT16 (deploy) vs SPY
```
 year    v8 2x   v10 2x      SPY
 2007    -0.8%     6.9%     5.1%
 2008    34.9%    -7.3%   -36.8%
 2009    10.0%     6.0%    26.4%
 2010     0.8%    21.1%    15.1%
 2011     2.0%    -6.9%     1.9%
 2012    -4.1%    14.2%    16.0%
 2013    44.4%    25.3%    32.3%
 2014    -2.6%     6.3%    13.5%
 2015   -24.9%    -7.7%     1.2%
 2016    -4.5%     4.8%    12.0%
 2017    51.9%    37.8%    21.7%
 2018   -14.8%   -14.5%    -4.6%
 2019     7.8%    27.7%    31.2%
 2020     6.7%     9.5%    18.3%
 2021    13.8%    11.7%    28.7%
 2022   -24.9%   -19.6%   -18.2%
 2023    16.4%    14.2%    26.2%
 2024     3.3%     5.8%    24.9%
 2025    22.8%    21.1%    17.7%
 2026    25.1%    16.2%    10.1%
```
