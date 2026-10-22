import os
import types
from datetime import datetime

import streamlit as st

import cbs_pickem
import model
import pick_log
import ui_helpers
from tabs import accuracy, markets, parlays, pickem, rankings, stats, today
from ui_helpers import (
    ACCENT, CENTRAL, TIER_COLORS, format_game_date, stat_row_html,
    team_row_html, team_slot_html, tier_badge_text_color,
)

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="CFB Gambling Model", page_icon="🏈", layout="wide")

# ── styling ───────────────────────────────────────────────────────────────────
st.markdown(ui_helpers.STYLES, unsafe_allow_html=True)

# ── session state ─────────────────────────────────────────────────────────────
if "parlay_legs" not in st.session_state:
    st.session_state["parlay_legs"] = 3

# ── secrets ───────────────────────────────────────────────────────────────────
try:
    bearer_token = st.secrets["BEARER_TOKEN"]
except Exception:
    bearer_token = os.environ.get("BEARER_TOKEN", "")

# Optional: a Supabase project lets the pick log survive a Streamlit Cloud redeploy by
# syncing it to a real external database instead of only local disk (see pick_log.py's
# sync_from_supabase/sync_to_supabase). Absent entirely if never configured — the log just
# stays local-disk-only, wiped on redeploy, same as before this existed.
try:
    supabase_url = st.secrets["SUPABASE_URL"]
    supabase_key = st.secrets["SUPABASE_KEY"]
except Exception:
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_KEY", "")

if supabase_url and supabase_key and "supabase_synced" not in st.session_state:
    pick_log.sync_from_supabase(supabase_url, supabase_key)
    st.session_state["supabase_synced"] = True

# Optional: lets the Pick'em tab filter its ranked list down to only the games actually in
# your CBS Sports Pick'em pool (see cbs_pickem.py) — CBS's pool is usually a subset of the
# week's full slate, not every game. CBS_COOKIE is your browser session (see README for how
# to grab one; it's a revocable session token, not your password). Absent entirely if never
# configured — the Pick'em tab just shows the full-slate Top 12 as before.
try:
    cbs_cookie = st.secrets["CBS_COOKIE"]
    cbs_pool_id = st.secrets["CBS_POOL_ID"]
    cbs_entry_id = st.secrets["CBS_ENTRY_ID"]
except Exception:
    cbs_cookie = os.environ.get("CBS_COOKIE", "")
    cbs_pool_id = os.environ.get("CBS_POOL_ID", "")
    cbs_entry_id = os.environ.get("CBS_ENTRY_ID", "")
cbs_configured = bool(cbs_cookie and cbs_pool_id and cbs_entry_id)
# Checked once per rerun (cheap — no network, just decodes the cookie's own JWT claim),
# so there's a heads-up before the cookie expires instead of just a silent fallback to
# the full-slate Top 12 the week it finally does.
cbs_cookie_warning = cbs_pickem.cookie_expiry_warning(cbs_cookie) if cbs_configured else None


@st.cache_data(show_spinner=False, ttl=86400)
def get_calendar_cached(yr):
    try:
        return model.get_calendar(bearer_token, yr)
    except Exception as e:
        print(f"Warning: failed to fetch calendar (defaults fall back to last year's week 1): {e}")
        return []


# Defined here (rather than alongside the rest of the cached wrappers, further down) because
# the sidebar needs team names/conferences for the Favorite Team and Conferences controls,
# and the sidebar renders before that section. Both only depend on `year`, not week/season_type,
# so fetching them this early costs nothing extra — same cached value either way.
@st.cache_data(show_spinner=False, ttl=86400)
def get_team_logos(yr):
    return model.get_team_logos(bearer_token, yr)


@st.cache_data(show_spinner=False, ttl=86400)
def get_team_conferences(yr):
    return model.get_team_conferences(bearer_token, yr)


# ── top control bar (was a left sidebar; moved to the top of the page) ────────
# date.today() is the server's system clock, not Central — on a UTC host it flips to
# "tomorrow" as early as 7pm Central, hours before it's actually tomorrow for anyone
# watching a game. Every "today" in this app needs to mean Central-today specifically.
_today = datetime.now(CENTRAL).date()
default_year, default_week = model.resolve_current_week(get_calendar_cached(_today.year), _today.year, _today)

