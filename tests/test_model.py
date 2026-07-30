import math

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
                                "start_date": "2025-12-20T18:00:00Z", "start_time_tbd": False},
    })
    assert with_date.iloc[0]["start_date"] == "2025-12-20T18:00:00Z"
    assert with_date.iloc[0]["start_time_tbd"] == False  # noqa: E712 (numpy bool from the DataFrame)

    # game_info entries without start_date/start_time_tbd (e.g. older cache) shouldn't error.
    legacy_info = model.build_picks(ratings, games, game_info={
        ("Home U", "Away U"): {"neutral_site": True, "notes": "Bowl"},
    })
    assert legacy_info.iloc[0]["start_date"] is None

    no_info = model.build_picks(ratings, games)
    assert no_info.iloc[0]["start_date"] is None
    assert no_info.iloc[0]["start_time_tbd"] is None


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
