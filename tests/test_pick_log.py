import json

import pandas as pd
import pytest

import pick_log


@pytest.fixture
def log_paths(tmp_path):
    log_dir = tmp_path / "pick_log"
    log_file = log_dir / "logged_picks.jsonl"
    return log_dir, log_file


def make_picks_df():
    return pd.DataFrame([
        {"home_team": "Home U", "away_team": "Away U", "market_spread_home": -3.0,
         "pick_team": "Home U", "model_pick": "HOME (Home U)", "cover_prob": 0.65,
         "edge_points": 4.0, "tier": "A"},
        {"home_team": "Third U", "away_team": "Fourth U", "market_spread_home": 0.0,
         "pick_team": "", "model_pick": "NO EDGE", "cover_prob": 0.5,
         "edge_points": 0.0, "tier": "Pass"},
    ])


def test_log_picks_writes_only_rows_with_a_pick(log_paths):
    log_dir, log_file = log_paths
    df = make_picks_df()

    written = pick_log.log_picks(df, 2025, 3, "regular", log_dir=log_dir, log_file=log_file)

    assert written is True
    entries = pick_log._read_all_entries(log_file)
    assert len(entries) == 1
    assert entries[0]["pick_team"] == "Home U"
    assert entries[0]["year"] == 2025
    assert entries[0]["week"] == 3
    assert entries[0]["season_type"] == "regular"


def test_log_picks_is_not_overwritable_for_the_same_slate(log_paths):
    log_dir, log_file = log_paths
    df = make_picks_df()

    first = pick_log.log_picks(df, 2025, 3, "regular", log_dir=log_dir, log_file=log_file)
    second = pick_log.log_picks(df, 2025, 3, "regular", log_dir=log_dir, log_file=log_file)

    assert first is True
    assert second is False
    assert len(pick_log._read_all_entries(log_file)) == 1  # not duplicated


def test_already_logged_distinguishes_different_slates(log_paths):
    log_dir, log_file = log_paths
    df = make_picks_df()
    pick_log.log_picks(df, 2025, 3, "regular", log_dir=log_dir, log_file=log_file)

    assert pick_log.already_logged(2025, 3, "regular", log_file) is True
    assert pick_log.already_logged(2025, 4, "regular", log_file) is False
    assert pick_log.already_logged(2024, 3, "regular", log_file) is False
    assert pick_log.already_logged(2025, None, "postseason", log_file) is False


def test_already_logged_handles_none_week_for_postseason(log_paths):
    log_dir, log_file = log_paths
    df = make_picks_df()
    pick_log.log_picks(df, 2025, None, "postseason", log_dir=log_dir, log_file=log_file)

    assert pick_log.already_logged(2025, None, "postseason", log_file) is True


def test_load_log_empty_returns_dataframe_with_expected_columns(log_paths):
    _, log_file = log_paths
    df = pick_log.load_log(log_file)
    assert df.empty
    assert list(df.columns) == pick_log.LOG_COLUMNS


def test_load_log_returns_logged_entries(log_paths):
    log_dir, log_file = log_paths
    pick_log.log_picks(make_picks_df(), 2025, 3, "regular", log_dir=log_dir, log_file=log_file)

    df = pick_log.load_log(log_file)
    assert len(df) == 1
    assert df.iloc[0]["pick_team"] == "Home U"


def test_load_log_deduplicates_a_slate_logged_twice(log_paths):
    # Simulates the race log_picks() guards against: the same slate written twice
    # (e.g. two Streamlit sessions both auto-logging within the same instant), landing
    # in the file as two batches with different logged_at timestamps.
    log_dir, log_file = log_paths
    log_dir.mkdir()
    entry_early = {"logged_at": "2026-01-01T00:00:00+00:00", "year": 2026, "week": 1, "season_type": "regular",
                   "home_team": "Home U", "away_team": "Away U", "market_spread_home": -3.0,
                   "pick_team": "Home U", "model_pick": "HOME (Home U)", "cover_prob": 0.65,
                   "edge_points": 4.0, "tier": "A"}
    entry_late = {**entry_early, "logged_at": "2026-01-01T00:00:00.000500+00:00"}  # same slate+game, later
    with log_file.open("w") as f:
        f.write(json.dumps(entry_early) + "\n")
        f.write(json.dumps(entry_late) + "\n")

    df = pick_log.load_log(log_file)
    assert len(df) == 1  # the duplicate collapses
    assert df.iloc[0]["logged_at"] == "2026-01-01T00:00:00+00:00"  # earliest one wins


