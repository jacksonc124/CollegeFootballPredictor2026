"""CLI script: build weekly ATS picks from SP+ ratings vs. market spreads and print/save them."""

import os

import model

# ===================== CONFIG ===================== #

YEAR = 2025              # season
WEEK = 14                # week number
SEASON_TYPE = "regular"  # "regular" or "postseason" for lines

# ================================================== #


def pretty_print_picks(df, title: str, top_n: int | None = None):
    if df.empty:
        print(f"\n=== {title} ===")
        print("None.")
        return

    df = df.copy()
    df = df.sort_values("edge_points", key=lambda s: s.abs(), ascending=False)

    if top_n is not None:
        df = df.head(top_n)

    cols = [
        "home_team",
        "away_team",
        "model_spread_home",
        "market_spread_home",
        "edge_points",
        "cover_prob",
        "tier",
        "model_pick",
        "provider",
    ]
    cols = [c for c in cols if c in df.columns]

    print(f"\n=== {title} ===")
    print(df[cols].to_string(index=False))


if __name__ == "__main__":
    bearer_token = os.environ.get("BEARER_TOKEN")
    if not bearer_token:
        raise RuntimeError("BEARER_TOKEN env var not set")

    ratings = model.get_sp_ratings(bearer_token, YEAR)
    games = model.get_weekly_lines(bearer_token, YEAR, WEEK, SEASON_TYPE)
    game_info = model.get_game_info(bearer_token, YEAR, WEEK, SEASON_TYPE)

    all_games = model.build_picks(ratings, games, game_info=game_info)
    strong = model.strong_picks(all_games).sort_values("cover_prob", ascending=False)

    pretty_print_picks(
        all_games,
        f"ALL GAMES {YEAR} WEEK {WEEK} (model vs market)",
    )

    pretty_print_picks(
        strong,
        f"STRONG PICKS (|edge| >= {model.EDGE_THRESHOLD}, cover_prob >= {model.COVER_PROB_THRESHOLD})",
        top_n=10,
    )

    # Save CSVs for later analysis
    all_games.to_csv(f"all_games_{YEAR}_wk{WEEK}.csv", index=False)
    strong.to_csv(f"strong_picks_{YEAR}_wk{WEEK}.csv", index=False)
