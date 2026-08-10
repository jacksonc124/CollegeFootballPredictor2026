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


def test_grade_logged_picks_empty_log_returns_empty(log_paths):
    _, log_file = log_paths
    result = pick_log.grade_logged_picks("fake-token", log_file=log_file)
    assert result.empty
