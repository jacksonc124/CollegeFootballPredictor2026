"""
Backtest the SP+ vs. market model against actual final scores for a past week.

Fetches completed game results from CFBD, grades each model pick against the
spread (win/loss/push), and reports accuracy plus calibration (does the
model's predicted cover probability match its actual win rate?) by tier.

Usage:
    BEARER_TOKEN=... python backtest.py [year] [week] [season_type]
"""

import json
import os
import sys

import pandas as pd

import model


def get_actual_results(bearer_token: str, year: int, week: int, season_type: str = "regular",
                        cache_dir=model.CACHE_DIR) -> dict:
    """Return {(home_team, away_team): (home_points, away_points)} for completed games."""
    import cfbd

    cache_file = model.cache_path(f"results_{year}_{season_type}_wk{week}.json", cache_dir=cache_dir)
    if cache_file.exists():
        raw = json.loads(cache_file.read_text())
        return {tuple(k.split("||")): tuple(v) for k, v in raw.items()}

    with model.make_client(bearer_token) as client:
        games = cfbd.GamesApi(client).get_games(year=year, week=week, season_type=season_type)

    results = {}
    for g in games:
        if g.home_points is None or g.away_points is None:
            continue
        results[(g.home_team, g.away_team)] = (g.home_points, g.away_points)

    serializable = {f"{h}||{a}": [hp, ap] for (h, a), (hp, ap) in results.items()}
    cache_file.write_text(json.dumps(serializable))
    return results


def grade_pick(pick_team: str, home_team: str, away_team: str, market_spread_home: float,
               home_points: int, away_points: int) -> str | None:
    """
    Determine whether a model's ATS pick won, lost, or pushed against the final score.

    market_spread_home follows CFBD convention: negative means home favored.
    A pick_team of "" means the model found no edge (NO EDGE) and isn't graded.
    """
    if not pick_team:
        return None

    actual_margin = home_points - away_points
    cover_margin = actual_margin + market_spread_home  # >0: home covered, <0: away covered, ==0: push

    if cover_margin == 0:
        return "push"

    home_covered = cover_margin > 0
    if pick_team == home_team:
        return "win" if home_covered else "loss"
    return "win" if not home_covered else "loss"


def backtest_week(bearer_token: str, year: int, week: int, season_type: str = "regular",
                   home_field: float = model.DEFAULT_HOME_FIELD) -> pd.DataFrame:
    """Build picks for a past week and grade each one against the actual final score."""
    ratings = model.get_sp_ratings(bearer_token, year)
    games = model.get_weekly_lines(bearer_token, year, week, season_type)
    game_info = model.get_game_info(bearer_token, year, week, season_type)
    picks = model.build_picks(ratings, games, home_field=home_field, game_info=game_info)
    results = get_actual_results(bearer_token, year, week, season_type)

    outcomes = []
    for _, row in picks.iterrows():
        result = results.get((row["home_team"], row["away_team"]))
        if result is None:
            outcomes.append(None)
            continue
        home_points, away_points = result
        outcomes.append(grade_pick(row["pick_team"], row["home_team"], row["away_team"],
                                    row["market_spread_home"], home_points, away_points))

    picks = picks.copy()
    picks["outcome"] = outcomes
    return picks


def summarize_by_tier(graded: pd.DataFrame) -> pd.DataFrame:
    """Win rate and calibration (predicted cover prob vs. actual win rate) by tier."""
    decided = graded[graded["outcome"].isin(["win", "loss"])]
    if decided.empty:
        return pd.DataFrame(columns=["tier", "n", "wins", "avg_predicted_cover_prob", "actual_win_rate"])

    summary = decided.groupby("tier").agg(
        n=("outcome", "size"),
        wins=("outcome", lambda s: (s == "win").sum()),
        avg_predicted_cover_prob=("cover_prob", "mean"),
    )
    summary["actual_win_rate"] = summary["wins"] / summary["n"]
    return summary.reset_index()


if __name__ == "__main__":
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    week = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    season_type = sys.argv[3] if len(sys.argv) > 3 else "regular"

    bearer_token = os.environ.get("BEARER_TOKEN")
    if not bearer_token:
        raise RuntimeError("BEARER_TOKEN env var not set")

    graded = backtest_week(bearer_token, year, week, season_type)
    display_cols = ["home_team", "away_team", "model_pick", "market_spread_home", "cover_prob", "tier", "outcome"]

    print(f"\n=== BACKTEST {year} WEEK {week} ({season_type}) ===")
    print(graded[display_cols].to_string(index=False))

    print("\n=== Calibration by tier ===")
    print(summarize_by_tier(graded).to_string(index=False))
