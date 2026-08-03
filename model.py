"""
Shared CFB SP+ vs. market-spread model: CFBD fetchers, math helpers, and pick-building.

Used by both app.py (Streamlit dashboard) and cfbpredict.py (CLI script) so the
two entry points stay in sync instead of drifting into two copies of the same logic.

`cfbd` is imported lazily inside the functions that need it, so pure functions
(normal_cdf, classify_tier, score_game, build_picks, strong_picks) can be
imported and unit-tested without the CFBD SDK installed.
"""

import json
import math
from pathlib import Path

import pandas as pd

CACHE_DIR = Path("cfb_cache")

DEFAULT_HOME_FIELD = 2.5
SPREAD_STD_DEV = 13.0
EDGE_THRESHOLD = 2.0
COVER_PROB_THRESHOLD = 0.55
DEFAULT_PROVIDER = "consensus"

# Heuristic std dev for total-points prediction error. Total points are noisier than
# margin, so this is deliberately looser than SPREAD_STD_DEV — it's not empirically
# fit, just a reasonable assumption for the normal-approximation cover-probability math.
TOTAL_STD_DEV = 17.0

# Minimum moneyline edge (model win prob - market vig-removed implied prob) to treat
# a moneyline pick as worth surfacing/using in a parlay.
ML_EDGE_THRESHOLD = 0.05


def cache_path(*parts, cache_dir: Path = CACHE_DIR) -> Path:
    cache_dir.mkdir(exist_ok=True)
    return cache_dir.joinpath(*parts)


def make_client(bearer_token: str):
    import cfbd

    if not bearer_token:
        raise RuntimeError("BEARER_TOKEN not set")
    return cfbd.ApiClient(cfbd.Configuration(access_token=bearer_token))


# ---------- CFBD fetchers (with JSON caching) ----------

def get_sp_ratings(bearer_token: str, year: int, cache_dir: Path = CACHE_DIR) -> dict:
    """Pull SP+ ratings from CFBD RatingsApi. Returns {team_name: sp_rating}."""
    import cfbd

    cache_file = cache_path(f"sp_{year}.json", cache_dir=cache_dir)
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    ratings: dict[str, float] = {}
    with make_client(bearer_token) as client:
        for t in cfbd.RatingsApi(client).get_sp(year=year):
            v = getattr(t, "rating", None)
            if v is not None:
                ratings[t.team] = float(v)

    cache_file.write_text(json.dumps(ratings))
    return ratings


# Bump whenever get_weekly_lines's per-line dict schema changes, same reasoning as
# GAME_INFO_CACHE_VERSION below — a stale cache from before a field existed would
# otherwise silently return it as missing instead of refetching.
LINES_CACHE_VERSION = 2


def get_weekly_lines(bearer_token: str, year: int, week: int | None, season_type: str,
                      cache_dir: Path = CACHE_DIR) -> list[dict]:
    """
    Pull betting lines for a year/week/season_type. week=None fetches all games
    for that season_type (used for postseason). Returns a list of plain dicts:
      {"home_team": str, "away_team": str, "lines": [{"provider": str, "spread": float | None,
       "over_under": float | None, "home_moneyline": float | None, "away_moneyline": float | None}, ...]}
    """
    import cfbd

    wk_str = "all" if week is None else str(week)
    cache_file = cache_path(f"lines_v{LINES_CACHE_VERSION}_{year}_{season_type}_wk{wk_str}.json",
                             cache_dir=cache_dir)
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    with make_client(bearer_token) as client:
        kwargs = dict(year=year, season_type=season_type)
        if week is not None:
            kwargs["week"] = week
        games = cfbd.BettingApi(client).get_lines(**kwargs)

    result = [
        {
            "home_team": g.home_team,
            "away_team": g.away_team,
            "lines": [
                {
                    "provider": ln.provider,
                    "spread": ln.spread,
                    "over_under": ln.over_under,
                    "home_moneyline": ln.home_moneyline,
                    "away_moneyline": ln.away_moneyline,
                }
                for ln in (g.lines or [])
            ],
        }
        for g in games
    ]
    cache_file.write_text(json.dumps(result))
    return result


