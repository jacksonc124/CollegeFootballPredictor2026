import pandas as pd
import pytest

from ui_helpers import build_parlay_leg_pool, format_game_date, outcome_row_css, tier_row_css


def test_format_game_date_with_known_time():
    # 2026-09-19 19:30 UTC -> 3:30 PM ET (UTC-4 during daylight saving)
    assert format_game_date("2026-09-19T19:30:00+00:00", False) == "Sep 19, 3:30 PM ET"


def test_format_game_date_tbd_omits_time():
    assert format_game_date("2026-09-19T19:30:00+00:00", True) == "Sep 19"


def test_format_game_date_empty_input():
    assert format_game_date(None, False) == ""
    assert format_game_date("", False) == ""


def test_format_game_date_invalid_iso_string():
    assert format_game_date("not-a-date", False) == ""


def test_tier_row_css_known_tiers():
    assert tier_row_css("A") == "background-color: #22c55e22"
    assert tier_row_css("B") == "background-color: #facc1522"
    assert tier_row_css("C") == "background-color: #fb923c22"


def test_tier_row_css_pass_and_unknown_get_no_tint():
    assert tier_row_css("Pass") == ""
    assert tier_row_css("Nonexistent") == ""


def test_outcome_row_css_win_and_loss():
    assert outcome_row_css("win") == "background-color: #22c55e22"
    assert outcome_row_css("loss") == "background-color: #ef444422"


def test_outcome_row_css_push_and_pending_get_no_tint():
    assert outcome_row_css("push") == ""
    assert outcome_row_css(None) == ""


def _parlay_df():
    return pd.DataFrame([
        {"home_team": "Home U", "away_team": "Away U", "tier": "A", "pick_team": "Home U",
         "cover_prob": 0.65, "edge_points": 4.0,
         "ml_pick_team": "Home U", "ml_model_prob": 0.7, "ml_edge": 0.08,
         "home_moneyline": -150.0, "away_moneyline": 130.0},
        {"home_team": "Third U", "away_team": "Fourth U", "tier": "C", "pick_team": "Third U",
         "cover_prob": 0.55, "edge_points": 1.0,
         "ml_pick_team": "", "ml_model_prob": 0.5, "ml_edge": 0.0,
         "home_moneyline": 100.0, "away_moneyline": -120.0},
    ])


def test_build_parlay_leg_pool_includes_ats_legs_within_tiers():
    pool = build_parlay_leg_pool(_parlay_df(), ats_tiers=("A", "B"), ml_edge_threshold=1.0)
    ats_legs = pool[pool["leg_type"] == "ATS"]
    assert list(ats_legs["leg_team"]) == ["Home U"]  # Tier C excluded by ats_tiers
    assert ats_legs.iloc[0]["leg_odds"] == -110


def test_build_parlay_leg_pool_includes_ml_legs_above_edge_threshold():
    pool = build_parlay_leg_pool(_parlay_df(), ats_tiers=("A", "B"), ml_edge_threshold=0.05)
    ml_legs = pool[pool["leg_type"] == "ML"]
    assert list(ml_legs["leg_team"]) == ["Home U"]  # 0.08 edge clears 0.05; Fourth U has 0.0 and blank pick
    assert ml_legs.iloc[0]["leg_odds"] == -150.0  # home team's own price


def test_build_parlay_leg_pool_excludes_ml_legs_when_threshold_too_strict():
    pool = build_parlay_leg_pool(_parlay_df(), ats_tiers=("A", "B"), ml_edge_threshold=1.0)
    assert "ML" not in set(pool["leg_type"])


def test_build_parlay_leg_pool_missing_ml_columns_still_returns_ats_legs():
    df = _parlay_df().drop(columns=["ml_pick_team", "ml_model_prob", "ml_edge"])
    pool = build_parlay_leg_pool(df, ats_tiers=("A", "B"))
    assert set(pool["leg_type"]) == {"ATS"}
