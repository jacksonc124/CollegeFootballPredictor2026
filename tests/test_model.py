import math
from datetime import date

import pandas as pd

import model


def test_normal_cdf_symmetric_around_zero():
    assert model.normal_cdf(0.0) == 0.5


def test_normal_cdf_matches_known_values():
    assert math.isclose(model.normal_cdf(1.0), 0.8413, abs_tol=1e-4)
    assert math.isclose(model.normal_cdf(-1.0), 0.1587, abs_tol=1e-4)


def test_classify_tier_boundaries():
    assert model.classify_tier(0.60) == "A"
    assert model.classify_tier(0.55) == "B"
    assert model.classify_tier(0.52) == "C"
    assert model.classify_tier(0.51) == "Pass"
    assert model.classify_tier(0.599) == "B"


def test_pick_line_prefers_provider():
    game = {"lines": [{"provider": "DraftKings", "spread": -3.5}, {"provider": "consensus", "spread": -3.0}]}
    assert model.pick_line(game, "consensus")["spread"] == -3.0


def test_pick_line_falls_back_to_first_when_no_match():
    game = {"lines": [{"provider": "DraftKings", "spread": -3.5}]}
    assert model.pick_line(game, "consensus")["spread"] == -3.5


def test_pick_line_returns_none_when_no_lines():
    assert model.pick_line({"lines": []}, "consensus") is None
    assert model.pick_line({}, "consensus") is None


def test_score_game_home_favored_and_covering():
    # Home is 10 pts better on SP+, home field +2.5, market has home favored by 3.
    # model_spread_home = 12.5, market_spread = -3 -> edge = 9.5 (home side)
    row = model.score_game("Home U", "Away U", home_rating=15.0, away_rating=5.0,
                            market_spread=-3.0, home_field=2.5, std=13.0)
    assert row["pick_team"] == "Home U"
    assert row["model_pick"] == "HOME (Home U)"
    assert row["edge_points"] > 0
    assert row["cover_prob"] > 0.5
    assert row["tier"] in ("A", "B", "C")


def test_score_game_away_favored():
    # Away is much better than home, market still favors home slightly -> edge negative (away side).
    row = model.score_game("Home U", "Away U", home_rating=1.0, away_rating=20.0,
                            market_spread=-1.0, home_field=2.5, std=13.0)
    assert row["pick_team"] == "Away U"
    assert row["model_pick"] == "AWAY (Away U)"
    assert row["edge_points"] < 0


def test_score_game_no_edge_when_model_matches_market_exactly():
    # model_spread_home = (10-10)+2.5 = 2.5; market_spread = -2.5 -> edge = 0
    row = model.score_game("Home U", "Away U", home_rating=10.0, away_rating=10.0,
                            market_spread=-2.5, home_field=2.5, std=13.0)
    assert row["pick_team"] == ""
    assert row["model_pick"] == "NO EDGE"
    assert row["cover_prob"] == 0.5


def test_build_picks_skips_games_missing_ratings_or_spread():
    ratings = {"Home U": 10.0, "Away U": 5.0}
    games = [
        {"home_team": "Home U", "away_team": "Away U", "lines": [{"provider": "consensus", "spread": -3.0}]},
        {"home_team": "Home U", "away_team": "Unranked", "lines": [{"provider": "consensus", "spread": -3.0}]},
        {"home_team": "Home U", "away_team": "Away U", "lines": []},
    ]
    df = model.build_picks(ratings, games)
    assert len(df) == 1
    assert df.iloc[0]["home_team"] == "Home U"