def test_load_log_keeps_distinct_games_within_the_same_slate(log_paths):
    log_dir, log_file = log_paths
    pick_log.log_picks(make_picks_df(), 2025, 3, "regular", log_dir=log_dir, log_file=log_file)
    df = pick_log.load_log(log_file)
    assert len(df) == 1  # make_picks_df() has one real pick (the other is NO EDGE, not logged)


def test_log_picks_blocked_by_a_stale_lock_file(log_paths):
    # Simulates losing the race: another caller's lock is already present. This caller
    # should back off (return False, write nothing) rather than fight over the file.
    log_dir, log_file = log_paths
    log_dir.mkdir()
    (log_dir / ".lock_2025_3_regular").open("x").close()

    written = pick_log.log_picks(make_picks_df(), 2025, 3, "regular", log_dir=log_dir, log_file=log_file)

    assert written is False
    assert not log_file.exists()
    assert (log_dir / ".lock_2025_3_regular").exists()  # not this caller's lock to remove


def test_logged_weeks_lists_distinct_slates_sorted(log_paths):
    log_dir, log_file = log_paths
    pick_log.log_picks(make_picks_df(), 2025, 5, "regular", log_dir=log_dir, log_file=log_file)
    pick_log.log_picks(make_picks_df(), 2025, 2, "regular", log_dir=log_dir, log_file=log_file)
    pick_log.log_picks(make_picks_df(), 2024, 10, "regular", log_dir=log_dir, log_file=log_file)

    assert pick_log.logged_weeks(log_file) == [
        (2024, 10, "regular"), (2025, 2, "regular"), (2025, 5, "regular"),
    ]


def test_restore_log_replaces_existing_contents(log_paths):
    log_dir, log_file = log_paths
    pick_log.log_picks(make_picks_df(), 2025, 3, "regular", log_dir=log_dir, log_file=log_file)
    assert len(pick_log.load_log(log_file)) == 1

    backup = pd.DataFrame([
        {"logged_at": "2025-01-01T00:00:00Z", "year": 2025, "week": 1, "season_type": "regular",
         "home_team": "X", "away_team": "Y", "market_spread_home": -1.0, "pick_team": "X",
         "model_pick": "HOME (X)", "cover_prob": 0.6, "edge_points": 2.0, "tier": "B"},
    ])
    pick_log.restore_log(backup, log_dir=log_dir, log_file=log_file)

    restored = pick_log.load_log(log_file)
    assert len(restored) == 1
    assert restored.iloc[0]["home_team"] == "X"


def test_merge_log_appends_without_erasing_existing_entries(log_paths):
    log_dir, log_file = log_paths
    pick_log.log_picks(make_picks_df(), 2026, 2, "regular", log_dir=log_dir, log_file=log_file)
    assert len(pick_log.load_log(log_file)) == 1

    reconstructed = pd.DataFrame([
        {"logged_at": "2026-08-29T12:00:00+00:00", "year": 2026, "week": 1, "season_type": "regular",
         "home_team": "Old U", "away_team": "Other U", "market_spread_home": -7.0, "pick_team": "Old U",
         "model_pick": "HOME (Old U)", "cover_prob": 0.6, "edge_points": 3.0, "tier": "A"},
    ])
    pick_log.merge_log(reconstructed, log_dir=log_dir, log_file=log_file)

    merged = pick_log.load_log(log_file)
    assert len(merged) == 2  # both the original week 2 entry and the reconstructed week 1 one
    assert set(merged["week"]) == {1, 2}


def test_merge_log_relies_on_load_log_dedup_for_overlapping_slates(log_paths):
    log_dir, log_file = log_paths
    pick_log.log_picks(make_picks_df(), 2025, 3, "regular", log_dir=log_dir, log_file=log_file)

    # Re-merging the exact same slate/game shouldn't double it once read back.
    duplicate = pd.DataFrame([
        {"logged_at": "2025-01-01T00:00:00Z", "year": 2025, "week": 3, "season_type": "regular",
         "home_team": "Home U", "away_team": "Away U", "market_spread_home": -3.0, "pick_team": "Home U",
         "model_pick": "HOME (Home U)", "cover_prob": 0.65, "edge_points": 4.0, "tier": "A"},
    ])
    pick_log.merge_log(duplicate, log_dir=log_dir, log_file=log_file)

    assert len(pick_log.load_log(log_file)) == 1


