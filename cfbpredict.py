import os
import json
import math
from pathlib import Path

import cfbd
import pandas as pd
from cfbd.rest import ApiException

# ===================== CONFIG ===================== #

YEAR = 2025              # season
WEEK = 14                # week number
SEASON_TYPE = "regular"  # "regular" or "postseason" for lines
PROVIDER = "consensus"   # sportsbook/provider name from CFBD

HOME_FIELD = 2.5         # home-field advantage (points)
SPREAD_STD_DEV = 13.0    # assumed std dev of model error in points
EDGE_THRESHOLD = 2.0     # minimum edge (points) to consider
COVER_PROB_THRESHOLD = 0.55  # minimum cover probability for "strong" picks

CACHE_DIR = Path("cfb_cache")
CACHE_DIR.mkdir(exist_ok=True)

# ================================================== #


def cache_path(*parts) -> Path:
    return CACHE_DIR.joinpath(*parts)


def make_cfbd_client():
    """
    Create a CFBD API client using the BEARER_TOKEN env var.
    """
    token = os.environ.get("BEARER_TOKEN")
    if not token:
        raise RuntimeError("BEARER_TOKEN env var not set")

    configuration = cfbd.Configuration(access_token=token)
    return cfbd.ApiClient(configuration)


# ---------- SP+ ratings (with caching) ----------

def get_sp_ratings(year: int) -> dict:
    """
    Pull SP+ ratings from CFBD RatingsApi (free endpoint).
    Returns dict: { team_name: sp_rating }.
    Uses a simple JSON cache to avoid repeated API calls.
    """
    cache_file = cache_path(f"sp_{year}.json")
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    ratings: dict[str, float] = {}

    with make_cfbd_client() as api_client:
        ratings_api = cfbd.RatingsApi(api_client)

        try:
            sp_list = ratings_api.get_sp(year=year)
        except ApiException as e:
            print("Error calling RatingsApi.get_sp:", e)
            raise

    for team_sp in sp_list:
        team_name = team_sp.team
        rating_value = getattr(team_sp, "rating", None)
        if rating_value is None:
            continue
        ratings[team_name] = float(rating_value)

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(ratings, f)

    return ratings


# ---------- Betting lines (with caching) ----------

def get_weekly_lines(year: int, week: int):
    """
    Pull betting lines for a given year/week using BettingApi.
    Returns a list of plain dict games:
      {
        "home_team": str,
        "away_team": str,
        "lines": [
          {"provider": str, "spread": float | None},
          ...
        ]
      }
    """
    cache_file = cache_path(f"lines_{year}_wk{week}.json")
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    with make_cfbd_client() as api_client:
        betting_api = cfbd.BettingApi(api_client)
        try:
            games = betting_api.get_lines(
                year=year,
                week=week,
                season_type=SEASON_TYPE,
            )
        except ApiException as e:
            print("Error calling BettingApi.get_lines:", e)
            raise

    simple_games: list[dict] = []
    for g in games:
        game_dict = {
            "home_team": g.home_team,
            "away_team": g.away_team,
            "lines": []
        }
        if g.lines:
            for ln in g.lines:
                game_dict["lines"].append(
                    {
                        "provider": ln.provider,
                        "spread": ln.spread,
                    }
                )
        simple_games.append(game_dict)

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(simple_games, f)

    return simple_games


def pick_line_for_game(game: dict, provider_preference: str):
    """
    Pick a line dict from a simple game dict.
    Returns: {"provider": str, "spread": float | None} or None.
    """
    lines = game.get("lines") or []
    if not lines:
        return None

    for line in lines:
        prov = (line.get("provider") or "").lower()
        if prov == provider_preference.lower():
            return line

    return lines[0]


# ---------- Math helpers ----------