def test_build_picks_zeroes_home_field_for_neutral_site_games():
    # Equal ratings and a pick'em market line isolate the effect of home_field alone.
    ratings = {"Home U": 10.0, "Away U": 10.0}
    games = [{"home_team": "Home U", "away_team": "Away U", "lines": [{"provider": "consensus", "spread": 0.0}]}]

    neutral_df = model.build_picks(ratings, games, home_field=2.5,
                                    game_info={("Home U", "Away U"): {"neutral_site": True, "notes": "Bowl"}})
    home_df = model.build_picks(ratings, games, home_field=2.5,
                                 game_info={("Home U", "Away U"): {"neutral_site": False, "notes": "CFP First Round"}})
    no_info_df = model.build_picks(ratings, games, home_field=2.5)

    # Neutral site: home_field is zeroed out -> model_spread_home = 0, matches the pick'em market -> NO EDGE.
    assert neutral_df.iloc[0]["model_spread_home"] == 0.0
    assert neutral_df.iloc[0]["model_pick"] == "NO EDGE"
    assert neutral_df.iloc[0]["neutral_site"] == True  # noqa: E712 (numpy bool from the DataFrame)

    # True home game (e.g. CFP first round): home_field applies -> model favors home over the pick'em market.
    assert home_df.iloc[0]["model_spread_home"] == 2.5
    assert home_df.iloc[0]["pick_team"] == "Home U"
    assert home_df.iloc[0]["neutral_site"] == False  # noqa: E712 (numpy bool from the DataFrame)
    assert home_df.iloc[0]["game_notes"] == "CFP First Round"

    # No game_info available: falls back to the flat home_field value, same as the true-home-game case.
    assert no_info_df.iloc[0]["model_spread_home"] == 2.5
    assert no_info_df.iloc[0]["neutral_site"] is None


def test_build_picks_threads_through_start_date_and_tbd_flag():
    ratings = {"Home U": 10.0, "Away U": 5.0}
    games = [{"home_team": "Home U", "away_team": "Away U", "lines": [{"provider": "consensus", "spread": -3.0}]}]

    with_date = model.build_picks(ratings, games, game_info={
        ("Home U", "Away U"): {"neutral_site": True, "notes": "Bowl",
                                "start_date": "2025-12-20T18:00:00Z", "start_time_tbd": False,
                                "venue": "Cotton Bowl Stadium"},
    })
    assert with_date.iloc[0]["start_date"] == "2025-12-20T18:00:00Z"
    assert with_date.iloc[0]["start_time_tbd"] == False  # noqa: E712 (numpy bool from the DataFrame)
    assert with_date.iloc[0]["venue"] == "Cotton Bowl Stadium"

    # game_info entries without start_date/start_time_tbd/venue (e.g. older cache) shouldn't error.
    legacy_info = model.build_picks(ratings, games, game_info={
        ("Home U", "Away U"): {"neutral_site": True, "notes": "Bowl"},
    })
    assert legacy_info.iloc[0]["start_date"] is None
    assert legacy_info.iloc[0]["venue"] == ""

    no_info = model.build_picks(ratings, games)
    assert no_info.iloc[0]["start_date"] is None
    assert no_info.iloc[0]["start_time_tbd"] is None
    assert no_info.iloc[0]["venue"] == ""


def test_build_picks_empty_games_returns_empty_dataframe():
    df = model.build_picks({}, [])
    assert df.empty


def test_strong_picks_filters_on_edge_cover_and_tier():
    df = pd.DataFrame([
        {"edge_points": 5.0, "cover_prob": 0.65, "tier": "A"},   # keep
        {"edge_points": 1.0, "cover_prob": 0.65, "tier": "A"},   # edge too small
        {"edge_points": 5.0, "cover_prob": 0.50, "tier": "Pass"},  # cover too low / Pass tier
        {"edge_points": -6.0, "cover_prob": 0.70, "tier": "A"},  # negative edge but big enough magnitude
    ])
    strong = model.strong_picks(df, edge_threshold=2.0, cover_prob_threshold=0.55)
    assert len(strong) == 2
    assert set(strong["edge_points"]) == {5.0, -6.0}


def test_strong_picks_handles_empty_dataframe():
    assert model.strong_picks(pd.DataFrame()).empty


# ---------- Totals (over/under) ----------