st.markdown("# 🏈 CFB MODEL")
bar1, bar2, bar3, bar4, bar5 = st.columns([1, 1.3, 1, 1.2, 1.5])
with bar1:
    year = st.number_input("Year", min_value=2000, max_value=2030, value=default_year, step=1)
with bar2:
    postseason = st.checkbox("📬 Postseason / Bowl Games", value=False,
                             help="Fetches every bowl & CFP game for the selected year, ignoring week. "
                                  "CFBD groups all of them under one 'week', so the week selector doesn't apply here.")
with bar3:
    # A dropdown beats a drag-slider for picking one of 15 discrete values on a touchscreen —
    # a slider needs a precise drag gesture, a dropdown just needs a tap.
    week = st.selectbox(
        "Week", options=list(range(1, 16)), index=default_week - 1,
        format_func=lambda w: f"Week {w}", disabled=postseason,
    )
with bar4:
    today_only = st.checkbox("📅 Today's games only", value=False,
                             help="Filter to just games kicking off today (in CT, matching the "
                                  "kickoff times shown on each card).")

# Both only depend on `year`, fetched here (not in the main fetch block below, which
# doesn't run until after this control bar) so these controls have real options on first
# render. Caught broadly and degraded to "no options" rather than crashing the page —
# e.g. if cfbd isn't installed yet, that's reported by the friendlier check further down.
try:
    _sidebar_team_names = sorted(get_team_logos(year).keys())
    _sidebar_conferences = sorted(set(get_team_conferences(year).values()))
except Exception as e:
    print(f"Warning: failed to load team/conference options for the control bar: {e}")
    _sidebar_team_names, _sidebar_conferences = [], []

with bar5:
    # No login system exists here, so there's no per-user account to attach this to —
    # the closest real equivalent is making it sticky for this browser via the URL's
    # query string, which survives reloads and works from a bookmark. Query params are
    # per-tab/URL, not a synced account, so it won't follow across a different browser
    # or an incognito window; that's an honest limit of "persistent" without auth.
    NO_FAVORITE = "— None —"
    favorite_options = [NO_FAVORITE] + _sidebar_team_names
    default_favorite = st.query_params.get("favorite_team", NO_FAVORITE)
    if default_favorite not in favorite_options:
        default_favorite = NO_FAVORITE

    favorite_team = st.selectbox(
        "⭐ Favorite Team", options=favorite_options, index=favorite_options.index(default_favorite),
        help="Highlights this team's game wherever it shows up in the current slate. Saved in "
             "the page's URL — reloading or revisiting that URL (e.g. from a bookmark) remembers it.",
    )
    if favorite_team == NO_FAVORITE:
        favorite_team = None
        st.query_params.pop("favorite_team", None)
    else:
        st.query_params["favorite_team"] = favorite_team

week0_filter = "All"
if week == 1 and not postseason:
    week0_filter = st.radio(
        "Week 1 slate", ["All", "Week 0 only", "Week 1 only"], horizontal=True,
        help="CFBD lumps the early season-opening games (what fans call 'Week 0') and the "
             "Labor Day weekend slate together under one 'week 1' — there's no such split in "
             "their data. This filters by actual game date instead (cutoff: the Thursday "
             "before Labor Day).",
    )

# Conferences and Home Field Advantage are lower-frequency tweaks than the controls
# above, so they're tucked into an expander rather than taking up a permanent row.
with st.expander("⚙️ More filters & advanced"):
    adv1, adv2 = st.columns([3, 1])
    with adv1:
        selected_conferences = st.multiselect(
            "🏟️ Conferences", options=_sidebar_conferences, default=_sidebar_conferences,
            help="Only show games involving at least one team from these conferences. "
                 "Leave everything selected to show every conference.",
        )
    with adv2:
        home_field = st.number_input(
            "Home Field Advantage (pts)",
            min_value=0.0, max_value=10.0, value=model.DEFAULT_HOME_FIELD, step=0.5,
            help="Applied only to true home games. Neutral-site games (most bowls, CFP quarterfinals/"
                 "semifinals/championship) automatically get 0 — detected per-game from CFBD, not guessed "
                 "from the postseason toggle. CFP first-round games are true home games for the higher seed, "
                 "so they still get this value.",
        )

