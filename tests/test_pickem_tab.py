import types

import pandas as pd
import pytest

from tabs.pickem import _resolve_top12_source


def _make_df():
    return pd.DataFrame([
        {"home_team": "Marshall", "away_team": "South Alabama", "tier": "A", "cover_prob": 0.6},
        {"home_team": "Ohio State", "away_team": "Kent State", "tier": "C", "cover_prob": 0.52},
    ])


def _make_ctx(cbs_configured, get_cbs_pool_games=None, df=None):
    return types.SimpleNamespace(
        cbs_configured=cbs_configured,
        get_cbs_pool_games=get_cbs_pool_games,
        logos={"Marshall": "", "South Alabama": "", "Ohio State": "", "Kent State": ""},
        df=df if df is not None else _make_df(),
    )


def test_falls_back_to_full_slate_when_cbs_not_configured():
    ctx = _make_ctx(cbs_configured=False)
    df, status, unmatched = _resolve_top12_source(ctx)
    assert df is ctx.df
    assert status is None
    assert unmatched == []


def test_falls_back_when_fetch_raises():
    def boom():
        raise RuntimeError("expired cookie")
    ctx = _make_ctx(cbs_configured=True, get_cbs_pool_games=boom)
    df, status, unmatched = _resolve_top12_source(ctx)
    assert df is ctx.df
    assert "expired cookie" in status
    assert "full-slate Top 12" in status
    assert unmatched == []


def test_falls_back_when_no_pool_games_returned():
    ctx = _make_ctx(cbs_configured=True, get_cbs_pool_games=lambda: [])
    df, status, unmatched = _resolve_top12_source(ctx)
    assert df is ctx.df
    assert "no games" in status
    assert "full-slate Top 12" in status


def test_falls_back_when_pool_games_match_nothing_in_this_slate():
    pool_games = [{"home_team": "Totally Unknown", "away_team": "Also Unknown"}]
    ctx = _make_ctx(cbs_configured=True, get_cbs_pool_games=lambda: pool_games)
    df, status, unmatched = _resolve_top12_source(ctx)
    assert df is ctx.df
    assert "None of your pool's games matched" in status
    assert "full-slate Top 12" in status


def test_uses_pool_filtered_df_on_success():
    pool_games = [
        {"home_team": "Marshall", "away_team": "South Alabama", "week_number": 8},
        {"home_team": "Not A Match", "away_team": "Still Not A Match", "week_number": 8},
    ]
    ctx = _make_ctx(cbs_configured=True, get_cbs_pool_games=lambda: pool_games)
    df, status, unmatched = _resolve_top12_source(ctx)

    assert len(df) == 1
    assert df.iloc[0]["home_team"] == "Marshall"
    assert "Filtered to your 1-game CBS pool" in status
    assert "Week 8" in status
    assert len(unmatched) == 1
    assert unmatched[0]["home_team"] == "Not A Match"