def test_predict_total_blends_own_scoring_and_opponent_allowed():
    home_scoring = {"avg_points_scored": 30, "avg_points_allowed": 20, "games_played": 5}
    away_scoring = {"avg_points_scored": 24, "avg_points_allowed": 28, "games_played": 5}
    # home_pred = (30 + 28) / 2 = 29; away_pred = (24 + 20) / 2 = 22; total = 51
    assert model.predict_total(home_scoring, away_scoring) == 51.0


def test_predict_total_none_when_a_team_has_no_games_played():
    home_scoring = {"avg_points_scored": 30, "avg_points_allowed": 20, "games_played": 0}
    away_scoring = {"avg_points_scored": 24, "avg_points_allowed": 28, "games_played": 5}
    assert model.predict_total(home_scoring, away_scoring) is None
    assert model.predict_total(None, away_scoring) is None


# ---------- Opponent-adjusted metrics ----------

def test_league_average_adjusted_metrics_computes_mean():
    adjusted_metrics = {
        "A": {"offense_epa": 0.1, "defense_epa_allowed": 0.2},
        "B": {"offense_epa": 0.3, "defense_epa_allowed": 0.4},
    }
    avg_off, avg_def = model.league_average_adjusted_metrics(adjusted_metrics)
    assert avg_off == 0.2
    assert math.isclose(avg_def, 0.3)


def test_league_average_adjusted_metrics_empty_returns_zero():
    assert model.league_average_adjusted_metrics({}) == (0.0, 0.0)


def test_adjusted_total_delta_zero_when_using_default_zero_baseline_and_all_teams_zero():
    # With the default 0.0 baseline (no league_average_adjusted_metrics call), an all-zero
    # matchup produces no adjustment. Real EPA data isn't actually zero-centered in
    # practice — see test_adjusted_total_delta_zero_when_teams_are_at_the_league_average
    # below for why callers should always pass real league averages, not rely on this default.
    home_adj = {"offense_epa": 0.0, "defense_epa_allowed": 0.0}
    away_adj = {"offense_epa": 0.0, "defense_epa_allowed": 0.0}
    assert model.adjusted_total_delta(home_adj, away_adj) == 0.0


def test_adjusted_total_delta_zero_when_teams_are_at_the_league_average():
    # Both teams sit exactly at league average (0.155, matching real 2025 data) — despite
    # nonzero raw EPA values, neither team is actually better/worse than average, so the
    # adjustment must be zero. This is exactly the bug that shipped initially: treating 0
    # as neutral inflated every game's total by ~10+ points because real EPA averages ~0.155,
    # not 0.
    home_adj = {"offense_epa": 0.155, "defense_epa_allowed": 0.155}
    away_adj = {"offense_epa": 0.155, "defense_epa_allowed": 0.155}
    delta = model.adjusted_total_delta(home_adj, away_adj, league_avg_offense=0.155, league_avg_defense_allowed=0.155)
    assert delta == 0.0


def test_adjusted_total_delta_positive_when_both_sides_favor_scoring_relative_to_league():
    # Home has a great offense relative to league average, away has a bad defense relative
    # to league average; both push the total up.
    home_adj = {"offense_epa": 0.35, "defense_epa_allowed": 0.155}
    away_adj = {"offense_epa": 0.155, "defense_epa_allowed": 0.355}
    delta = model.adjusted_total_delta(home_adj, away_adj, league_avg_offense=0.155,
                                        league_avg_defense_allowed=0.155, plays_per_game=35.0)
    # home_off above avg = 0.35-0.155=0.195; away_def above avg = 0.355-0.155=0.2
    # home_boost = (0.195+0.2)/2 = 0.1975; away_boost = (0+0)/2 = 0
    assert math.isclose(delta, 0.1975 * 35.0)


def test_adjusted_total_delta_none_when_either_team_missing():
    assert model.adjusted_total_delta(None, {"offense_epa": 0.1, "defense_epa_allowed": 0.1}) is None
    assert model.adjusted_total_delta({"offense_epa": 0.1, "defense_epa_allowed": 0.1}, None) is None


