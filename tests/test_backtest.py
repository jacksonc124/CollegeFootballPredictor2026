import json
import time

import pandas as pd

from backtest import get_actual_results, grade_pick, overall_accuracy, summarize_by_tier, summarize_by_week


def test_get_actual_results_uses_fresh_cache_without_a_network_call(tmp_path):
    # A fresh cache hit returns before ever touching cfbd/the bearer token, so this needs
    # no real network access or credentials to verify.
    cache_file = tmp_path / "results_2025_regular_wk3.json"
    cache_file.write_text(json.dumps({
        "fetched_at": time.time(),
        "results": {"Home U||Away U": [27, 24]},
    }))

    result = get_actual_results("fake-token", 2025, 3, "regular", cache_dir=tmp_path)

    assert result == {("Home U", "Away U"): (27, 24)}


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


def test_overall_accuracy_counts_and_win_rate():
    graded = pd.DataFrame([
        {"outcome": "win"}, {"outcome": "win"}, {"outcome": "loss"}, {"outcome": "push"},
    ])
    result = overall_accuracy(graded)
    assert result == {"n": 3, "wins": 2, "losses": 1, "pushes": 1, "win_rate": 2 / 3}


def test_overall_accuracy_handles_no_decided_picks():
    graded = pd.DataFrame([{"outcome": "push"}, {"outcome": None}])
    result = overall_accuracy(graded)
    assert result["n"] == 0
    assert result["win_rate"] is None


def test_summarize_by_week_tracks_win_rate_per_week():
    graded = pd.DataFrame([
        {"week": 1, "outcome": "win"}, {"week": 1, "outcome": "win"}, {"week": 1, "outcome": "loss"},
        {"week": 2, "outcome": "loss"}, {"week": 2, "outcome": "loss"},
        {"week": 3, "outcome": "push"},  # excluded — no decided picks that week
    ])
    summary = summarize_by_week(graded).set_index("week")
    assert summary.loc[1, "n"] == 3
    assert round(summary.loc[1, "win_rate"], 3) == round(2 / 3, 3)
    assert summary.loc[2, "win_rate"] == 0.0
    assert 3 not in summary.index


def test_grade_total():
    from backtest import grade_total
    assert grade_total("OVER", 50.5, 30, 24) == "win"
    assert grade_total("UNDER", 50.5, 30, 24) == "loss"
    assert grade_total("OVER", 54.0, 30, 24) == "push"
    assert grade_total("NO EDGE", 50.5, 30, 24) is None
    assert grade_total(None, 50.5, 30, 24) is None
    assert grade_total("OVER", float("nan"), 30, 24) is None


def test_grade_moneyline():
    from backtest import grade_moneyline
    assert grade_moneyline("Home U", "Home U", 27, 20) == "win"
    assert grade_moneyline("Away U", "Home U", 27, 20) == "loss"
    assert grade_moneyline("Away U", "Home U", 20, 27) == "win"
    assert grade_moneyline(None, "Home U", 27, 20) is None
    assert grade_moneyline(float("nan"), "Home U", 27, 20) is None


def test_moneyline_profit():
    from backtest import moneyline_profit
    assert moneyline_profit("win", 150) == 1.5
    assert moneyline_profit("win", -200) == 0.5
    assert moneyline_profit("loss", -200) == -1.0
    assert moneyline_profit("push", 150) == 0.0
    assert moneyline_profit(None, 150) is None
    assert moneyline_profit("win", None) is None


def test_summarize_market_by_group():
    import pandas as pd
    from backtest import summarize_market
    df = pd.DataFrame({"total_outcome": ["win", "loss", "win", "push", None],
                       "total_tier": ["A", "A", "B", "B", "A"]})
    overall = summarize_market(df, "total_outcome")
    assert (overall.iloc[0]["wins"], overall.iloc[0]["losses"], overall.iloc[0]["pushes"]) == (2, 1, 1)
    by_tier = summarize_market(df, "total_outcome", "total_tier").set_index("total_tier")
    assert by_tier.loc["A", "win_rate"] == 0.5
    assert by_tier.loc["B", "win_rate"] == 1.0
    assert summarize_market(df.iloc[0:0], "total_outcome").empty