def test_grade_logged_picks_empty_log_returns_empty(log_paths):
    _, log_file = log_paths
    result = pick_log.grade_logged_picks("fake-token", log_file=log_file)
    assert result.empty


def test_summarize_by_week_groups_by_year_week_and_season_type():
    graded = pd.DataFrame([
        {"year": 2025, "week": 3, "season_type": "regular", "outcome": "win"},
        {"year": 2025, "week": 3, "season_type": "regular", "outcome": "loss"},
        {"year": 2025, "week": 3, "season_type": "regular", "outcome": "win"},
        {"year": 2026, "week": 3, "season_type": "regular", "outcome": "win"},  # different year, same week number
        {"year": 2025, "week": 4, "season_type": "regular", "outcome": "loss"},
        {"year": 2025, "week": 4, "season_type": "regular", "outcome": None},  # ungraded, excluded
        {"year": 2025, "week": 5, "season_type": "regular", "outcome": "push"},  # push, excluded
    ])
    summary = pick_log.summarize_by_week(graded)

    wk3_2025 = summary[(summary["year"] == 2025) & (summary["week"] == 3)].iloc[0]
    assert wk3_2025["n"] == 3
    assert wk3_2025["wins"] == 2
    assert wk3_2025["losses"] == 1
    assert wk3_2025["win_rate"] == pytest.approx(2 / 3)

    wk3_2026 = summary[(summary["year"] == 2026) & (summary["week"] == 3)].iloc[0]
    assert wk3_2026["n"] == 1
    assert wk3_2026["wins"] == 1

    wk4_2025 = summary[(summary["year"] == 2025) & (summary["week"] == 4)].iloc[0]
    assert wk4_2025["n"] == 1  # the ungraded row doesn't count

    assert not ((summary["year"] == 2025) & (summary["week"] == 5)).any()  # push-only week is absent


def test_summarize_by_week_keeps_postseason_none_week_as_its_own_group():
    graded = pd.DataFrame([
        {"year": 2025, "week": None, "season_type": "postseason", "outcome": "win"},
        {"year": 2025, "week": 14, "season_type": "regular", "outcome": "loss"},
    ])
    summary = pick_log.summarize_by_week(graded)
    assert len(summary) == 2
    postseason_row = summary[summary["season_type"] == "postseason"].iloc[0]
    assert pd.isna(postseason_row["week"])  # None becomes NaN once week is a numeric DataFrame column
    assert postseason_row["wins"] == 1


def test_summarize_by_week_empty_when_nothing_decided():
    graded = pd.DataFrame([{"year": 2025, "week": 3, "season_type": "regular", "outcome": None}])
    summary = pick_log.summarize_by_week(graded)
    assert summary.empty
    assert list(summary.columns) == ["year", "week", "season_type", "n", "wins", "losses", "win_rate"]


def test_load_manual_records_empty_returns_dataframe_with_expected_columns(log_paths):
    log_dir, _ = log_paths
    df = pick_log.load_manual_records(log_dir / "manual_records.jsonl")
    assert df.empty
    assert list(df.columns) == ["year", "week", "season_type", "wins", "losses"]


def test_add_manual_record_roundtrip(log_paths):
    log_dir, _ = log_paths
    manual_file = log_dir / "manual_records.jsonl"

    pick_log.add_manual_record(2026, 1, "regular", 28, 21, log_dir=log_dir, manual_file=manual_file)

    df = pick_log.load_manual_records(manual_file)
    assert len(df) == 1
    assert df.iloc[0]["year"] == 2026
    assert df.iloc[0]["week"] == 1
    assert df.iloc[0]["wins"] == 28
    assert df.iloc[0]["losses"] == 21


def test_add_manual_record_overwrites_the_same_slate(log_paths):
    log_dir, _ = log_paths
    manual_file = log_dir / "manual_records.jsonl"

    pick_log.add_manual_record(2026, 1, "regular", 28, 21, log_dir=log_dir, manual_file=manual_file)
    pick_log.add_manual_record(2026, 1, "regular", 30, 19, log_dir=log_dir, manual_file=manual_file)  # correction

    df = pick_log.load_manual_records(manual_file)
    assert len(df) == 1  # replaced, not appended
    assert df.iloc[0]["wins"] == 30
    assert df.iloc[0]["losses"] == 19