# ---------- Weather adjustment ----------

def test_weather_total_adjustment_no_effect_when_calm_and_dry():
    weather = {"game_indoors": False, "wind_speed": 5.0, "precipitation": 0, "snowfall": 0}
    assert model.weather_total_adjustment(weather) == 0.0


def test_weather_total_adjustment_reduces_for_high_wind():
    weather = {"game_indoors": False, "wind_speed": 25.0, "precipitation": 0, "snowfall": 0}
    # (25 - 15) * 0.4 = 4.0 points reduction
    assert model.weather_total_adjustment(weather) == -4.0


def test_weather_total_adjustment_zero_when_indoors_regardless_of_wind():
    weather = {"game_indoors": True, "wind_speed": 40.0, "precipitation": 5, "snowfall": 2}
    assert model.weather_total_adjustment(weather) == 0.0


def test_weather_total_adjustment_zero_when_missing_data():
    assert model.weather_total_adjustment(None) == 0.0
    assert model.weather_total_adjustment({}) == 0.0


def test_weather_total_adjustment_reduces_for_precipitation_and_snow():
    weather = {"game_indoors": False, "wind_speed": 5.0, "precipitation": 0.5, "snowfall": 1.0}
    assert model.weather_total_adjustment(weather) == -2.0 + -3.0


def test_score_total_picks_over_when_predicted_above_market():
    result = model.score_total(predicted_total=51.0, market_total=45.0)
    assert result["total_pick"] == "OVER"
    assert result["total_edge"] == 6.0
    assert result["total_cover_prob"] > 0.5


def test_score_total_picks_under_when_predicted_below_market():
    result = model.score_total(predicted_total=45.0, market_total=51.0)
    assert result["total_pick"] == "UNDER"
    assert result["total_edge"] == -6.0
    assert result["total_cover_prob"] > 0.5


def test_score_total_no_edge_when_predicted_equals_market():
    result = model.score_total(predicted_total=48.0, market_total=48.0)
    assert result["total_pick"] == "NO EDGE"
    assert result["total_cover_prob"] == 0.5


# ---------- Moneylines ----------

def test_moneyline_to_implied_prob_favorite_and_underdog():
    assert math.isclose(model.moneyline_to_implied_prob(-150), 0.6)
    assert math.isclose(model.moneyline_to_implied_prob(150), 0.4)


def test_american_to_decimal_odds_matches_known_values():
    assert math.isclose(model.american_to_decimal_odds(150), 2.5)
    assert math.isclose(model.american_to_decimal_odds(-110), 1.9091, abs_tol=1e-4)
    assert math.isclose(model.american_to_decimal_odds(-700), 1.1429, abs_tol=1e-4)


def test_american_to_decimal_odds_heavy_favorite_pays_far_less_than_minus_110():
    # A -700 favorite should pay much less per dollar than the standard -110 juice.
    assert model.american_to_decimal_odds(-700) < model.american_to_decimal_odds(-110)


def test_devig_moneylines_sums_to_one_and_preserves_favorite():
    home_p, away_p = model.devig_moneylines(-150, 130)
    assert math.isclose(home_p + away_p, 1.0, abs_tol=1e-9)
    assert home_p > away_p  # home is still the favorite after removing vig


def test_score_moneyline_returns_none_without_both_odds():
    assert model.score_moneyline("Home U", "Away U", 10.0, 5.0, None, 130) is None
    assert model.score_moneyline("Home U", "Away U", 10.0, 5.0, -150, None) is None


def test_score_moneyline_no_edge_when_model_matches_devigged_market():
    # Equal ratings/no home field -> model_home_win_prob = 0.5; symmetric odds devig to 0.5/0.5 too.
    result = model.score_moneyline("Home U", "Away U", 10.0, 10.0, -110, -110, home_field=0.0)
    assert result["ml_pick_team"] == ""
    assert math.isclose(result["ml_model_prob"], 0.5)
    assert math.isclose(result["ml_market_prob"], 0.5)
    assert result["ml_edge"] == 0.0


