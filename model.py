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


def get_weekly_lines(bearer_token: str, year: int, week: int | None, season_type: str,
                      cache_dir: Path = CACHE_DIR) -> list[dict]:
    """
    Pull betting lines for a year/week/season_type. week=None fetches all games
    for that season_type (used for postseason). Returns a list of plain dicts:
      {"home_team": str, "away_team": str, "lines": [{"provider": str, "spread": float | None}, ...]}
    """
    import cfbd

    wk_str = "all" if week is None else str(week)
    cache_file = cache_path(f"lines_{year}_{season_type}_wk{wk_str}.json", cache_dir=cache_dir)
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
            "lines": [{"provider": ln.provider, "spread": ln.spread} for ln in (g.lines or [])],
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


def build_picks(ratings: dict, games: list[dict], provider: str = DEFAULT_PROVIDER,
                 home_field: float = DEFAULT_HOME_FIELD, std: float = SPREAD_STD_DEV,
                 game_info: dict | None = None) -> pd.DataFrame:
    """
    Build the full picks DataFrame from SP+ ratings and a list of game/line dicts.

    game_info, if provided (see get_game_info), is keyed by (home_team, away_team) and
    used to zero out home_field advantage for neutral-site games and apply it correctly
    for true home games (e.g. CFP first-round) — see get_game_info's docstring. Games
    missing from game_info fall back to the flat home_field value.
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
