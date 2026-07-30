import pandas as pd

from backtest import grade_pick, summarize_by_tier


def test_grade_pick_home_win_covers():
    # Home favored by 7 (market_spread_home=-7), wins by 10 -> covers.
    assert grade_pick("Home U", "Home U", "Away U", -7.0, home_points=31, away_points=21) == "win"


def test_grade_pick_home_loss_fails_to_cover():
    # Home favored by 7, only wins by 3 -> fails to cover.
    assert grade_pick("Home U", "Home U", "Away U", -7.0, home_points=24, away_points=21) == "loss"


def test_grade_pick_away_win_when_home_fails_to_cover():
    # Picked away, home favored by 7 but wins by only 3 -> away covered.
    assert grade_pick("Away U", "Home U", "Away U", -7.0, home_points=24, away_points=21) == "win"


def test_grade_pick_push():
    # Home favored by exactly the actual margin -> push.
    assert grade_pick("Home U", "Home U", "Away U", -7.0, home_points=28, away_points=21) == "push"


def test_grade_pick_no_edge_returns_none():
    assert grade_pick("", "Home U", "Away U", -7.0, home_points=28, away_points=21) is None


def test_summarize_by_tier_computes_win_rate_and_calibration():
    graded = pd.DataFrame([
        {"tier": "A", "cover_prob": 0.65, "outcome": "win"},
        {"tier": "A", "cover_prob": 0.62, "outcome": "loss"},
        {"tier": "B", "cover_prob": 0.57, "outcome": "win"},
        {"tier": "A", "cover_prob": 0.61, "outcome": "push"},  # excluded from win-rate calc
    ])
    summary = summarize_by_tier(graded).set_index("tier")
    assert summary.loc["A", "n"] == 2
    assert summary.loc["A", "wins"] == 1
    assert summary.loc["A", "actual_win_rate"] == 0.5
    assert summary.loc["B", "actual_win_rate"] == 1.0


def test_summarize_by_tier_handles_no_decided_picks():
    graded = pd.DataFrame([{"tier": "A", "cover_prob": 0.6, "outcome": "push"}])
    summary = summarize_by_tier(graded)
    assert summary.empty
