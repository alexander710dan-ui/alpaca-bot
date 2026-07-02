"""Offline unit tests for guardrails.py — no network, no Alpaca account needed.

Run: python3 -m pytest -q tests/
The CI workflow runs these BEFORE the bot; if any fail, no orders are placed that day.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import guardrails as G


def ts(y, m, d, h=14):
    return int(datetime.datetime(y, m, d, h, tzinfo=datetime.timezone.utc).timestamp())


# ---------------- data quality ----------------

def test_data_fresh():
    now = ts(2026, 7, 2)
    assert G.data_fresh(ts(2026, 7, 1), now, max_age_days=6)
    assert not G.data_fresh(ts(2026, 6, 20), now, max_age_days=6)
    assert not G.data_fresh(None, now, max_age_days=6)
    assert not G.data_fresh(0, now, max_age_days=6)


def test_drop_partial_bar_drops_todays_bar():
    now = datetime.datetime(2026, 7, 2, 15, 5, tzinfo=datetime.timezone.utc)
    bars = [{"t": ts(2026, 6, 30), "c": 100.0},
            {"t": ts(2026, 7, 1), "c": 101.0},
            {"t": ts(2026, 7, 2), "c": 101.5}]      # in-progress bar
    out = G.drop_partial_bar(bars, now=now)
    assert len(out) == 2 and out[-1]["c"] == 101.0


def test_drop_partial_bar_keeps_completed_bars():
    now = datetime.datetime(2026, 7, 2, 15, 5, tzinfo=datetime.timezone.utc)
    bars = [{"t": ts(2026, 6, 30), "c": 100.0}, {"t": ts(2026, 7, 1), "c": 101.0}]
    assert G.drop_partial_bar(bars, now=now) == bars
    assert G.drop_partial_bar([], now=now) == []


# ---------------- circuit breakers ----------------

def test_daily_loss_breached():
    assert G.daily_loss_breached(equity=95_900, last_equity=100_000, max_daily_loss=0.04)
    assert not G.daily_loss_breached(equity=96_100, last_equity=100_000, max_daily_loss=0.04)
    assert not G.daily_loss_breached(equity=95_000, last_equity=0, max_daily_loss=0.04)


def test_drawdown_breached():
    hist = [100_000, 110_000, 105_000]
    breached, dd = G.drawdown_breached(hist, equity=87_000, max_drawdown=0.20)
    assert breached and abs(dd - (110_000 - 87_000) / 110_000) < 1e-9
    breached, dd = G.drawdown_breached(hist, equity=95_000, max_drawdown=0.20)
    assert not breached
    breached, _ = G.drawdown_breached([], equity=50_000, max_drawdown=0.20)
    assert not breached                    # no history -> cannot trip


def test_cap_gross():
    assert G.cap_gross(4.16, 2.0) == (2.0, True)
    assert G.cap_gross(1.01, 2.0) == (1.01, False)


# ---------------- order planning ----------------

EQ = 100_000.0


def test_short_without_price_is_skipped():
    # regression: the old code fell back to px=1.0 and would have sold ~10,000 shares
    actions, warnings = G.plan_orders({"SPY": -0.10}, EQ, positions={}, prices={"SPY": None})
    assert actions == []
    assert any("SKIPPED" in w for w in warnings)


def test_short_sized_in_whole_shares_from_real_price():
    actions, _ = G.plan_orders({"SPY": -0.10}, EQ, positions={}, prices={"SPY": 500.0})
    assert actions == [("short", "SPY", 20)]          # $10k / $500


def test_cover_when_short_target_shrinks():
    actions, _ = G.plan_orders({"SPY": -0.05}, EQ,
                               positions={"SPY": (-10_000.0, -20.0)}, prices={"SPY": 500.0})
    assert actions == [("cover", "SPY", 10)]


def test_sign_flip_closes_only():
    actions, warnings = G.plan_orders({"SPY": -0.10}, EQ,
                                      positions={"SPY": (8_000.0, 12.0)}, prices={"SPY": 650.0})
    assert actions == [("close", "SPY")]
    assert any("flips sign" in w for w in warnings)


def test_close_position_not_in_target_book():
    actions, _ = G.plan_orders({}, EQ, positions={"EEM": (16_000.0, 300.0)}, prices={})
    assert actions == [("close", "EEM")]


def test_rebalance_band_suppresses_small_trades():
    actions, _ = G.plan_orders({"XLK": 0.101}, EQ,
                               positions={"XLK": (10_000.0, 40.0)}, prices={"XLK": 250.0})
    assert actions == []                              # $100 delta < 1.5% band


def test_reduce_to_near_zero_becomes_close():
    actions, _ = G.plan_orders({"QQQ": 0.0001}, EQ,
                               positions={"QQQ": (9_000.0, 15.0)}, prices={"QQQ": 600.0})
    assert actions == [("close", "QQQ")]


def test_buy_capped_at_max_order_fraction():
    actions, warnings = G.plan_orders({"XLK": 0.90}, EQ, positions={}, prices={"XLK": 250.0})
    assert actions == [("buy", "XLK", 70_000.0)]
    assert any("capped" in w for w in warnings)


def test_risk_reducing_actions_come_first():
    actions, _ = G.plan_orders(
        {"XLK": 0.30, "GLD": 0.0, "QQQ": 0.05},
        EQ,
        positions={"GLD": (20_000.0, 90.0), "QQQ": (12_000.0, 20.0)},
        prices={"XLK": 250.0, "GLD": 220.0, "QQQ": 600.0})
    kinds = [a[0] for a in actions]
    assert kinds.index("close") < kinds.index("sell") < kinds.index("buy")


def test_max_orders_truncation():
    targets = {f"S{i:02d}": 0.02 for i in range(40)}
    actions, warnings = G.plan_orders(targets, EQ, positions={}, prices={}, max_orders=25)
    assert len(actions) == 25
    assert any("runaway" in w for w in warnings)