st.markdown(
    f'<div class="fetch-caption">📡 Fetching <b>{year} · '
    f'{"Postseason" if postseason else f"Week {week}"}</b> · consensus lines'
    f'<br/>Results update automatically as you change these settings. '
    f'Ratings/lines are cached up to 1 hour.</div>',
    unsafe_allow_html=True,
)
st.markdown("---")

# Resolve API params from the control bar's state
season_type = "postseason" if postseason else "regular"
api_week    = None if postseason else week


# ── header ────────────────────────────────────────────────────────────────────
season_label = "POSTSEASON" if postseason else f"WK {week}"
if week0_filter != "All":
    season_label += f" · {week0_filter}"
if today_only:
    season_label += " · Today Only"
st.markdown(f"### {year} · {season_label}")
st.caption("SP+ ratings vs. consensus market spreads · Edge-based ATS picks")
st.markdown("---")

if not bearer_token:
    st.error("No Bearer Token found. Set BEARER_TOKEN in Streamlit secrets.")
    st.stop()

try:
    import cfbd  # noqa: F401  (validates the SDK is installed before we hit cached wrappers below)
except ImportError:
    st.error("Run `python -m pip install cfbd` and restart.")
    st.stop()


# ── cached wrappers around the shared model's CFBD fetchers ───────────────────
@st.cache_data(show_spinner=False, ttl=3600)
def get_sp_ratings(yr):
    return model.get_sp_ratings(bearer_token, yr)


@st.cache_data(show_spinner=False, ttl=3600)
def get_weekly_lines(yr, wk, stype):
    return model.get_weekly_lines(bearer_token, yr, wk, stype)


@st.cache_data(show_spinner=False, ttl=3600)
def get_game_info(yr, wk, stype):
    return model.get_game_info(bearer_token, yr, wk, stype)


@st.cache_data(show_spinner=False, ttl=86400)
def get_team_colors(yr):
    return model.get_team_colors(bearer_token, yr)


@st.cache_data(show_spinner=False, ttl=3600)
def get_scoring_stats(yr):
    # "both" so the totals model reflects every game played this season (regular +
    # postseason so far), regardless of which slate the sidebar is currently showing.
    return model.get_team_scoring_stats(bearer_token, yr, "both")


@st.cache_data(show_spinner=False, ttl=3600)
def get_rankings(yr, wk, stype):
    return model.get_rankings(bearer_token, yr, wk, stype)


@st.cache_data(show_spinner=False, ttl=3600)
def get_game_weather(yr, wk, stype):
    # Requires CFBD's "weather" feature (Tier 1+). Degrades to no adjustment on lower tiers
    # rather than breaking the whole app.
    try:
        return model.get_game_weather(bearer_token, yr, wk, stype)
    except Exception as e:
        print(f"Warning: failed to fetch weather (requires CFBD Tier 1+ 'weather' access): {e}")
        return {}


@st.cache_data(show_spinner=False, ttl=60)
def get_scoreboard(known_team_names):
    # Live score data — a 1-hour cache (this app's usual default) would leave the Today
    # tab frozen mid-game for most of an hour; 60s keeps it close to real-time without
    # hammering the API on every widget interaction's rerun. Non-fatal on failure: no
    # live scores just means Today's Games falls back to showing kickoff time only, same
    # as before this feature existed.
    try:
        return model.get_scoreboard(bearer_token, known_team_names)
    except Exception as e:
        print(f"Warning: failed to fetch live scoreboard: {e}")
        return {}


@st.cache_data(show_spinner=False, ttl=21600)
def get_adjusted_metrics(yr):
    # Requires CFBD's "adjustedMetrics" feature (Tier 1+). Same graceful degradation as weather.
    try:
        return model.get_adjusted_team_metrics(bearer_token, yr)
    except Exception as e:
        print(f"Warning: failed to fetch adjusted metrics (requires CFBD Tier 1+ 'adjustedMetrics' access): {e}")
        return {}


@st.cache_data(show_spinner=False, ttl=21600)
def get_ats_records(yr):
    return model.get_team_ats_records(bearer_token, yr)


@st.cache_data(show_spinner=False, ttl=21600)
def get_season_backtest(yr):
    import backtest
    return backtest.backtest_season(bearer_token, yr, range(1, 16), "regular")