# Bump this whenever get_game_info's return schema changes. It's baked into the cache
# filename so a stale on-disk cache from an older schema is never mistaken for the new
# one — it just gets ignored and refetched instead of silently returning missing fields.
GAME_INFO_CACHE_VERSION = 2


def get_game_info(bearer_token: str, year: int, week: int | None, season_type: str,
                   cache_dir: Path = CACHE_DIR) -> dict:
    """
    Pull scheduling metadata (neutral site, round/bowl name, kickoff date, venue) for
    FBS games from the Games API.

    Betting lines alone don't say whether a game is at a neutral site or when/where it's
    played. This matters most in the postseason: CFBD lumps every postseason FBS game —
    bowls *and* all four rounds of the CFP — under a single week=1, but they aren't all
    neutral. Bowl games and CFP quarterfinals/semifinals/the championship are
    neutral-site; CFP first-round games are played at the higher seed's campus stadium
    (neutral_site=False), so the home team should still get home-field advantage there.
    Returns {(home_team, away_team): {"neutral_site": bool, "notes": str,
    "start_date": str | None (ISO 8601, UTC), "start_time_tbd": bool, "venue": str}}.
    """
    import cfbd

    wk_str = "all" if week is None else str(week)
    cache_file = cache_path(f"games_v{GAME_INFO_CACHE_VERSION}_{year}_{season_type}_wk{wk_str}.json",
                             cache_dir=cache_dir)
    if cache_file.exists():
        raw = json.loads(cache_file.read_text())
        return {tuple(k.split("||", 1)): v for k, v in raw.items()}

    with make_client(bearer_token) as client:
        kwargs = dict(year=year, season_type=season_type, classification="fbs")
        if week is not None:
            kwargs["week"] = week
        games = cfbd.GamesApi(client).get_games(**kwargs)

    info = {
        (g.home_team, g.away_team): {
            "neutral_site": bool(g.neutral_site),
            "notes": g.notes or "",
            "start_date": g.start_date.isoformat() if g.start_date else None,
            "start_time_tbd": bool(g.start_time_tbd),
            "venue": g.venue or "",
        }
        for g in games
    }

    serializable = {f"{h}||{a}": v for (h, a), v in info.items()}
    cache_file.write_text(json.dumps(serializable))
    return info


def get_team_scoring_stats(bearer_token: str, year: int, season_type: str = "regular",
                            cache_dir: Path = CACHE_DIR) -> dict:
    """
    Season-to-date scoring averages per FBS team, computed from every completed game
    of the season in one call. Returns
    {team: {"avg_points_scored": float, "avg_points_allowed": float, "games_played": int}}.

    This is a season-long snapshot (like SP+), not point-in-time — see the
    look-ahead-bias caveat in backtest.py's module docstring if using this for backtesting.
    Feeds the simple totals (over/under) model — see predict_total().
    """
    import cfbd

    cache_file = cache_path(f"scoring_{year}_{season_type}.json", cache_dir=cache_dir)
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    with make_client(bearer_token) as client:
        games = cfbd.GamesApi(client).get_games(year=year, season_type=season_type, classification="fbs")

    totals: dict[str, dict] = {}

    def add(team, scored, allowed):
        t = totals.setdefault(team, {"scored": 0, "allowed": 0, "games_played": 0})
        t["scored"] += scored
        t["allowed"] += allowed
        t["games_played"] += 1

    for g in games:
        if g.home_points is None or g.away_points is None:
            continue
        add(g.home_team, g.home_points, g.away_points)
        add(g.away_team, g.away_points, g.home_points)

    stats = {
        team: {
            "avg_points_scored": t["scored"] / t["games_played"],
            "avg_points_allowed": t["allowed"] / t["games_played"],
            "games_played": t["games_played"],
        }
        for team, t in totals.items()
    }

    cache_file.write_text(json.dumps(stats))
    return stats


def get_team_logos(bearer_token: str, year: int, cache_dir: Path = CACHE_DIR) -> dict:
    """Pull team logo URLs. Returns {school_name: logo_url}. Non-fatal on failure."""
    import cfbd

    cache_file = cache_path(f"logos_{year}.json", cache_dir=cache_dir)
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    logos: dict[str, str] = {}
    try:
        with make_client(bearer_token) as client:
            for t in cfbd.TeamsApi(client).get_fbs_teams(year=year):
                if t.logos:
                    logos[t.school] = t.logos[0]
    except Exception as e:
        print(f"Warning: failed to fetch team logos: {e}")

    cache_file.write_text(json.dumps(logos))
    return logos


