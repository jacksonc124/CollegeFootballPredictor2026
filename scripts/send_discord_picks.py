"""
Standalone entry point for the send_weekly_picks GitHub Action
(.github/workflows/send_weekly_picks.yml). Builds this week's Top 12 ATS picks exactly
the way the Pick'em tab does (CBS-pool-filtered when configured, full-slate otherwise —
see cbs_pickem.resolve_top12_source, shared with that tab) and posts them to Discord via
an incoming webhook — all without a running Streamlit process.

Requires BEARER_TOKEN (CFBD) and DISCORD_WEBHOOK_URL as environment variables — GitHub
Actions repo secrets, not Streamlit secrets (this never runs inside Streamlit).
CBS_COOKIE/CBS_POOL_ID/CBS_ENTRY_ID are optional, same as the Streamlit app: absent
entirely, this posts the full-slate Top 12 instead of a CBS-pool-filtered one.
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

# Python only adds this script's own directory (scripts/) to sys.path, not the repo root —
# so the modules below (which live at the repo root) aren't importable without this,
# regardless of the invoking shell's current directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cbs_pickem  # noqa: E402
import discord_notify  # noqa: E402
import model  # noqa: E402

# date.today() is the server's system clock, not Central — on a UTC host (this Action)
# it can flip to "tomorrow" hours before it's actually tomorrow for anyone watching a
# game. Matches app.py's own reasoning for using Central-today specifically.
CENTRAL = ZoneInfo("America/Chicago")


def main() -> int:
    bearer_token = os.environ.get("BEARER_TOKEN")
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    cbs_cookie = os.environ.get("CBS_COOKIE")
    cbs_pool_id = os.environ.get("CBS_POOL_ID")
    cbs_entry_id = os.environ.get("CBS_ENTRY_ID")

    if not bearer_token:
        print("BEARER_TOKEN not set — nothing to do.")
        return 1
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL not set — nowhere to post.")
        return 1

    # A cookie saved via the in-app "Replace CBS cookie" form overrides the CBS_COOKIE
    # secret below — same reasoning as app.py: replacing an expired cookie should reach
    # this scheduled job too, not just the Streamlit app, with no separate secret update.
    _stored_cookie = cbs_pickem.load_cookie_from_supabase(supabase_url, supabase_key)
    if _stored_cookie:
        cbs_cookie = _stored_cookie

    today = datetime.now(CENTRAL).date()
    calendar = model.get_calendar(bearer_token, today.year)
    year, week = model.resolve_current_week(calendar, today.year, today)

    ratings = model.get_sp_ratings(bearer_token, year)
    games = model.get_weekly_lines(bearer_token, year, week, "regular")
    game_info = model.get_game_info(bearer_token, year, week, "regular")
    df = model.build_picks(ratings, games, game_info=game_info)

    if df.empty:
        print(f"No games found for {year} week {week} — nothing to post.")
        return 0

    known_team_names = set(model.get_team_logos(bearer_token, year).keys())

    cbs_configured = bool(cbs_cookie and cbs_pool_id and cbs_entry_id)
    source_df, cbs_status, cookie_warning = df, None, None
    if cbs_configured:
        def fetch_pool_games():
            data = cbs_pickem.fetch_pool_games(cbs_cookie, cbs_pool_id, cbs_entry_id)
            return cbs_pickem.extract_pool_games(data)

        source_df, cbs_status, _unmatched = cbs_pickem.resolve_top12_source(
            df, known_team_names, fetch_pool_games,
        )
        cookie_warning = cbs_pickem.cookie_expiry_warning(cbs_cookie)

    top12 = (source_df[source_df["tier"] != "Pass"]
             .sort_values("cover_prob", ascending=False)
             .head(12).reset_index(drop=True))

    if top12.empty:
        print(f"No picks above Pass tier for {year} week {week} — nothing to post.")
        return 0

    season_label = f"{year} · Week {week}"
    payload = discord_notify.build_top12_embed(top12, season_label, cbs_status, cookie_warning)
    discord_notify.send_webhook(payload, webhook_url)
    print(f"Posted {len(top12)} picks to Discord for {season_label}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