@st.cache_data(show_spinner=False, ttl=3600)
def get_player_season_stats(yr, category):
    return model.get_player_season_stats(bearer_token, yr, category, "regular")


@st.cache_data(show_spinner=False, ttl=600)
def get_cbs_pool_games():
    # Short TTL (10 min, vs. this app's usual 1h) since lines/game status move throughout
    # game day and this is explicitly about "what's in my pool right now." Non-fatal on
    # failure — an expired cookie or CBS-side change surfaces as a clear error message in
    # the Pick'em tab (see cbs_pickem.py's docstring: this is unofficial and unverified
    # against a live call), not a crashed app.
    data = cbs_pickem.fetch_pool_games(cbs_cookie, cbs_pool_id, cbs_entry_id)
    return cbs_pickem.extract_pool_games(data)


# ── Fetch ─────────────────────────────────────────────────────────────────────
with st.spinner("Fetching ratings, lines, and logos…"):
    try:
        ratings          = get_sp_ratings(year)
        games            = get_weekly_lines(year, api_week, season_type)
        game_info        = get_game_info(year, api_week, season_type)
        scoring_stats    = get_scoring_stats(year)
        rankings_data    = get_rankings(year, api_week, season_type)
        game_weather     = get_game_weather(year, api_week, season_type)
        adjusted_metrics = get_adjusted_metrics(year)
        ats_records      = get_ats_records(year)
        df               = model.build_picks(ratings, games, model.DEFAULT_PROVIDER, home_field, model.SPREAD_STD_DEV,
                                              game_info=game_info, scoring_stats=scoring_stats,
                                              adjusted_metrics=adjusted_metrics, game_weather=game_weather)
        logos            = get_team_logos(year)
        team_colors      = get_team_colors(year)
    except Exception as e:
        st.error(f"API error: {e}")
        st.stop()

if df.empty:
    st.warning("No games returned. Try a different year or toggle postseason.")
    st.stop()

# ── Auto-log the current week's picks ───────────────────────────────────────────
# Uses the full, unfiltered df (before the Week 0/1 split below) so the log always
# captures the whole week's picks regardless of which display filter happens to be
# selected. Only the slate resolve_current_week() actually identifies as "now" — not
# whatever year/week the sidebar happens to be showing, since a user browsing a past
# week shouldn't silently log it (that would defeat the "recorded before kickoff"
# premise pick_log.py exists for). Postseason isn't auto-detected as "current"
# (resolve_current_week only reasons about regular-season weeks), so postseason picks
# still need the manual button.
is_current_slate = (not postseason) and year == default_year and week == default_week
if is_current_slate:
    auto_log_key = f"auto_logged_{year}_{week}_{season_type}"
    if auto_log_key not in st.session_state:
        pick_log.log_picks(df, year, api_week, season_type)  # no-op if already logged
        # Slates logged before totals/moneylines were tracked: fill those in for games that
        # haven't kicked off yet (never after — see backfill_extras).
        pick_log.backfill_extras(df, year, api_week, season_type)
        pick_log.sync_to_supabase(supabase_url, supabase_key)  # no-op if Supabase sync isn't configured
        st.session_state[auto_log_key] = True

# Applied after auto-logging (above), not before — the pick log is meant to be a complete
# record of the slate for accuracy tracking, and shouldn't silently shrink just because
# the user happened to have a conference filter narrowed down while it fired.
if selected_conferences and len(selected_conferences) < len(_sidebar_conferences):
    team_conferences = get_team_conferences(year)
    in_selected_conf = (
        df["home_team"].map(team_conferences).isin(selected_conferences)
        | df["away_team"].map(team_conferences).isin(selected_conferences)
    )
    df = df[in_selected_conf].reset_index(drop=True)
    if df.empty:
        st.warning("No games match the selected conferences. Try selecting more.")
        st.stop()

if week0_filter != "All":
    is_week0 = df["start_date"].apply(lambda d: model.is_week_zero_game(d, year))
    df = df[is_week0 if week0_filter == "Week 0 only" else ~is_week0].reset_index(drop=True)
    if df.empty:
        st.warning(f"No games found for '{week0_filter}'. Try 'All' instead.")
        st.stop()

