"""Offline tests for moe_core.py — synthetic data, no network.

The critical invariant: NOTHING that earns day T's return may depend on day T's data.
The original v8 violated this (same-day signal application) and its entire backtest edge
turned out to be that violation. These tests keep it from coming back.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import moe_core as C


def synth_db(n=420, seed=7):
    """Deterministic pseudo-random walks for a handful of core symbols."""
    syms = ["SPY", "QQQ", "XLK", "IWM", "GLD", "TLT", "EEM", "EFA", "DBC"]
    db = {}
    x = seed
    t0 = int(datetime.datetime(2020, 1, 6, 14, 30, tzinfo=datetime.timezone.utc).timestamp())
    for k, s in enumerate(syms):
        px = 100.0 + 10 * k
        bars = []
        for i in range(n):
            x = (1103515245 * x + 12345) % (2**31)          # LCG, reproducible
            r = ((x / 2**31) - 0.5) * 0.03 + 0.0004
            px *= (1 + r)
            bars.append({"t": t0 + i * 86400, "c": round(px, 4), "ac": round(px, 4)})
        db[s] = bars
    return db


def pipeline(db, legacy=False):
    M = C.build_market(db, {})
    D = C.expert_decisions(M)
    HELD, SER = C.expert_series(M, D, legacy=legacy)
    effS, expoS, sclS, nxt = C.router(M, SER, legacy=legacy)
    return M, D, HELD, SER, effS, expoS, sclS, nxt


def test_no_lookahead_perturbing_last_bar():
    db = synth_db()
    M1, D1, H1, S1, e1, x1, c1, _ = pipeline(db, legacy=False)
    db2 = {s: [dict(b) for b in bars] for s, bars in db.items()}
    for s in db2:                                            # shock every final close by -20%
        db2[s][-1]["c"] = round(db2[s][-1]["c"] * 0.8, 4)
        db2[s][-1]["ac"] = db2[s][-1]["c"]
    M2, D2, H2, S2, e2, x2, c2, _ = pipeline(db2, legacy=False)
    T = M1["dates"][-1]
    for k in H1:
        assert H1[k][T] == H2[k][T], f"{k}: book earning day T changed with day T's data"
    assert e1[T] == e2[T] and x1[T] == x2[T] and c1[T] == c2[T], \
        "router weights earning day T changed with day T's data"


def test_fixed_router_shape_and_weights():
    db = synth_db()
    M = C.build_market(db, {})
    D = C.expert_decisions(M)
    _, SER = C.expert_series(M, D)
    effS, expoS, sclS, (eff, expo, scl) = C.fixed_router(M, SER, {"core": 0.6, "dip": 0.4})
    T = M["dates"][-1]
    assert effS[T]["core"] == 0.6 and effS[T]["dip"] == 0.4 and effS[T].get("crash", 0.0) == 0.0
    assert expo == 1.0 and scl == 1.0 and expoS[T] == 1.0


def test_v10_weights_exclude_crash_and_sum_to_one():
    assert "crash" not in C.V10_WEIGHTS
    assert abs(sum(C.V10_WEIGHTS.values()) - 1.0) < 1e-9


def test_tom_flags_window():
    # March 2021: 23 trading days; first 3 and last 4 must be flagged
    days = []
    d = datetime.date(2021, 3, 1)
    while d.month == 3:
        if d.weekday() < 5: days.append(d)
        d += datetime.timedelta(days=1)
    f = C.tom_flags(days)
    assert f[:3] == [True, True, True] and not f[3]
    assert f[-4:] == [True] * 4 and not f[-5]


def test_tom_expert_decides_for_next_day():
    db = synth_db()
    M = C.build_market(db, {})
    D = C.expert_decisions(M)
    days = [C.uday(t) for t in M["dates"]]
    f = C.tom_flags(days)
    for i in range(len(days) - 1):          # D[t] must answer: is TOMORROW in the window?
        want = {"SPY": 1.0} if f[i + 1] else {}
        assert D["tom"][M["dates"][i]] == want


def test_v11_weights_sum_to_one():
    assert abs(sum(C.V11_WEIGHTS.values()) - 1.0) < 1e-9 and "crash" not in C.V11_WEIGHTS


def test_vol_target_multipliers_scale_down_high_vol():
    calm = [0.001] * 300
    wild = [(-1) ** i * 0.03 for i in range(300)]
    assert C.vol_target_multipliers(calm, target=0.12)[-1] > 1.0   # calm -> lever up (capped)
    assert C.vol_target_multipliers(wild, target=0.12)[-1] < 0.5   # wild -> cut hard


def test_dd_scale_multipliers_cut_in_drawdown_and_recover():
    crash = [0.001] * 50 + [-0.02] * 15 + [0.0] * 5
    m = C.dd_scale_multipliers(crash)
    assert m[50] == 1.0                    # no drawdown yet -> untouched
    assert m[-1] < 0.7                     # deep dd -> cut
    recovered = crash + [0.03] * 20
    assert C.dd_scale_multipliers(recovered)[-1] > C.dd_scale_multipliers(crash)[-1]
