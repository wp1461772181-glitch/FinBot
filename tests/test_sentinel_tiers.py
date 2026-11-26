"""5a: the pure tier functions of sentinel/tiers.py (measures, tiers, once-per-direction decisions, level locks,
short moves, grouping).  No I/O."""
import pytest

from sentinel import tiers

T0 = 1_000_000.0


def m(price, prev=100.0, sigma=0.02, **kw):
    return tiers.measure(price, prev, sigma, **kw)


# --- measures ------------------------------------------------------------------------------------------------------

def test_measure_sigma_multiple_direction_and_market():
    out = tiers.measure(92.5, 100.0, 0.05, market_r=-0.004)
    assert out["r"] == pytest.approx(-0.075) and out["direction"] == "down"
    assert out["sigma_mult"] == pytest.approx(1.5) and out["market_r"] == -0.004 and out["impact_pct"] is None


def test_measure_without_sigma_uses_two_percent_unit():
    assert tiers.measure(104.0, 100.0, None)["sigma_mult"] == pytest.approx(2.0)


def test_measure_impact_on_total_assets():
    out = tiers.measure(90.0, 100.0, 0.05, shares=100, total_assets=13135)
    assert out["impact_pct"] == pytest.approx(-1000 / 13135 * 100)


# --- tiers per sensitivity -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("sensitivity, mults", [("quiet", (2.5, 5.0)), ("standard", (2.0, 4.0)), ("sensitive", (1.5, 3.0))])
def test_tier_table(sensitivity, mults):
    low, high = mults
    assert tiers.tier_of(m(100 + (low - 0.01) * 2), sensitivity) == 0
    assert tiers.tier_of(m(100 + low * 2), sensitivity) == 1
    assert tiers.tier_of(m(100 + (high - 0.01) * 2), sensitivity) == 1
    assert tiers.tier_of(m(100 - high * 2), sensitivity) == 2


def test_unknown_sensitivity_is_standard():
    assert tiers.tier_of(m(104.0), "bogus") == 1 and tiers.thresholds("") == (2.0, 4.0)


def test_holding_impact_over_two_percent_is_major_but_a_queue_symbol_has_none():
    big = tiers.measure(94.0, 100.0, 0.05, shares=100, total_assets=10000)     # 1.2 sigma, 6% of assets
    assert tiers.tier_of(big, "standard", held=True) == 2
    assert tiers.tier_of(big, "standard", held=False) == 0
    small = tiers.measure(94.0, 100.0, 0.05, shares=10, total_assets=10000)    # 0.6% of assets
    assert tiers.tier_of(small, "standard", held=True) == 0


# --- decide ---------------------------------------------------------------------------------------------------------

def test_first_push_once_per_direction():
    d = tiers.decide({}, 1, "down", -0.05, T0)
    assert (d.action, d.why, d.tier) == ("push", "first", 1)
    states = {"down": {"max_tier": 1, "extreme_r": -0.05, "reversal_said": 0}}
    assert tiers.decide(states, 1, "down", -0.06, T0 + 3600).action == "none"          # no step re-alerts


def test_tier_zero_never_pushes_alone():
    assert tiers.decide({}, 0, "up", 0.01, T0).action == "none"


def test_rise_to_major_pushes_again_once():
    states = {"down": {"max_tier": 1, "extreme_r": -0.10, "reversal_said": 0}}
    d = tiers.decide(states, 2, "down", -0.17, T0 + 3600)
    assert (d.action, d.why, d.tier) == ("push", "rise", 2)
    states = {"down": {"max_tier": 2, "extreme_r": -0.17, "reversal_said": 0}}
    assert tiers.decide(states, 2, "down", -0.18, T0 + 7200).action == "none"


def test_other_side_of_prev_close_is_its_own_first_push():
    states = {"down": {"max_tier": 1, "extreme_r": -0.05, "reversal_said": 0}}
    assert tiers.decide(states, 1, "up", 0.05, T0 + 3600).why == "first"


def test_reversal_after_giving_back_half_of_the_extreme_once_a_day():
    states = {"down": {"max_tier": 1, "extreme_r": -0.16, "reversal_said": 0}}
    assert tiers.decide(states, 0, "down", -0.09, T0).action == "none"                  # gave back 44%
    d = tiers.decide(states, 0, "down", -0.08, T0)
    assert (d.action, d.why, d.direction) == ("push", "reversal", "down")                # exactly half
    done = {"down": {"max_tier": 1, "extreme_r": -0.16, "reversal_said": 1}}
    assert tiers.decide(done, 0, "down", -0.01, T0).action == "none"


def test_reversal_needs_a_pushed_tier_and_works_for_a_rise_too():
    quiet = {"up": {"max_tier": 0, "extreme_r": 0.03, "reversal_said": 0}}
    assert tiers.decide(quiet, 0, "up", 0.0, T0).action == "none"
    states = {"up": {"max_tier": 2, "extreme_r": 0.36, "reversal_said": 0}}
    assert tiers.decide(states, 2, "up", 0.17, T0).why == "reversal"                     # still major, but half is gone