if today_only:
    is_today = df["start_date"].apply(lambda d: model.is_game_on_date(d, _today, CENTRAL))
    df = df[is_today].reset_index(drop=True)
    if df.empty:
        st.warning("No games today for this slate. Try turning off 'Today's games only'.")
        st.stop()

# Snapshot for the "Today's Games" landing tab — computed on raw (pre-format) start_date,
# independent of the "Today's games only" sidebar checkbox, so that tab always reflects
# literally today regardless of whether the user has that filter on.
today_df = df[df["start_date"].apply(lambda d: model.is_game_on_date(d, _today, CENTRAL))].copy()
if not today_df.empty:
    # .apply(axis=1) on an empty DataFrame returns the DataFrame unchanged (not a Series),
    # which breaks the single-column assignment below — only worth doing with rows present.
    today_df["start_date"] = today_df.apply(lambda r: format_game_date(r["start_date"], r["start_time_tbd"]), axis=1)
today_df = today_df.drop(columns=["start_time_tbd"]).reset_index(drop=True)

df["start_date"] = df.apply(lambda r: format_game_date(r["start_date"], r["start_time_tbd"]), axis=1)
df = df.drop(columns=["start_time_tbd"])

# model_spread_home is stored as a rating differential (positive = home team rated
# better/favored) — the opposite sign convention from market_spread_home (CFBD/Vegas:
# negative = home favored). Showing both raw side by side in the All Games table reads
# as if they disagree on who's favored when they don't (e.g. model +23.8 / market -26.5
# both mean "home favored," just in opposite notations) — flip it here, display-only,
# so "Model Spread" reads the same way as "Market Spread" already does. Nothing else in
# this file, pick_log.py, or backtest.py reads model_spread_home, so this is safe to
# negate in place rather than adding a parallel display column.
df["model_spread_home"] = -df["model_spread_home"]

strong = model.strong_picks(df)