def test_add_manual_record_keeps_distinct_slates_separate(log_paths):
    log_dir, _ = log_paths
    manual_file = log_dir / "manual_records.jsonl"

    pick_log.add_manual_record(2026, 1, "regular", 28, 21, log_dir=log_dir, manual_file=manual_file)
    pick_log.add_manual_record(2026, None, "postseason", 5, 2, log_dir=log_dir, manual_file=manual_file)

    df = pick_log.load_manual_records(manual_file)
    assert len(df) == 2


def test_delete_manual_record_removes_only_the_matching_slate(log_paths):
    log_dir, _ = log_paths
    manual_file = log_dir / "manual_records.jsonl"
    pick_log.add_manual_record(2026, 1, "regular", 28, 21, log_dir=log_dir, manual_file=manual_file)
    pick_log.add_manual_record(2026, 2, "regular", 10, 5, log_dir=log_dir, manual_file=manual_file)

    pick_log.delete_manual_record(2026, 1, "regular", manual_file=manual_file)

    df = pick_log.load_manual_records(manual_file)
    assert len(df) == 1
    assert df.iloc[0]["week"] == 2


def test_delete_manual_record_is_a_noop_when_nothing_matches(log_paths):
    log_dir, _ = log_paths
    manual_file = log_dir / "manual_records.jsonl"
    pick_log.delete_manual_record(2026, 1, "regular", manual_file=manual_file)  # file doesn't exist yet
    assert pick_log.load_manual_records(manual_file).empty


def test_sync_from_github_noop_without_a_token(log_paths, monkeypatch):
    log_dir, log_file = log_paths
    manual_file = log_dir / "manual_records.jsonl"

    def fail_if_called(*a, **k):
        raise AssertionError("should never touch the network without a token")
    monkeypatch.setattr(pick_log, "_github_get_file", fail_if_called)

    pick_log.sync_from_github("", log_dir=log_dir, log_file=log_file, manual_file=manual_file)
    # No exception, and nothing written — a true no-op, not a failed sync.
    assert not log_file.exists()


def test_sync_to_github_noop_without_a_token(log_paths, monkeypatch):
    log_dir, log_file = log_paths
    manual_file = log_dir / "manual_records.jsonl"
    pick_log.log_picks(make_picks_df(), 2026, 1, "regular", log_dir=log_dir, log_file=log_file)

    def fail_if_called(*a, **k):
        raise AssertionError("should never touch the network without a token")
    monkeypatch.setattr(pick_log, "_github_put_file", fail_if_called)

    pick_log.sync_to_github("", log_dir=log_dir, log_file=log_file, manual_file=manual_file)  # should not raise


def test_sync_to_github_swallows_failures(log_paths, monkeypatch):
    log_dir, log_file = log_paths
    manual_file = log_dir / "manual_records.jsonl"
    pick_log.log_picks(make_picks_df(), 2026, 1, "regular", log_dir=log_dir, log_file=log_file)

    def boom(*a, **k):
        raise RuntimeError("network is down")
    monkeypatch.setattr(pick_log, "_github_put_file", boom)

    pick_log.sync_to_github("fake-token", log_dir=log_dir, log_file=log_file, manual_file=manual_file)  # no raise


def test_sync_from_github_swallows_failures(log_paths, monkeypatch):
    log_dir, log_file = log_paths
    manual_file = log_dir / "manual_records.jsonl"

    def boom(*a, **k):
        raise RuntimeError("network is down")
    monkeypatch.setattr(pick_log, "_github_get_file", boom)

    pick_log.sync_from_github("fake-token", log_dir=log_dir, log_file=log_file, manual_file=manual_file)  # no raise
    assert not log_file.exists()  # nothing pulled, but no crash


def test_sync_from_github_writes_pulled_content(log_paths, monkeypatch):
    log_dir, log_file = log_paths
    manual_file = log_dir / "manual_records.jsonl"

    def fake_get(path, token):
        if path.endswith("logged_picks.jsonl"):
            return '{"year": 2026, "week": 1}\n', "sha1"
        return None, None
    monkeypatch.setattr(pick_log, "_github_get_file", fake_get)

    pick_log.sync_from_github("fake-token", log_dir=log_dir, log_file=log_file, manual_file=manual_file)

    assert log_file.exists()
    assert json.loads(log_file.read_text().strip()) == {"year": 2026, "week": 1}
    assert not manual_file.exists()  # fake_get returned None for this one — nothing to write
