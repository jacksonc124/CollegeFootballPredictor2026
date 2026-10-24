import base64
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import pick_log
from cbs_pickem import (
    cookie_expiry,
    cookie_expiry_warning,
    extract_pool_games,
    load_cookie_from_supabase,
    match_pool_games_to_df,
    match_team_name,
    resolve_top12_source,
    save_cookie_to_supabase,
)


def _fake_jwt(payload: dict) -> str:
    """A JWT-shaped (but unsigned/fake) token with the given payload — enough to test
    cbs_pickem's payload decoder, which never verifies signatures anyway (see its
    docstring: it only ever reads our own already-trusted cookie)."""
    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{b64({'alg': 'none'})}.{b64(payload)}.fakesignature"


def _cookie_with_auth_state(payload: dict) -> str:
    return f"userId=abc123; auth_state={_fake_jwt(payload)}; other=xyz"


def _sample_graphql_data():
    # Shaped like a real captured response (see cbs_pickem.py's module docstring) —
    # trimmed to just the fields extract_pool_games actually reads.
    return {
        "commonPool": {
            "poolPeriod": {
                "poolEvents": [
                    {
                        "homeTeam": {"mediumName": "Marshall"},
                        "awayTeam": {"mediumName": "South Alabama"},
                        "homeTeamSpread": 3.5,
                        "gameStatus": "F",
                        "startsAt": 1792539000000,
                        "weekNumber": 8,
                    },
                    {
                        "homeTeam": {"mediumName": "Ohio State"},
                        "awayTeam": {"mediumName": "Kent State"},
                        "homeTeamSpread": -52.5,
                        "gameStatus": "P",
                        "startsAt": 1792612800000,
                        "weekNumber": 8,
                    },
                ]
            }
        }
    }


def test_extract_pool_games_flattens_the_response():
    games = extract_pool_games(_sample_graphql_data())
    assert len(games) == 2
    assert games[0] == {
        "home_team": "Marshall", "away_team": "South Alabama", "home_spread": 3.5,
        "game_status": "F", "starts_at": 1792539000000, "week_number": 8,
    }
    assert games[1]["home_team"] == "Ohio State"


def test_extract_pool_games_handles_missing_fields_gracefully():
    assert extract_pool_games({}) == []
    assert extract_pool_games({"commonPool": {}}) == []
    assert extract_pool_games({"commonPool": {"poolPeriod": {}}}) == []


def test_match_team_name_exact_match():
    known = ["Marshall", "South Alabama", "Ohio State"]
    assert match_team_name("Marshall", known) == "Marshall"


def test_match_team_name_strips_trailing_qualifier():
    # Real mismatch seen in production: CBS writes "Miami (Fla.)", CFBD just "Miami".
    known = ["Miami", "Miami (OH)", "Pittsburgh"]
    assert match_team_name("Miami (Fla.)", known) == "Miami"


def test_match_team_name_handles_cbs_state_abbreviation():
    # Real mismatch seen in production: "Iowa St." vs CFBD's "Iowa State".
    known = ["Iowa State", "Arizona"]
    assert match_team_name("Iowa St.", known) == "Iowa State"


def test_match_team_name_handles_cbs_compound_abbreviation():
    # Real mismatch seen in production: "App. St." vs CFBD's "Appalachian State".
    known = ["Appalachian State", "James Madison"]
    assert match_team_name("App. St.", known) == "Appalachian State"


def test_match_team_name_abbreviation_does_not_misfire_on_token_count_mismatch():
    # "Ohio" (the MAC school) must never resolve to "Ohio State" just because it's a
    # prefix match on the first word — the token-count check should block that.
    known = ["Ohio", "Ohio State"]
    assert match_team_name("Ohio", known) == "Ohio"


def test_match_team_name_fuzzy_match_for_minor_differences():
    known = ["Miami", "Miami (OH)"]
    # CBS sometimes spells things slightly differently than CFBD; this should still
    # resolve to the closer of the two rather than picking the wrong Miami.
    assert match_team_name("Miami (OH)", known) == "Miami (OH)"


def test_match_team_name_returns_none_when_nothing_close():
    known = ["Marshall", "South Alabama"]
    assert match_team_name("Some Totally Different School", known) is None


def test_match_team_name_handles_missing_name():
    assert match_team_name(None, ["Marshall"]) is None
    assert match_team_name("", ["Marshall"]) is None


def _sample_df():
    return pd.DataFrame([
        {"home_team": "Marshall", "away_team": "South Alabama", "cover_prob": 0.6, "tier": "A"},
        {"home_team": "Ohio State", "away_team": "Kent State", "cover_prob": 0.52, "tier": "C"},
        {"home_team": "Georgia", "away_team": "Arkansas", "cover_prob": 0.7, "tier": "A"},  # not in pool
    ])


def test_match_pool_games_to_df_filters_to_only_pool_games():
    pool_games = extract_pool_games(_sample_graphql_data())
    known_names = ["Marshall", "South Alabama", "Ohio State", "Kent State", "Georgia", "Arkansas"]
    matched, unmatched = match_pool_games_to_df(pool_games, _sample_df(), known_names)

    assert len(matched) == 2
    assert set(matched["home_team"]) == {"Marshall", "Ohio State"}
    assert unmatched == []


