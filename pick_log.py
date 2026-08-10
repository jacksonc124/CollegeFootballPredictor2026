"""
Persistent log of picks made *before* each week's games were played — the only way to
get a genuinely unbiased accuracy number. backtest.py's season backtest reuses
end-of-season SP+ ratings against past weeks, which has real look-ahead bias (see that
module's docstring); this log sidesteps the problem entirely by capturing what the model
actually said in advance, then grading it against results once they're final.

PERSISTENCE CAVEAT: this log lives on local disk (LOG_DIR) and is not committed to git.
On Streamlit Cloud, a redeploy pulls a fresh container and wipes local disk — use the
Download/Restore Log controls in the app to back it up if you want it to survive
redeploys.
"""

import json
from pathlib import Path

import pandas as pd

LOG_DIR = Path("pick_log")
LOG_FILE = LOG_DIR / "logged_picks.jsonl"

LOG_COLUMNS = [
    "logged_at", "year", "week", "season_type", "home_team", "away_team",
    "market_spread_home", "pick_team", "model_pick", "cover_prob", "edge_points", "tier",
]


def _read_all_entries(log_file: Path = LOG_FILE) -> list[dict]:
    if not log_file.exists():
        return []
    entries = []
    for line in log_file.read_text().splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def already_logged(year: int, week: int | None, season_type: str, log_file: Path = LOG_FILE) -> bool:
    """Whether this exact (year, week, season_type) slate has already been logged."""
    return any(
        e["year"] == year and e["week"] == week and e["season_type"] == season_type
        for e in _read_all_entries(log_file)
    )


def log_picks(df: pd.DataFrame, year: int, week: int | None, season_type: str,
              log_dir: Path = LOG_DIR, log_file: Path = LOG_FILE) -> bool:
    """
    Append this slate's picks (every row with a non-empty pick_team) to the log. Returns
    False without writing anything if this (year, week, season_type) is already logged —
    intentionally not overwritable, since the whole point is capturing what was
    predictable *before* kickoff, not whatever a later, fresher re-fetch would say.
    """
    if already_logged(year, week, season_type, log_file):
        return False

    log_dir.mkdir(exist_ok=True)
    logged_at = pd.Timestamp.now(tz="UTC").isoformat()
    picks = df[df["pick_team"] != ""]

    with log_file.open("a") as f:
        for _, row in picks.iterrows():
            entry = {
                "logged_at": logged_at, "year": year, "week": week, "season_type": season_type,
                "home_team": row["home_team"], "away_team": row["away_team"],
                "market_spread_home": row["market_spread_home"], "pick_team": row["pick_team"],
                "model_pick": row["model_pick"], "cover_prob": row["cover_prob"],
                "edge_points": row["edge_points"], "tier": row["tier"],
            }
            f.write(json.dumps(entry) + "\n")
    return True


def load_log(log_file: Path = LOG_FILE) -> pd.DataFrame:
    """Load the full pick log as a DataFrame (empty with LOG_COLUMNS if nothing logged yet)."""
    entries = _read_all_entries(log_file)
    if not entries:
        return pd.DataFrame(columns=LOG_COLUMNS)
    return pd.DataFrame(entries)


def logged_weeks(log_file: Path = LOG_FILE) -> list[tuple]:
    """Distinct (year, week, season_type) combos present in the log, sorted."""
    entries = _read_all_entries(log_file)
    return sorted({(e["year"], e["week"], e["season_type"]) for e in entries}, key=lambda t: (t[0], t[1] or 0, t[2]))


def restore_log(df: pd.DataFrame, log_dir: Path = LOG_DIR, log_file: Path = LOG_FILE) -> None:
    """
    Replace the on-disk log with df (e.g. a previously downloaded CSV backup, after a
    redeploy wiped local disk). This overwrites, it doesn't merge — if picks were logged
    locally after the backup was taken, they're lost. Low-risk in practice since restoring
    is a rare, deliberate action.
    """
    log_dir.mkdir(exist_ok=True)
    with log_file.open("w") as f:
        for _, row in df.iterrows():
            f.write(json.dumps(row.to_dict()) + "\n")


def grade_logged_picks(bearer_token: str, log_file: Path = LOG_FILE) -> pd.DataFrame:
    """
    Grade every logged pick against actual final scores, for weeks where results are
    available yet. Returns the log with an added "outcome" column (win/loss/push/None —
    None means the game hasn't been played, or a result couldn't be fetched).
    """
    import backtest  # local import: backtest.py doesn't import this module, avoids a cycle

    log_df = load_log(log_file)
    if log_df.empty:
        return log_df

    outcomes = []
    results_cache: dict[tuple, dict] = {}
    for _, row in log_df.iterrows():
        key = (row["year"], row["week"], row["season_type"])
        if key not in results_cache:
            try:
                results_cache[key] = backtest.get_actual_results(bearer_token, row["year"], row["week"], row["season_type"])
            except Exception:
                results_cache[key] = {}
        result = results_cache[key].get((row["home_team"], row["away_team"]))
        if result is None:
            outcomes.append(None)
            continue
        home_points, away_points = result
        outcomes.append(backtest.grade_pick(row["pick_team"], row["home_team"], row["away_team"],
                                             row["market_spread_home"], home_points, away_points))

    log_df = log_df.copy()
    log_df["outcome"] = outcomes
    return log_df