def test_score_moneyline_favors_home_when_model_more_confident_than_market():
    # Model strongly favors home (20 vs 10 rating), market barely favors home (-110/-110).
    result = model.score_moneyline("Home U", "Away U", 20.0, 10.0, -110, -110, home_field=2.5)
    assert result["ml_pick_team"] == "Home U"
    assert result["ml_model_prob"] > result["ml_market_prob"]
    assert result["ml_edge"] > 0


# ---------- build_picks integration: totals + moneylines ----------

def test_build_picks_adds_totals_and_moneyline_columns():
    ratings = {"Home U": 10.0, "Away U": 10.0}
    games = [{
        "home_team": "Home U", "away_team": "Away U",
        "lines": [{"provider": "consensus", "spread": 0.0, "over_under": 45.0,
                   "home_moneyline": -150, "away_moneyline": 130}],
    }]
    scoring_stats = {
        "Home U": {"avg_points_scored": 30, "avg_points_allowed": 20, "games_played": 5},
        "Away U": {"avg_points_scored": 24, "avg_points_allowed": 28, "games_played": 5},
    }

    df = model.build_picks(ratings, games, scoring_stats=scoring_stats)
    row = df.iloc[0]

    assert row["market_total"] == 45.0
    assert row["predicted_total"] == 51.0
    assert row["total_pick"] == "OVER"

    assert row["home_moneyline"] == -150
    assert row["away_moneyline"] == 130
    assert row["ml_pick_team"] in ("Home U", "Away U")


def test_build_picks_applies_opponent_and_weather_adjustments_to_total():
    ratings = {"Home U": 10.0, "Away U": 10.0}
    games = [{
        "home_team": "Home U", "away_team": "Away U",
        "lines": [{"provider": "consensus", "spread": 0.0, "over_under": 45.0}],
    }]
    scoring_stats = {
        "Home U": {"avg_points_scored": 30, "avg_points_allowed": 20, "games_played": 5},
        "Away U": {"avg_points_scored": 24, "avg_points_allowed": 28, "games_played": 5},
    }
    # Base predicted_total (no adjustments) is 51.0, per test_build_picks_adds_totals_and_moneyline_columns.
    # A third team is included purely to make the league average non-degenerate — with only
    # Home U/Away U in the pool, their pairwise deviations from a 2-team average always net
    # to exactly zero, which wouldn't exercise the adjustment at all.
    adjusted_metrics = {
        "Home U": {"offense_epa": 0.3, "defense_epa_allowed": 0.1},
        "Away U": {"offense_epa": 0.1, "defense_epa_allowed": 0.1},
        "Other U": {"offense_epa": 0.1, "defense_epa_allowed": 0.1},
    }
    game_weather = {
        ("Home U", "Away U"): {"game_indoors": False, "wind_speed": 25.0, "precipitation": 0, "snowfall": 0},
    }

    df = model.build_picks(ratings, games, scoring_stats=scoring_stats,
                            adjusted_metrics=adjusted_metrics, game_weather=game_weather)
    row = df.iloc[0]

    league_avg_off, league_avg_def = model.league_average_adjusted_metrics(adjusted_metrics)
    expected_opp_delta = model.adjusted_total_delta(adjusted_metrics["Home U"], adjusted_metrics["Away U"],
                                                      league_avg_off, league_avg_def)
    expected_weather_delta = model.weather_total_adjustment(game_weather[("Home U", "Away U")])
    assert expected_opp_delta != 0.0  # sanity check that this test actually exercises a nonzero adjustment
    assert row["opponent_adjustment"] == round(expected_opp_delta, 1)
    assert row["weather_adjustment"] == round(expected_weather_delta, 1)
    assert row["predicted_total"] == round(51.0 + expected_opp_delta + expected_weather_delta, 1)


