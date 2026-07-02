# Edge factory — ranked results (protocol in edge_factory.py)

```
edge             rationale                                      DEV S/CAGR   VAL S/CAGR  verdict      HOLDOUT
qqq_bh           baseline: NASDAQ beta                            1.08/+18     0.93/+18     PASS             
spy_bh           baseline: US equity beta                         0.98/+14     0.83/+12     PASS             
trend2_tsmom     12-1 TSMOM, inv-vol, 8 assets                    0.89/+10      0.77/+9     PASS     0.74/+11
turbo_trend      TQQQ/SOXL above 200dma, inv-vol                  0.88/+32     0.66/+22     PASS     0.99/+51
ethbtc_relmom    stronger of BTC/ETH by 63d mom                   1.55/+99    -0.03/-15     DEAD             
tqqq_vix_reg     TQQQ in uptrend + VIX<25 regime                  1.10/+40      0.37/+7     PASS     0.68/+23
tom_upro         turn-of-month on 3x SPY                          0.79/+17     0.66/+16     PASS     0.56/+14
crypto_trend     BTC/ETH above 200dma, inv-vol                   1.77/+122    -0.35/-22     DEAD             
core_qqx         strongest of SPY/QQQ/XLK in uptrend               0.87/+9      0.50/+6     PASS     0.91/+15
tom_spy          turn-of-month flows, SPY                          0.73/+6      0.64/+6     PASS      0.57/+6
burst_tqqq       panic-day 1-day holds, 3x NASDAQ                 0.66/+14     0.69/+18     PASS     0.74/+23
qtr_end_spy      last 5 days of quarter, SPY                       0.38/+1      0.92/+5     PASS      0.24/+1
sector_mom_wk    weekly top-2 sector momentum                     0.79/+10      0.46/+6     PASS     0.78/+15
v11_core_2x      deployed core (multi-edge blend, 2x vt16)        0.75/+11      0.32/+4 MARGINAL             
dual_momentum    GEM: SPY/EFA vs T-bills, monthly                  0.68/+9      0.33/+4 MARGINAL             
vrp_svxy         short vol only in contango                       1.08/+57     -0.11/-8     DEAD             
def_gldtlt       stronger of GLD/TLT by momentum                   0.17/+1      0.56/+5 MARGINAL             
dip_etf          RSI2 dip-buy in uptrend, ETFs                     0.71/+9     -0.09/-2     DEAD             
tlt_monthend     bond month-end duration flows, TLT                0.35/+2     -0.10/-0     DEAD             
eth_trend        ETH above 200dma                                  0.00/+0      0.21/+2     DEAD             
btc_weekend      hold BTC weekends only                           -0.11/-7    -0.23/-10     DEAD             
uvxy_backwd      long vol in backwardation (crash convex)          0.09/-1    -0.62/-40     DEAD             
```

## Blends (chosen on DEV+VAL only)
- RELIABLE: 50% trend2_tsmom + 20% tqqq_vix_reg + 20% tom_upro + 10% burst_tqqq — dev+val Sharpe 1.06
- UPSIDE: 20% turbo_trend + 80% tqqq_vix_reg — dev+val CAGR 32%

### RELIABLE — holdout Sharpe 0.91, CAGR +17.7%, DD 29%
rolling 5y: n=2390, median 2.1x, worst 1.46x, P(>=10x) 0%
MC 5y: median 2.3x, P(10x) 0.0%, P(100x) 0.00%, P(-80%) 0.0%

### UPSIDE — holdout Sharpe 0.79, CAGR +29.3%, DD 61%
rolling 5y: n=2390, median 3.1x, worst 0.99x, P(>=10x) 2%
MC 5y: median 4.2x, P(10x) 18.1%, P(100x) 0.01%, P(-80%) 0.1%

