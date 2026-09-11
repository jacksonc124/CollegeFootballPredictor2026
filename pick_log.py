"""
Persistent log of picks made *before* each week's games were played — the only way to
get a genuinely unbiased accuracy number. backtest.py's season backtest reuses
end-of-season SP+ ratings against past weeks, which has real look-ahead bias (see that
module's docstring); this log sidesteps the problem entirely by capturing what the model
actually said in advance, then grading it against results once they're final.

PERSISTENCE: local disk (LOG_DIR) is still the primary read/write target — every function
below reads and writes it exactly as before, and behaves identically whether or not GitHub
sync is configured. sync_from_github()/sync_to_github() are an optional layer on top: when
a github_token is supplied, they pull/push these same files to a dedicated branch (not the
branch Streamlit deploys from) in this repo, so the log survives a Streamlit Cloud redeploy
wiping local disk. Call sync_from_github() once near the start of a session (before the
first read) and sync_to_github() after any write. Both are no-ops if github_token is falsy,
so the log still works exactly as before (local-disk-only, wiped on redeploy) if GitHub
sync was never configured — see the Backup/Restore Log controls in the app for that case.
"""

import base64
import json
from pathlib import Path

import pandas as pd

LOG_DIR = Path("pick_log")
LOG_FILE = LOG_DIR / "logged_picks.jsonl"
MANUAL_RECORDS_FILE = LOG_DIR / "manual_records.jsonl"