def test_build_picks_totals_adjustment_columns_none_when_not_provided():
    ratings = {"Home U": 10.0, "Away U": 10.0}
    games = [{
        "home_team": "Home U", "away_team": "Away U",
        "lines": [{"provider": "consensus", "spread": 0.0, "over_under": 45.0}],
    }]
    scoring_stats = {
        "Home U": {"avg_points_scored": 30, "avg_points_allowed": 20, "games_played": 5},
        "Away U": {"avg_points_scored": 24, "avg_points_allowed": 28, "games_played": 5},
    }
    df = model.build_picks(ratings, games, scoring_stats=scoring_stats)
    row = df.iloc[0]
    assert row["opponent_adjustment"] is None
    assert row["weather_adjustment"] is None


def test_build_picks_skips_totals_when_scoring_stats_missing_a_team():
    ratings = {"Home U": 10.0, "Away U": 10.0}
    games = [{
        "home_team": "Home U", "away_team": "Away U",
        "lines": [{"provider": "consensus", "spread": 0.0, "over_under": 45.0}],
    }]
    scoring_stats = {"Home U": {"avg_points_scored": 30, "avg_points_allowed": 20, "games_played": 5}}

    df = model.build_picks(ratings, games, scoring_stats=scoring_stats)
    assert "total_pick" not in df.columns or pd.isna(df.iloc[0]["total_pick"])


def test_build_picks_no_moneyline_columns_when_line_lacks_them():
    ratings = {"Home U": 10.0, "Away U": 5.0}
    games = [{
        "home_team": "Home U", "away_team": "Away U",
        "lines": [{"provider": "consensus", "spread": -3.0}],
    }]
    df = model.build_picks(ratings, games)
    assert "ml_pick_team" not in df.columns


# ---------- Current-week resolution ----------

SAMPLE_2026_CALENDAR = [
    {"week": 1, "season_type": "regular", "start_date": "2026-08-29T07:00:00+00:00", "end_date": "2026-09-08T06:59:00+00:00"},
    {"week": 2, "season_type": "regular", "start_date": "2026-09-08T07:00:00+00:00", "end_date": "2026-09-14T06:59:00+00:00"},
    {"week": 15, "season_type": "regular", "start_date": "2026-11-28T07:00:00+00:00", "end_date": "2026-12-05T06:59:00+00:00"},
    {"week": 1, "season_type": "postseason", "start_date": "2026-12-19T07:00:00+00:00", "end_date": "2027-01-01T06:59:00+00:00"},
]


def test_resolve_current_week_matches_a_week_in_progress():
    # Regression test for the actual reported bug: Aug 29 is week 1's start date, but the
    # old hardcoded "after September 1" cutoff treated this as still last year's week 1.
    assert model.resolve_current_week(SAMPLE_2026_CALENDAR, 2026, date(2026, 8, 29)) == (2026, 1)
    assert model.resolve_current_week(SAMPLE_2026_CALENDAR, 2026, date(2026, 9, 10)) == (2026, 2)


def test_resolve_current_week_falls_back_to_last_year_before_season_starts():
    assert model.resolve_current_week(SAMPLE_2026_CALENDAR, 2026, date(2026, 8, 1)) == (2025, 1)


def test_resolve_current_week_caps_at_last_week_after_season_ends():
    assert model.resolve_current_week(SAMPLE_2026_CALENDAR, 2026, date(2026, 12, 25)) == (2026, 15)


def test_resolve_current_week_ignores_postseason_entries():
    # The sample calendar's postseason entry covers late Dec / early Jan — resolve_current_week
    # should still treat that as "past the regular season" (week 15), not pick up postseason.
    assert model.resolve_current_week(SAMPLE_2026_CALENDAR, 2026, date(2026, 12, 20)) == (2026, 15)


def test_resolve_current_week_empty_calendar_falls_back():
    assert model.resolve_current_week([], 2026, date(2026, 9, 1)) == (2025, 1)