# ── Logo helper ───────────────────────────────────────────────────────────────
def logo_img(team, size=32, dim=False):
    """
    Render a team logo (or initials fallback) inside a light circular chip, ringed
    with the team's real brand color when known. The chip guarantees contrast
    regardless of app theme or how dark/transparent a given team's logo artwork is —
    some logos are otherwise invisible on a dark background. The color ring is purely
    decorative team identity (dynamic branding) — it never carries meaning on its own,
    so a missing color just falls back to the neutral border, not a broken chip.

    dim=True grayscales the chip (see .logo-chip-dim) — used on whichever side of a
    matchup card ISN'T the model's pick, so "not this team" reads at a glance even
    before noticing the other side's colored glow ring (see ui_helpers.team_slot_html).
    """
    url = logos.get(team, "")
    if url:
        inner = f'<img src="{url}" width="{size}" height="{size}" style="object-fit:contain;" />'
    else:
        initials = "".join(w[0] for w in team.split()[:2]).upper()
        inner = f'<span style="font-family:\'Anton\',sans-serif;font-size:{size // 2}px;color:#0d0f14;">{initials}</span>'
    pad = max(2, size // 8)
    chip_size = size + pad * 2
    ring_color = team_colors.get(team, "")
    border = f'border: 2px solid {ring_color};' if ring_color else ""
    dim_class = " logo-chip-dim" if dim else ""
    return f'<span class="logo-chip{dim_class}" style="width:{chip_size}px;height:{chip_size}px;{border}">{inner}</span>'


def fav_star(team: str) -> str:
    """A small marker for the favorite team, prefixed the same way rank_badge()
    prefixes AP/Coaches rank — so it's visible in any listing without a dedicated card."""
    return "⭐ " if favorite_team and team == favorite_team else ""


# ── Shared context passed to every tabs/*.py render(ctx) ──────────────────────
# Built here (rather than after the favorite-team card) so the favorite-team card and
# the today-strip below can both use it, side by side, instead of duplicating logic.
ctx = types.SimpleNamespace(
    df=df, today_df=today_df, strong=strong,
    logos=logos, team_colors=team_colors, rankings=rankings_data, ats_records=ats_records,
    favorite_team=favorite_team,
    year=year, week=week, postseason=postseason, season_type=season_type, api_week=api_week,
    is_current_slate=is_current_slate, season_label=season_label,
    today=_today,
    bearer_token=bearer_token, supabase_url=supabase_url, supabase_key=supabase_key,
    logo_img=logo_img, fav_star=fav_star,
    get_scoreboard=get_scoreboard, get_sp_ratings=get_sp_ratings,
    get_season_backtest=get_season_backtest, get_player_season_stats=get_player_season_stats,
    cbs_configured=cbs_configured, get_cbs_pool_games=get_cbs_pool_games,
    cbs_cookie_warning=cbs_cookie_warning,
)


# ── Favorite team highlight + today's games, side by side ────────────────────────
# Today's Games used to be its own tab, but every stat on it (tier/cover prob/ML/O-U)
# already has a dedicated home elsewhere — now it's a compact strip up here instead,
# next to the one other "about you/today" thing on the page.
_has_fav_card = bool(favorite_team)
fav_col, today_col = (st.columns([1, 2]) if _has_fav_card else (None, st.container()))

if favorite_team:
    with fav_col:
        fav_rows = df[(df["home_team"] == favorite_team) | (df["away_team"] == favorite_team)]
        if fav_rows.empty:
            st.info(f"⭐ {favorite_team} isn't playing in this slate.")
        else:
            row = fav_rows.iloc[0]
            tier, home, away       = row["tier"], row["home_team"], row["away_team"]
            pick_team, cover, edge = row["pick_team"], row["cover_prob"], row["edge_points"]
            spread                 = row["market_spread_home"]
            neutral_site           = row.get("neutral_site")
            venue                  = row.get("venue") or ""
            game_date              = row.get("start_date") or ""
            tier_color             = TIER_COLORS.get(tier, ACCENT)
            tier_text              = tier_badge_text_color(tier)
            # This card is framed in the fan's own team's brand color (not the tier
            # color) since it's "your team", not primarily a pick — the pick itself
            # still shows via the tier-colored glow on whichever logo the model
            # actually picked, so the two meanings stay visually distinct.
            fav_color              = team_colors.get(favorite_team) or tier_color
            if neutral_site is None:
                site_str = ""
            elif neutral_site:
                site_str = f"🏟 {venue}" if venue else "🏟 Neutral Site"
            else:
                site_str = f"🏠 {venue}" if venue else "🏠 Home Game"

            # Dim only the side that's neither the favorite nor the model's pick — your
            # own team never goes black-and-white on its own card, even on weeks the
            # model likes the other side.
            away_slot = team_slot_html(
                f"{model.rank_badge(away, rankings_data)}{away}",
                logo_img(away, 56, dim=pick_team != away and away != favorite_team),
                is_pick=pick_team == away, tier_color=tier_color,
            )
            home_slot = team_slot_html(
                f"{model.rank_badge(home, rankings_data)}{home}",
                logo_img(home, 56, dim=pick_team != home and home != favorite_team),
                is_pick=pick_team == home, tier_color=tier_color,
            )
            meta_lines = [l for l in [site_str, f"🗓 {game_date}" if game_date else ""] if l]
            st.markdown(
                f'<div class="matchup-card" style="--tier:{fav_color};">'
                f'<div class="matchup-card-top">'
                f'<div class="matchup-rank">⭐ Your Team</div>'
                f'<div class="tier-badge" style="--tier:{tier_color};--tier-text:{tier_text};">TIER {tier}</div>'
                f'</div>'
                f'{team_row_html(away_slot, home_slot)}'
                f'{stat_row_html([(f"{cover:.0%}", "Cover Prob"), (f"{spread:+.1f}", "Spread"), (f"{edge:+.1f}", "Edge")])}'
                f'<div class="extra-meta">{"<br/>".join(meta_lines)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

with today_col:
    today.render_strip(ctx)

st.markdown("---")


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab0, tab1, tab2, tab3, tab4 = st.tabs([
    "🏆  CBS Pick'em Top 12",
    "🎲  Gambling",
    "🥇  Rankings & ATS",
    "📊  Model Accuracy",
    "📈  Stats",
])

with tab0:
    pickem.render(ctx)

with tab1:
    markets.render(ctx)
    st.markdown("---")
    parlays.render(ctx)

with tab2:
    rankings.render(ctx)

with tab3:
    accuracy.render(ctx)

with tab4:
    stats.render(ctx)