# The data branch is dedicated to holding these two files as committed content — never the
# branch Streamlit Cloud deploys from, so a sync_to_github() write never triggers a redeploy.
GITHUB_REPO = "jacksonc124/CollegeFootballPredictor2026"
GITHUB_BRANCH = "data"
GITHUB_API_BASE = "https://api.github.com"

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

    already_logged() below is a check, and this function's append is a separate act —
    not atomic. Two callers racing within the same instant (observed in practice: two
    Streamlit sessions/reruns both auto-logging the current week within half a
    millisecond of each other) can both pass the check before either writes, producing
    duplicate entries for the same slate. An exclusive-create lock file narrows that
    race to almost nothing: 'x' mode atomically fails if another caller's lock already
    exists, so at most one racer proceeds to write. It's cleaned up in `finally` so a
    completed write doesn't block this slate from ever being logged again; a lock left
    behind by a crash mid-write is the one case that would (see load_log()'s
    deduplication for the actual safety net against any duplicate that still slips
    through — this lock is a mitigation, not a guarantee).
    """
    if already_logged(year, week, season_type, log_file):
        return False

    log_dir.mkdir(exist_ok=True)
    lock_path = log_dir / f".lock_{year}_{week}_{season_type}"
    try:
        lock_path.open("x").close()
    except FileExistsError:
        return False

    try:
        if already_logged(year, week, season_type, log_file):  # re-check inside the lock
            return False

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
    finally:
        lock_path.unlink(missing_ok=True)


def load_log(log_file: Path = LOG_FILE) -> pd.DataFrame:
    """
    Load the full pick log as a DataFrame (empty with LOG_COLUMNS if nothing logged yet).

    Deduplicates by (year, week, season_type, home_team, away_team), keeping the earliest
    logged_at. This is the actual safety net against log_picks()'s race (see its
    docstring) — even if a duplicate write slips through, every consumer of this log
    (accuracy counts, the CSV export, summarize_by_week) goes through load_log() or
    grade_logged_picks() (which calls this), so a duplicate silently collapses here
    instead of double-counting every game downstream.
    """
    entries = _read_all_entries(log_file)
    if not entries:
        return pd.DataFrame(columns=LOG_COLUMNS)
    df = pd.DataFrame(entries)
    return (
        df.sort_values("logged_at")
        .drop_duplicates(subset=["year", "week", "season_type", "home_team", "away_team"], keep="first")
        .reset_index(drop=True)
    )


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


def merge_log(df: pd.DataFrame, log_dir: Path = LOG_DIR, log_file: Path = LOG_FILE) -> None:
    """
    Append df's rows onto the existing log rather than replacing it — for reconstructing a
    slate that was lost (e.g. from an old CSV export of picks, re-graded against real
    results) without wiping whatever's been logged normally since. Safe even if df
    overlaps a slate that's already logged: load_log() dedupes by (year, week,
    season_type, home_team, away_team) keeping the earliest logged_at, so re-adding an
    already-present game doesn't double it, and a genuinely new slate lands as new rows.
    """
    log_dir.mkdir(exist_ok=True)
    with log_file.open("a") as f:
        for _, row in df.iterrows():
            f.write(json.dumps(row.to_dict()) + "\n")


def grade_logged_picks(bearer_token: str, log_file: Path = LOG_FILE) -> pd.DataFrame:
    """
    Grade every logged pick against actual final scores, for weeks where results are
    available yet. Returns the log with added "outcome" (win/loss/push/None — None means
    the game hasn't been played, or a result couldn't be fetched) and "home_points"/
    "away_points" (the final score behind that outcome, None alongside a None outcome)
    columns.
    """
    import backtest  # local import: backtest.py doesn't import this module, avoids a cycle

    log_df = load_log(log_file)
    if log_df.empty:
        return log_df

    outcomes = []
    home_points_col = []
    away_points_col = []
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
            home_points_col.append(None)
            away_points_col.append(None)
            continue
        home_points, away_points = result
        home_points_col.append(home_points)
        away_points_col.append(away_points)
        outcomes.append(backtest.grade_pick(row["pick_team"], row["home_team"], row["away_team"],
                                             row["market_spread_home"], home_points, away_points))

    log_df = log_df.copy()
    log_df["home_points"] = home_points_col
    log_df["away_points"] = away_points_col
    log_df["outcome"] = outcomes
    return log_df


def summarize_by_week(graded: pd.DataFrame) -> pd.DataFrame:
    """
    Win/loss record grouped by (year, week, season_type) — the log spans arbitrarily many
    seasons over time (it's never cleared), unlike a single backtest_season() run, so
    grouping by week number alone (like backtest.summarize_by_week) would wrongly combine
    e.g. 2025 week 3 with 2026 week 3. Postseason rows have week=None; dropna=False keeps
    them as their own group instead of pandas silently dropping them.
    """
    decided = graded[graded["outcome"].isin(["win", "loss"])]
    if decided.empty:
        return pd.DataFrame(columns=["year", "week", "season_type", "n", "wins", "losses", "win_rate"])

    summary = decided.groupby(["year", "week", "season_type"], dropna=False).agg(
        n=("outcome", "size"),
        wins=("outcome", lambda s: (s == "win").sum()),
    ).reset_index()
    summary["losses"] = summary["n"] - summary["wins"]
    summary["win_rate"] = summary["wins"] / summary["n"]
    return summary.sort_values(["year", "week"], na_position="first").reset_index(drop=True)


def add_manual_record(year: int, week: int | None, season_type: str, wins: int, losses: int,
                       log_dir: Path = LOG_DIR, manual_file: Path = MANUAL_RECORDS_FILE) -> None:
    """
    Record a remembered win/loss total for a slate with no per-game detail behind it — e.g.
    a week whose logged picks were lost to a disk reset before anyone backed them up.
    Stored in a separate file from the real per-game log (never mixed into load_log()'s
    rows), so it can never be mistaken for an actual graded pick and so Game-by-game
    results — which needs real per-game rows to show anything — doesn't try to render it.
    Lives on the same shared server-side disk as the log itself (not per-browser, unlike
    Favorite Team's URL storage), so every visitor sees the same corrected record — and
    carries the same reboot risk as the log, which is the whole reason this exists.

    Overwrites any existing manual entry for the same (year, week, season_type) — this is
    meant to be a single correction per slate, not an appendable history.
    """
    log_dir.mkdir(exist_ok=True)
    records = [
        r for r in _read_all_entries(manual_file)
        if not (r["year"] == year and r["week"] == week and r["season_type"] == season_type)
    ]
    records.append({"year": year, "week": week, "season_type": season_type, "wins": wins, "losses": losses})
    with manual_file.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def load_manual_records(manual_file: Path = MANUAL_RECORDS_FILE) -> pd.DataFrame:
    """Load manually-recorded slate totals (see add_manual_record). Empty DataFrame with
    columns [year, week, season_type, wins, losses] if none have been entered yet."""
    entries = _read_all_entries(manual_file)
    if not entries:
        return pd.DataFrame(columns=["year", "week", "season_type", "wins", "losses"])
    return pd.DataFrame(entries)


def delete_manual_record(year: int, week: int | None, season_type: str,
                          manual_file: Path = MANUAL_RECORDS_FILE) -> None:
    """Remove a manually-recorded slate (e.g. once the real log has genuinely caught up to
    it, or it was entered by mistake). A true no-op (no write at all) if the file doesn't
    exist yet or no entry matches — nothing has ever been recorded to delete."""
    if not manual_file.exists():
        return
    records = [
        r for r in _read_all_entries(manual_file)
        if not (r["year"] == year and r["week"] == week and r["season_type"] == season_type)
    ]
    with manual_file.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _github_headers(github_token: str) -> dict:
    return {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"}


def _github_get_file(path: str, github_token: str) -> tuple[str | None, str | None]:
    """(content, sha) for a file on GITHUB_BRANCH, or (None, None) if it doesn't exist there yet."""
    import requests

    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{path}"
    resp = requests.get(url, params={"ref": GITHUB_BRANCH}, headers=_github_headers(github_token), timeout=10)
    if resp.status_code == 404:
        return None, None
    resp.raise_for_status()
    data = resp.json()
    return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]


def _github_put_file(path: str, content: str, github_token: str, message: str) -> None:
    """Create or update a file on GITHUB_BRANCH with content, via a single commit."""
    import requests

    _, sha = _github_get_file(path, github_token)
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{path}"
    payload = {"message": message, "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
               "branch": GITHUB_BRANCH}
    if sha:
        payload["sha"] = sha
    resp = requests.put(url, json=payload, headers=_github_headers(github_token), timeout=10)
    resp.raise_for_status()


def sync_from_github(github_token: str, log_dir: Path = LOG_DIR, log_file: Path = LOG_FILE,
                      manual_file: Path = MANUAL_RECORDS_FILE) -> None:
    """
    Pull the log and manual records down from GITHUB_BRANCH to local disk, overwriting
    whatever's there. Meant to run once near the start of a session, before any reads, so a
    fresh post-redeploy container recovers what was there before instead of starting empty.

    A no-op if github_token is falsy (GitHub sync not configured — local disk stays the
    only copy, as before). Also a no-op per-file if that file doesn't exist on the branch
    yet (nothing has ever synced, e.g. right after the branch was created) — that's not an
    error, just nothing to pull. Failures (network, bad token, rate limit) are logged and
    swallowed rather than raised, since the app should keep working on local-only state
    rather than break because GitHub was briefly unreachable.
    """
    if not github_token:
        return
    log_dir.mkdir(exist_ok=True)
    for local_path in (log_file, manual_file):
        remote_path = f"{log_dir.name}/{local_path.name}"
        try:
            content, _ = _github_get_file(remote_path, github_token)
            if content is not None:
                local_path.write_text(content)
        except Exception as e:
            print(f"Warning: failed to sync {remote_path} from GitHub: {e}")


def sync_to_github(github_token: str, log_dir: Path = LOG_DIR, log_file: Path = LOG_FILE,
                    manual_file: Path = MANUAL_RECORDS_FILE) -> None:
    """
    Push the log and manual records up to GITHUB_BRANCH. Call after any write (log_picks,
    merge_log, restore_log, add_manual_record, delete_manual_record) so GitHub stays
    current. A no-op if github_token is falsy. Non-fatal on failure — the write already
    succeeded on local disk; it just hasn't reached GitHub yet, and the next successful
    sync_to_github() call will catch it up (each push sends the file's full current
    contents, not a diff, so a missed sync isn't lost, just delayed).
    """
    if not github_token:
        return
    for local_path in (log_file, manual_file):
        if not local_path.exists():
            continue
        remote_path = f"{log_dir.name}/{local_path.name}"
        try:
            _github_put_file(remote_path, local_path.read_text(), github_token,
                              message=f"Sync {local_path.name}")
        except Exception as e:
            print(f"Warning: failed to sync {remote_path} to GitHub: {e}")