# ---------- Week 0 vs Week 1 ----------

def test_labor_day_is_first_monday_of_september():
    assert model.labor_day(2026) == date(2026, 9, 7)
    assert model.labor_day(2025) == date(2025, 9, 1)


def test_is_week_zero_game_true_for_early_opener():
    # Verified live: 2026's actual season-opening games (Aug 29) are what fans call Week 0.
    assert model.is_week_zero_game("2026-08-29T16:00:00+00:00", 2026) is True


def test_is_week_zero_game_false_for_labor_day_weekend():
    # Verified live: the Labor Day weekend slate (Sep 5, 2026) is the "real" Week 1.
    assert model.is_week_zero_game("2026-09-05T16:00:00+00:00", 2026) is False


def test_is_week_zero_game_false_for_missing_date():
    assert model.is_week_zero_game(None, 2026) is False
    assert model.is_week_zero_game("", 2026) is False


# ---------- Team ATS records ----------

def test_ats_record_str_formats_win_loss():
    ats_records = {"Ohio State": {"games": 13, "ats_wins": 9, "ats_losses": 4, "ats_pushes": 0,
                                   "avg_cover_margin": 4.1}}
    assert model.ats_record_str("Ohio State", ats_records) == "9-4"


def test_ats_record_str_includes_pushes_when_present():
    ats_records = {"Ohio State": {"games": 13, "ats_wins": 8, "ats_losses": 4, "ats_pushes": 1,
                                   "avg_cover_margin": 2.0}}
    assert model.ats_record_str("Ohio State", ats_records) == "8-4-1"


def test_ats_record_str_empty_when_team_unknown():
    assert model.ats_record_str("Vanderbilt", {}) == ""


# ---------- Rankings ----------

def test_rank_badge_prefers_ap_over_coaches():
    rankings = {"AP Top 25": {"Ohio State": 2}, "Coaches Poll": {"Ohio State": 3}}
    assert model.rank_badge("Ohio State", rankings) == "#2 "


def test_rank_badge_falls_back_to_coaches_when_unranked_in_ap():
    rankings = {"AP Top 25": {}, "Coaches Poll": {"Duke": 24}}
    assert model.rank_badge("Duke", rankings) == "#24 "


def test_rank_badge_empty_when_unranked_in_both():
    rankings = {"AP Top 25": {"Ohio State": 2}, "Coaches Poll": {"Ohio State": 3}}
    assert model.rank_badge("Vanderbilt", rankings) == ""


def test_rank_badge_handles_missing_poll_keys():
    assert model.rank_badge("Ohio State", {}) == ""


# ---------- Per-category stat leaders ----------

def test_top_stat_leaders_ranks_by_requested_stat_type():
    rows = [
        {"player": "RB1", "team": "A", "position": "RB", "stat_type": "YDS", "stat": "1200"},
        {"player": "RB2", "team": "B", "position": "RB", "stat_type": "YDS", "stat": "1800"},
        {"player": "RB3", "team": "C", "position": "RB", "stat_type": "TD", "stat": "25"},  # different stat_type
    ]
    leaders = model.top_stat_leaders(rows, "YDS", top_n=10)
    assert list(leaders["player"]) == ["RB2", "RB1"]
    assert leaders.iloc[0]["value"] == 1800


def test_top_stat_leaders_respects_top_n():
    rows = [{"player": f"P{i}", "team": "A", "position": "WR", "stat_type": "YDS", "stat": str(i)}
            for i in range(5)]
    leaders = model.top_stat_leaders(rows, "YDS", top_n=2)
    assert len(leaders) == 2
    assert leaders.iloc[0]["player"] == "P4"


def test_top_stat_leaders_empty_when_stat_type_not_present():
    rows = [{"player": "P1", "team": "A", "position": "WR", "stat_type": "TD", "stat": "5"}]
    assert model.top_stat_leaders(rows, "YDS").empty