def test_min_gap_holds_minor_pushes_but_never_a_major_one():
    held = tiers.decide({}, 1, "down", -0.05, T0 + 300, last_push_ts=T0)
    assert (held.action, held.reason) == ("hold", "min_gap")
    assert tiers.decide({}, 1, "down", -0.05, T0 + 600, last_push_ts=T0).action == "push"
    states = {"down": {"max_tier": 1, "extreme_r": -0.10, "reversal_said": 0}}
    assert tiers.decide(states, 2, "down", -0.17, T0 + 60, last_push_ts=T0).action == "push"


# --- price levels ---------------------------------------------------------------------------------------------------

def level(state, kind, lvl, price, date="2026-11-03", sigma=0.04):
    return tiers.level_state(state, kind, lvl, price, sigma, date)


def test_level_first_sight_on_the_far_side_is_locked_not_a_crossing():
    fire, count, st = level(None, "plan_add", 55.0, 54.0)
    assert not fire and st["armed"] == 0
    fire, _, st = level(None, "plan_add", 55.0, 56.0)
    assert not fire and st["armed"] == 1


def test_add_level_fires_once_then_locks_until_half_a_sigma_away():
    _, _, st = level(None, "plan_add", 55.0, 56.0)
    fire, count, st = level(st, "plan_add", 55.0, 54.9)
    assert fire and count == 1 and st["armed"] == 0
    for price in (55.2, 54.0, 55.5, 56.0, 54.0):                       # chopping inside the lock: never fires
        fire, _, st = level(st, "plan_add", 55.0, price)
        assert not fire
    _, _, st = level(st, "plan_add", 55.0, 55.0 * 1.02 + 0.01)           # 0.5 * 4% = 2% above: re-armed
    assert st["armed"] == 1
    fire, count, st = level(st, "plan_add", 55.0, 54.0)
    assert fire and count == 2                                            # same date: the second crossing


def test_count_resets_on_a_new_date_and_target_fires_upwards():
    _, _, st = level(None, "plan_target", 80.0, 79.0)
    fire, count, st = level(st, "plan_target", 80.0, 80.5)
    assert fire and count == 1
    _, _, st = level(st, "plan_target", 80.0, 80.0 * 0.98 - 0.01, date="2026-11-04")
    fire, count, st = level(st, "plan_target", 80.0, 80.1, date="2026-11-04")
    assert fire and count == 1


def test_level_rearm_distance_falls_back_to_one_percent():
    _, _, st = level(None, "plan_stop", 30.0, 31.0, sigma=None)
    _, _, st = level(st, "plan_stop", 30.0, 29.0, sigma=None)
    _, _, st = level(st, "plan_stop", 30.0, 30.2, sigma=None)
    assert st["armed"] == 0
    _, _, st = level(st, "plan_stop", 30.0, 30.31, sigma=None)
    assert st["armed"] == 1


# --- short moves ----------------------------------------------------------------------------------------------------

def test_short_move_needs_half_a_daily_sigma():
    assert not tiers.short_move(0.01, 0.075, "mid")             # the 1% on a 7.5% stock
    assert tiers.short_move(0.04, 0.075, "mid")
    assert tiers.short_move(0.011, None, "mid") and not tiers.short_move(0.009, None, "mid")


def test_short_move_in_extended_hours_needs_volume():
    assert not tiers.short_move(0.04, 0.075, "pre", volume=100, avg_volume=100)
    assert not tiers.short_move(0.04, 0.075, "pre", volume=500, avg_volume=None)
    assert tiers.short_move(0.04, 0.075, "pre", volume=300, avg_volume=100)


# --- grouping -------------------------------------------------------------------------------------------------------

def cand(symbol, direction="down", tier=1, held=False, why="first", mult=2.0):
    return {"symbol": symbol, "direction": direction, "tier": tier, "held": held, "why": why, "sigma_mult": mult}


def test_group_needs_three_same_way_and_a_market_move():
    items = [cand("A"), cand("B"), cand("C")]
    members, rest = tiers.group(items, -0.02, 0.01)
    assert [c["symbol"] for c in members] == ["A", "B", "C"] and rest == []
    assert tiers.group(items[:2], -0.02, 0.01) is None
    assert tiers.group(items, -0.004, 0.01) is None                    # the market barely moved
    assert tiers.group(items, 0.02, 0.01) is None                      # moved the other way
    assert tiers.group(items, -0.012, None) is not None                # unknown sigma: 1%
    assert tiers.group(items, -0.008, None) is None


def test_group_lists_a_major_holding_first_and_leaves_other_directions_and_reversals():
    items = [cand("A"), cand("B", tier=2, held=True, mult=5), cand("C", mult=3), cand("D", direction="up"),
             cand("E", why="reversal")]
    members, rest = tiers.group(items, -0.02, 0.01)
    assert [c["symbol"] for c in members] == ["B", "C", "A"]
    assert [c["symbol"] for c in rest] == ["D", "E"]