def get_player_season_stats(bearer_token: str, year: int, category: str, season_type: str = "regular",
                             cache_dir: Path = CACHE_DIR) -> list[dict]:
    """
    Pull aggregated player season stats for one category (e.g. "passing", "rushing",
    "receiving"). CFBD returns "long" format — one row per player per stat type — so this
    is a thin passthrough; build_stat_leaderboard() does the aggregation. stat is kept as
    the raw string CFBD returns; parse it at use time.
    """
    import cfbd

    cache_file = cache_path(f"player_stats_{year}_{season_type}_{category}.json", cache_dir=cache_dir)
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    with make_client(bearer_token) as client:
        rows = cfbd.StatsApi(client).get_player_season_stats(year=year, season_type=season_type, category=category)

    result = [
        {"player": r.player, "team": r.team, "position": r.position, "stat_type": r.stat_type, "stat": r.stat}
        for r in rows
    ]
    cache_file.write_text(json.dumps(result))
    return result


# ---------- Math helpers (pure) ----------

def normal_cdf(z: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def classify_tier(cover_prob: float) -> str:
    if cover_prob >= 0.60:
        return "A"
    if cover_prob >= 0.55:
        return "B"
    if cover_prob >= 0.52:
        return "C"
    return "Pass"


def pick_line(game: dict, provider_preference: str) -> dict | None:
    """Pick the preferred provider's line for a game, falling back to the first available."""
    lines = game.get("lines") or []
    if not lines:
        return None
    for line in lines:
        if (line.get("provider") or "").lower() == provider_preference.lower():
            return line
    return lines[0]


# ---------- Core model (pure — no I/O) ----------

def score_game(home: str, away: str, home_rating: float, away_rating: float, market_spread: float,
               home_field: float = DEFAULT_HOME_FIELD, std: float = SPREAD_STD_DEV) -> dict:
    """
    Compute model spread, edge, and ATS cover probability for one game.

    market_spread follows CFBD convention (home POV): negative means home favored.
    edge = model_spread_home + market_spread (positive edge favors home).
    """
    model_spread_home = (home_rating - away_rating) + home_field
    edge = model_spread_home + market_spread
    z = (-market_spread - model_spread_home) / std
    home_cover_prob = 1.0 - normal_cdf(z)

    if edge > 0:
        pick_team, cover_prob, model_pick = home, home_cover_prob, f"HOME ({home})"
    elif edge < 0:
        pick_team, cover_prob, model_pick = away, 1.0 - home_cover_prob, f"AWAY ({away})"
    else:
        pick_team, cover_prob, model_pick = "", 0.5, "NO EDGE"

    return {
        "home_team": home,
        "away_team": away,
        "sp_home_rating": round(home_rating, 2),
        "sp_away_rating": round(away_rating, 2),
        "model_spread_home": round(model_spread_home, 2),
        "market_spread_home": market_spread,
        "edge_points": round(edge, 2),
        "cover_prob": round(cover_prob, 3),
        "tier": classify_tier(cover_prob),
        "pick_team": pick_team,
        "model_pick": model_pick,
    }


def predict_total(home_scoring: dict | None, away_scoring: dict | None) -> float | None:
    """
    Simple blended total-points estimate: average of each team's own scoring tendency
    and their opponent's tendency to allow points. Returns None if either team has no
    games_played yet (e.g. week 1, or a team missing from scoring_stats).
    """
    if not home_scoring or not away_scoring:
        return None
    if not home_scoring.get("games_played") or not away_scoring.get("games_played"):
        return None
    home_pred = (home_scoring["avg_points_scored"] + away_scoring["avg_points_allowed"]) / 2
    away_pred = (away_scoring["avg_points_scored"] + home_scoring["avg_points_allowed"]) / 2
    return home_pred + away_pred


def score_total(predicted_total: float, market_total: float, std: float = TOTAL_STD_DEV) -> dict:
    """Compute edge and cover probability for the over/under, mirroring score_game's spread logic."""
    edge = predicted_total - market_total
    z = (market_total - predicted_total) / std
    over_prob = 1.0 - normal_cdf(z)

    if edge > 0:
        pick, cover_prob = "OVER", over_prob
    elif edge < 0:
        pick, cover_prob = "UNDER", 1.0 - over_prob
    else:
        pick, cover_prob = "NO EDGE", 0.5

    return {
        "predicted_total": round(predicted_total, 1),
        "market_total": market_total,
        "total_edge": round(edge, 1),
        "total_cover_prob": round(cover_prob, 3),
        "total_tier": classify_tier(cover_prob),
        "total_pick": pick,
    }


def moneyline_to_implied_prob(odds: float) -> float:
    """Convert American odds to raw (vig-included) implied win probability."""
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return -odds / (-odds + 100.0)


def american_to_decimal_odds(odds: float) -> float:
    """
    Convert American odds to a decimal payout multiplier (stake included), e.g.
    +150 -> 2.5x, -110 -> 1.909x, -700 -> 1.143x. Used to price parlay legs correctly:
    a heavy-favorite moneyline leg pays far less than the standard -110 ATS/O-U juice,
    so a parlay payout can't just assume every leg is -110.
    """
    if odds > 0:
        return (odds / 100.0) + 1.0
    return (100.0 / -odds) + 1.0


def devig_moneylines(home_odds: float, away_odds: float) -> tuple[float, float]:
    """Remove the vig by normalizing both sides' implied probabilities to sum to 1."""
    home_p = moneyline_to_implied_prob(home_odds)
    away_p = moneyline_to_implied_prob(away_odds)
    total = home_p + away_p
    return home_p / total, away_p / total


def score_moneyline(home: str, away: str, home_rating: float, away_rating: float,
                     home_ml: float | None, away_ml: float | None,
                     home_field: float = DEFAULT_HOME_FIELD, std: float = SPREAD_STD_DEV) -> dict | None:
    """
    Compute the model's straight-up (not ATS) win probability vs. the market's
    vig-removed moneyline-implied probability, and the edge between them.

    Because devig'd probabilities sum to 1 on both sides, the away-side edge is always
    exactly the negative of the home-side edge, so a single edge value determines the pick.
    Returns None if either moneyline is missing (some providers only post spreads).
    """
    if home_ml is None or away_ml is None:
        return None

    model_spread_home = (home_rating - away_rating) + home_field
    model_home_win_prob = 1.0 - normal_cdf(-model_spread_home / std)
    market_home_prob, market_away_prob = devig_moneylines(home_ml, away_ml)
    edge = model_home_win_prob - market_home_prob

    if edge > 0:
        team, model_prob, market_prob = home, model_home_win_prob, market_home_prob
    elif edge < 0:
        team, model_prob, market_prob = away, 1.0 - model_home_win_prob, market_away_prob
    else:
        team, model_prob, market_prob = "", model_home_win_prob, market_home_prob

    return {
        "ml_pick_team": team,
        "ml_model_prob": round(model_prob, 3),
        "ml_market_prob": round(market_prob, 3),
        "ml_edge": round(abs(edge), 3),
        "home_moneyline": home_ml,
        "away_moneyline": away_ml,
    }


def build_picks(ratings: dict, games: list[dict], provider: str = DEFAULT_PROVIDER,
                 home_field: float = DEFAULT_HOME_FIELD, std: float = SPREAD_STD_DEV,
                 game_info: dict | None = None, scoring_stats: dict | None = None) -> pd.DataFrame:
    """
    Build the full picks DataFrame from SP+ ratings and a list of game/line dicts.

    game_info, if provided (see get_game_info), is keyed by (home_team, away_team) and
    used to zero out home_field advantage for neutral-site games and apply it correctly
    for true home games (e.g. CFP first-round) — see get_game_info's docstring. Games
    missing from game_info fall back to the flat home_field value.

    scoring_stats, if provided (see get_team_scoring_stats), adds total-points (over/under)
    columns when the line has a market total and both teams have scoring data. Moneyline
    columns are added whenever the line includes moneylines, independent of scoring_stats.
    """
    rows = []
    for game in games:
        line = pick_line(game, provider)
        if line is None or line.get("spread") is None:
            continue
        home, away = game["home_team"], game["away_team"]
        if home not in ratings or away not in ratings:
            continue
        info = (game_info or {}).get((home, away))
        game_home_field = 0.0 if info and info["neutral_site"] else home_field
        row = score_game(home, away, ratings[home], ratings[away], float(line["spread"]), game_home_field, std)
        row["provider"] = line.get("provider")
        row["neutral_site"] = bool(info["neutral_site"]) if info else None
        row["game_notes"] = info["notes"] if info else ""
        row["start_date"] = info.get("start_date") if info else None
        row["start_time_tbd"] = bool(info.get("start_time_tbd")) if info else None
        row["venue"] = info.get("venue", "") if info else ""

        market_total = line.get("over_under")
        if market_total is not None and scoring_stats is not None:
            predicted_total = predict_total(scoring_stats.get(home), scoring_stats.get(away))
            if predicted_total is not None:
                row.update(score_total(predicted_total, float(market_total)))

        ml_result = score_moneyline(home, away, ratings[home], ratings[away],
                                     line.get("home_moneyline"), line.get("away_moneyline"),
                                     game_home_field, std)
        if ml_result:
            row.update(ml_result)

        rows.append(row)
    return pd.DataFrame(rows)


def strong_picks(df: pd.DataFrame, edge_threshold: float = EDGE_THRESHOLD,
                  cover_prob_threshold: float = COVER_PROB_THRESHOLD) -> pd.DataFrame:
    """Filter to picks with a meaningful edge, solid cover probability, and non-Pass tier."""
    if df.empty:
        return df
    return df[
        (df["edge_points"].abs() >= edge_threshold)
        & (df["cover_prob"] >= cover_prob_threshold)
        & (df["tier"] != "Pass")
    ]


def build_stat_leaderboard(passing: list[dict], rushing: list[dict], receiving: list[dict],
                            top_n: int = 10) -> pd.DataFrame:
    """
    Simple stat-based offensive leaderboard — NOT real Heisman odds. CFBD has no
    awards-odds market data (no book prices a Heisman futures line through this API),
    so this is a composite of real season stats instead: total yards + 6 points per TD,
    summed across passing/rushing/receiving. That's a common informal "total production"
    heuristic, not a calibrated prediction — see app.py's caption for the same caveat
    surfaced to the user.

    Each input is a list of {"player", "team", "position", "stat_type", "stat"} dicts as
    returned by get_player_season_stats (only "YDS" and "TD" stat_types are used; others,
    e.g. completions/attempts/long, are ignored). Returns a DataFrame sorted by score
    descending, truncated to top_n, with columns: player, team, position, pass_yds,
    pass_td, rush_yds, rush_td, rec_yds, rec_td, total_yards, total_td, score.
    """
    totals: dict[str, dict] = {}

    def ensure(player, team, position):
        return totals.setdefault(player, {
            "player": player, "team": team, "position": position,
            "pass_yds": 0.0, "pass_td": 0.0, "rush_yds": 0.0, "rush_td": 0.0,
            "rec_yds": 0.0, "rec_td": 0.0,
        })

    def accumulate(rows, yds_key, td_key):
        for r in rows:
            if r["stat_type"] not in ("YDS", "TD"):
                continue
            try:
                value = float(r["stat"])
            except (TypeError, ValueError):
                continue
            t = ensure(r["player"], r["team"], r["position"])
            t[yds_key if r["stat_type"] == "YDS" else td_key] += value

    accumulate(passing, "pass_yds", "pass_td")
    accumulate(rushing, "rush_yds", "rush_td")
    accumulate(receiving, "rec_yds", "rec_td")

    if not totals:
        return pd.DataFrame()

    rows = []
    for t in totals.values():
        total_yards = t["pass_yds"] + t["rush_yds"] + t["rec_yds"]
        total_td = t["pass_td"] + t["rush_td"] + t["rec_td"]
        rows.append({**t, "total_yards": total_yards, "total_td": total_td,
                     "score": total_yards + 6 * total_td})

    return pd.DataFrame(rows).sort_values("score", ascending=False).head(top_n).reset_index(drop=True)