def test_top_stat_leaders_ignores_unparseable_values():
    rows = [{"player": "P1", "team": "A", "position": "WR", "stat_type": "YDS", "stat": "--"}]
    assert model.top_stat_leaders(rows, "YDS").empty


# ---------- Stat leaderboard ----------

def test_build_stat_leaderboard_combines_categories_and_scores():
    passing = [
        {"player": "QB1", "team": "A", "position": "QB", "stat_type": "YDS", "stat": "3000"},
        {"player": "QB1", "team": "A", "position": "QB", "stat_type": "TD", "stat": "30"},
        {"player": "QB1", "team": "A", "position": "QB", "stat_type": "INT", "stat": "8"},  # ignored stat_type
    ]
    rushing = [
        {"player": "QB1", "team": "A", "position": "QB", "stat_type": "YDS", "stat": "500"},
        {"player": "QB1", "team": "A", "position": "QB", "stat_type": "TD", "stat": "5"},
        {"player": "RB1", "team": "B", "position": "RB", "stat_type": "YDS", "stat": "1500"},
        {"player": "RB1", "team": "B", "position": "RB", "stat_type": "TD", "stat": "18"},
        {"player": "RB1", "team": "B", "position": "RB", "stat_type": "CAR", "stat": "250"},  # ignored stat_type
    ]
    receiving = [
        {"player": "RB1", "team": "B", "position": "RB", "stat_type": "YDS", "stat": "200"},
        {"player": "RB1", "team": "B", "position": "RB", "stat_type": "TD", "stat": "2"},
    ]

    board = model.build_stat_leaderboard(passing, rushing, receiving, top_n=10)

    qb1 = board[board["player"] == "QB1"].iloc[0]
    assert qb1["total_yards"] == 3500  # unweighted, for display
    assert qb1["total_td"] == 35
    assert qb1["score"] == 0.5 * 3000 + 500 + 6 * 35  # passing yards weighted, rushing yards aren't

    rb1 = board[board["player"] == "RB1"].iloc[0]
    assert rb1["total_yards"] == 1700
    assert rb1["total_td"] == 20
    assert rb1["score"] == 1700 + 6 * 20  # no passing yards, so weighting doesn't affect RB1

    # QB1's score is higher, so it should rank first.
    assert board.iloc[0]["player"] == "QB1"


def test_build_stat_leaderboard_weights_passing_so_non_qbs_can_outrank_qbs():
    # Under an unweighted sum, a QB's raw passing yardage makes it nearly impossible for
    # any RB/WR to rank above them, which is why the leaderboard used to be all QBs.
    passing = [
        {"player": "QB1", "team": "A", "position": "QB", "stat_type": "YDS", "stat": "4000"},
        {"player": "QB1", "team": "A", "position": "QB", "stat_type": "TD", "stat": "30"},
    ]
    rushing = [
        {"player": "RB1", "team": "B", "position": "RB", "stat_type": "YDS", "stat": "2200"},
        {"player": "RB1", "team": "B", "position": "RB", "stat_type": "TD", "stat": "28"},
    ]

    board = model.build_stat_leaderboard(passing, rushing, [], top_n=10)
    assert board.iloc[0]["player"] == "RB1"


def test_build_stat_leaderboard_respects_top_n():
    passing = [
        {"player": f"QB{i}", "team": "A", "position": "QB", "stat_type": "YDS", "stat": str(1000 + i)}
        for i in range(5)
    ]
    board = model.build_stat_leaderboard(passing, [], [], top_n=2)
    assert len(board) == 2
    assert board.iloc[0]["player"] == "QB4"  # highest yardage


def test_build_stat_leaderboard_empty_inputs_returns_empty_dataframe():
    assert model.build_stat_leaderboard([], [], []).empty


def test_build_stat_leaderboard_ignores_unparseable_stat_values():
    passing = [{"player": "QB1", "team": "A", "position": "QB", "stat_type": "YDS", "stat": "N/A"}]
    board = model.build_stat_leaderboard(passing, [], [])
    assert board.empty