def normal_cdf(z: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def classify_tier(cover_prob: float) -> str:
    """
    Classify picks into tiers by cover probability.
    """
    if cover_prob >= 0.60:
        return "A"
    elif cover_prob >= 0.55:
        return "B"
    elif cover_prob >= 0.52:
        return "C"
    else:
        return "Pass"


# ---------- Core model ----------

def build_weekly_picks(year: int, week: int):
    """
    Main pipeline:
      - Get SP+ ratings for all teams.
      - Get betting lines for this week.
      - Compute model spread (home SP+ diff + home field)
      - Compute edge vs market and ATS cover probabilities.
      - Return (strong_edges_df, all_games_df).
    """
    ratings = get_sp_ratings(year)
    games = get_weekly_lines(year, week)

    rows = []

    for game in games:
        line = pick_line_for_game(game, PROVIDER)
        if line is None or line.get("spread") is None:
            continue

        home = game["home_team"]
        away = game["away_team"]

        if home not in ratings or away not in ratings:
            continue

        home_rating = ratings[home]
        away_rating = ratings[away]

        # SP+ rating is points vs average on a neutral field.
        # Neutral margin:
        model_spread_neutral = home_rating - away_rating

        # Add home-field advantage:
        model_spread_home = model_spread_neutral + HOME_FIELD  # m

        # CFBD spread is from home POV:
        # spread s: bet home wins if margin D > -s
        market_spread = line["spread"]  # s

        # Edge in "margin" terms: model margin - implied margin
        # implied margin = -s; so edge = m - (-s) = m + s
        edge = model_spread_home + market_spread

        # Home cover probability: P(D > -s) where D ~ N(m, σ)
        # P(D > -s) = 1 - Φ((-s - m)/σ)
        z = (-market_spread - model_spread_home) / SPREAD_STD_DEV
        home_cover_prob = 1.0 - normal_cdf(z)

        # Decide side and side-specific cover probability
        if edge > 0:
            pick = f"HOME ({home})"
            cover_prob = home_cover_prob
        elif edge < 0:
            pick = f"AWAY ({away})"
            cover_prob = 1.0 - home_cover_prob
        else:
            pick = "NO EDGE"
            cover_prob = 0.5

        tier = classify_tier(cover_prob)

        rows.append(
            {
                "home_team": home,
                "away_team": away,
                "provider": line.get("provider"),
                "sp_home_rating": round(home_rating, 2),
                "sp_away_rating": round(away_rating, 2),
                "model_spread_home": round(model_spread_home, 2),
                "market_spread_home": market_spread,
                "edge_points": round(edge, 2),
                "cover_prob": round(cover_prob, 3),
                "tier": tier,
                "model_pick": pick,
            }
        )

    df = pd.DataFrame(rows)

    # Strong edges: big edge and decent cover probability
    strong_edges = df[
        (df["edge_points"].abs() >= EDGE_THRESHOLD)
        & (df["cover_prob"] >= COVER_PROB_THRESHOLD)
        & (df["tier"] != "Pass")
    ].copy()

    strong_edges.sort_values("cover_prob", ascending=False, inplace=True)

    return strong_edges, df


# ---------- Display helpers ----------

def pretty_print_picks(df: pd.DataFrame, title: str, top_n: int | None = None):
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


# ---------- Main ----------

if __name__ == "__main__":
    print("Using BEARER_TOKEN:", os.environ.get("BEARER_TOKEN"))

    strong, all_games = build_weekly_picks(YEAR, WEEK)

    pretty_print_picks(
        all_games,
        f"ALL GAMES {YEAR} WEEK {WEEK} (model vs market)",
    )

    pretty_print_picks(
        strong,
        f"STRONG PICKS (|edge| >= {EDGE_THRESHOLD}, cover_prob >= {COVER_PROB_THRESHOLD})",
        top_n=10,
    )

    # Save CSVs for later analysis
    all_games.to_csv(f"all_games_{YEAR}_wk{WEEK}.csv", index=False)
    strong.to_csv(f"strong_picks_{YEAR}_wk{WEEK}.csv", index=False)