def test_match_pool_games_to_df_flags_unmatched_games():
    pool_games = [{"home_team": "Totally Unknown School", "away_team": "Another Unknown", "home_spread": 1.0}]
    known_names = ["Marshall", "South Alabama"]
    matched, unmatched = match_pool_games_to_df(pool_games, _sample_df(), known_names)

    assert matched.empty
    assert len(unmatched) == 1
    assert unmatched[0]["home_team"] == "Totally Unknown School"


def test_match_pool_games_to_df_empty_df():
    pool_games = extract_pool_games(_sample_graphql_data())
    matched, unmatched = match_pool_games_to_df(pool_games, pd.DataFrame(), ["Marshall", "South Alabama"])
    assert matched.empty


def _known_names():
    return ["Marshall", "South Alabama", "Ohio State", "Kent State", "Georgia", "Arkansas"]


def test_resolve_top12_source_falls_back_when_fetch_raises():
    def boom():
        raise RuntimeError("expired cookie")
    df, status, unmatched = resolve_top12_source(_sample_df(), _known_names(), boom)
    assert df.equals(_sample_df())
    assert "expired cookie" in status
    assert "full-slate Top 12" in status
    assert unmatched == []


def test_resolve_top12_source_falls_back_when_no_pool_games_returned():
    df, status, unmatched = resolve_top12_source(_sample_df(), _known_names(), lambda: [])
    assert "no games" in status
    assert "full-slate Top 12" in status


def test_resolve_top12_source_falls_back_when_pool_games_match_nothing():
    pool_games = [{"home_team": "Totally Unknown", "away_team": "Also Unknown"}]
    df, status, unmatched = resolve_top12_source(_sample_df(), _known_names(), lambda: pool_games)
    assert "None of your pool's games matched" in status
    assert "full-slate Top 12" in status


def test_resolve_top12_source_uses_pool_filtered_df_on_success():
    pool_games = extract_pool_games(_sample_graphql_data())  # Marshall/South Alabama + Ohio State/Kent State
    df, status, unmatched = resolve_top12_source(_sample_df(), _known_names(), lambda: pool_games)

    assert len(df) == 2
    assert set(df["home_team"]) == {"Marshall", "Ohio State"}
    assert "Filtered to your 2-game CBS pool" in status
    assert "Week 8" in status
    assert unmatched == []


def test_cookie_expiry_reads_the_exp_claim():
    expires_at = datetime(2027, 1, 1, tzinfo=timezone.utc)
    cookie = _cookie_with_auth_state({"exp": int(expires_at.timestamp())})
    assert cookie_expiry(cookie) == expires_at


def test_cookie_expiry_none_without_auth_state():
    assert cookie_expiry("userId=abc123; other=xyz") is None


def test_cookie_expiry_none_for_malformed_token():
    assert cookie_expiry("auth_state=not-a-real-jwt; other=xyz") is None


def test_cookie_expiry_warning_none_when_far_from_expiry():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cookie = _cookie_with_auth_state({"exp": int((now + timedelta(days=30)).timestamp())})
    assert cookie_expiry_warning(cookie, now=now) is None


def test_cookie_expiry_warning_within_threshold():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cookie = _cookie_with_auth_state({"exp": int((now + timedelta(days=3)).timestamp())})
    warning = cookie_expiry_warning(cookie, now=now)
    assert "expires in 3 day(s)" in warning


def test_cookie_expiry_warning_already_expired():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cookie = _cookie_with_auth_state({"exp": int((now - timedelta(days=1)).timestamp())})
    warning = cookie_expiry_warning(cookie, now=now)
    assert "has expired" in warning


def test_cookie_expiry_warning_none_when_expiry_unknown():
    assert cookie_expiry_warning("userId=abc123") is None


def test_load_cookie_from_supabase_noop_without_credentials(monkeypatch):
    def fail_if_called(*a, **k):
        raise AssertionError("should not call Supabase without credentials")
    monkeypatch.setattr(pick_log, "get_synced_file", fail_if_called)
    assert load_cookie_from_supabase("", "") is None


def test_load_cookie_from_supabase_returns_saved_cookie(monkeypatch):
    monkeypatch.setattr(pick_log, "get_synced_file", lambda path, url, key: "auth_state=fresh")
    assert load_cookie_from_supabase("https://x.supabase.co", "key") == "auth_state=fresh"


def test_load_cookie_from_supabase_swallows_failures(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network error")
    monkeypatch.setattr(pick_log, "get_synced_file", boom)
    assert load_cookie_from_supabase("https://x.supabase.co", "key") is None


def test_save_cookie_to_supabase_calls_put_synced_file(monkeypatch):
    calls = []
    monkeypatch.setattr(pick_log, "put_synced_file", lambda path, content, url, key: calls.append((path, content)))
    save_cookie_to_supabase("auth_state=new-cookie", "https://x.supabase.co", "key")
    assert calls == [("cbs_cookie.txt", "auth_state=new-cookie")]
