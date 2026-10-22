import os
import types
from datetime import datetime

import streamlit as st

import cbs_pickem
import model
import pick_log
import ui_helpers
from tabs import accuracy, markets, parlays, pickem, rankings, stats, today
from ui_helpers import ACCENT, CENTRAL, TIER_COLORS, format_game_date

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


# ── sidebar ───────────────────────────────────────────────────────────────────
# date.today() is the server's system clock, not Central — on a UTC host it flips to
# "tomorrow" as early as 7pm Central, hours before it's actually tomorrow for anyone
# watching a game. Every "today" in this app needs to mean Central-today specifically.
_today = datetime.now(CENTRAL).date()
default_year, default_week = model.resolve_current_week(get_calendar_cached(_today.year), _today.year, _today)

with st.sidebar:
    st.markdown("# 🏈 CFB MODEL")
    st.markdown("---")
    st.markdown("### 📅 Season")
    year = st.number_input("Year", min_value=2000, max_value=2030, value=default_year, step=1)
    postseason = st.checkbox("📬 Postseason / Bowl Games", value=False,
                             help="Fetches every bowl & CFP game for the selected year, ignoring week. "
                                  "CFBD groups all of them under one 'week', so the week selector doesn't apply here.")
    # A dropdown beats a drag-slider for picking one of 15 discrete values on a touchscreen —
    # a slider needs a precise drag gesture, a dropdown just needs a tap.
    week = st.selectbox(
        "Week", options=list(range(1, 16)), index=default_week - 1,
        format_func=lambda w: f"Week {w}", disabled=postseason,
    )

    week0_filter = "All"
    if week == 1 and not postseason:
        week0_filter = st.radio(
            "Week 1 slate", ["All", "Week 0 only", "Week 1 only"], horizontal=True,
            help="CFBD lumps the early season-opening games (what fans call 'Week 0') and the "
                 "Labor Day weekend slate together under one 'week 1' — there's no such split in "
                 "their data. This filters by actual game date instead (cutoff: the Thursday "
                 "before Labor Day).",
        )

    today_only = st.checkbox("📅 Today's games only", value=False,
                             help="Filter to just games kicking off today (in CT, matching the "
                                  "kickoff times shown on each card).")

    # Both only depend on `year`, fetched here (not in the main fetch block below, which
    # doesn't run until after the sidebar) so these controls have real options on first
    # render. Caught broadly and degraded to "no options" rather than crashing the sidebar —
    # e.g. if cfbd isn't installed yet, that's reported by the friendlier check further down.
    try:
        _sidebar_team_names = sorted(get_team_logos(year).keys())
        _sidebar_conferences = sorted(set(get_team_conferences(year).values()))
    except Exception as e:
        print(f"Warning: failed to load team/conference options for sidebar: {e}")
        _sidebar_team_names, _sidebar_conferences = [], []

    st.markdown("### ⭐ Your Team")
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
        "Favorite Team", options=favorite_options, index=favorite_options.index(default_favorite),
        help="Highlights this team's game wherever it shows up in the current slate. Saved in "
             "the page's URL — reloading or revisiting that URL (e.g. from a bookmark) remembers it.",
    )
    if favorite_team == NO_FAVORITE:
        favorite_team = None
        st.query_params.pop("favorite_team", None)
    else:
        st.query_params["favorite_team"] = favorite_team

    selected_conferences = st.multiselect(
        "🏟️ Conferences", options=_sidebar_conferences, default=_sidebar_conferences,
        help="Only show games involving at least one team from these conferences. "
             "Leave everything selected to show every conference.",
    )

    # Home Field Advantage is a rarely-touched tuning knob, not a day-to-day nav control —
    # tucked away so the sidebar's main job (picking a slate) isn't cluttered by it.
    with st.expander("⚙️ Advanced"):
        home_field = st.number_input(
            "Home Field Advantage (pts)",
            min_value=0.0, max_value=10.0, value=model.DEFAULT_HOME_FIELD, step=0.5,
            help="Applied only to true home games. Neutral-site games (most bowls, CFP quarterfinals/"
                 "semifinals/championship) automatically get 0 — detected per-game from CFBD, not guessed "
                 "from the postseason toggle. CFP first-round games are true home games for the higher seed, "
                 "so they still get this value.",
        )

    st.markdown("---")
    st.markdown(
        f'<div class="fetch-caption">📡 Fetching <b>{year} · '
        f'{"Postseason" if postseason else f"Week {week}"}</b> · consensus lines'
        f'<br/>Results update automatically as you change these settings. '
        f'Ratings/lines are cached up to 1 hour.</div>',
        unsafe_allow_html=True,
    )

# Resolve API params from sidebar state
season_type = "postseason" if postseason else "regular"
api_week    = None if postseason else week


# ── header ────────────────────────────────────────────────────────────────────
season_label = "POSTSEASON" if postseason else f"WK {week}"
if week0_filter != "All":
    season_label += f" · {week0_filter}"
if today_only:
    season_label += " · Today Only"
st.markdown(f"# CFB — {year} · {season_label}")
st.markdown("SP+ ratings vs. consensus market spreads · Edge-based ATS picks")
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

# ── Summary metrics ───────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Games",    len(df))
c2.metric("Strong Picks",   len(strong))
c3.metric("Tier A Picks",   len(df[df["tier"] == "A"]))
c4.metric("Avg Cover Prob", f"{df['cover_prob'].mean():.3f}")

# ── Slate confidence breakdown ──────────────────────────────────────────────────
st.markdown("##### 🎯 This Slate's Confidence")
tier_order = ["A", "B", "C", "Pass"]
tier_counts = df["tier"].value_counts()
tier_bar_segs = "".join(
    f'<div class="tier-bar-seg" style="flex:{tier_counts.get(t, 0)};background:{TIER_COLORS[t]};"></div>'
    for t in tier_order
)
tier_bar_legend = "".join(
    f'<span><b style="color:{TIER_COLORS[t]}">{tier_counts.get(t, 0)}</b> '
    f'{"Tier " + t if t != "Pass" else "Pass"}</span>'
    for t in tier_order
)
st.markdown(
    f'<div class="tier-bar">{tier_bar_segs}</div>'
    f'<div class="tier-bar-legend">{tier_bar_legend}</div>',
    unsafe_allow_html=True,
)
st.caption("Share of this slate's games in each tier — more green (Tier A) means more strong plays. "
           "See the Pick'em tab for the ranked list.")
st.markdown("---")


# ── Logo helper ───────────────────────────────────────────────────────────────
def logo_img(team, size=32):
    """
    Render a team logo (or initials fallback) inside a light circular chip, ringed
    with the team's real brand color when known. The chip guarantees contrast
    regardless of app theme or how dark/transparent a given team's logo artwork is —
    some logos are otherwise invisible on a dark background. The color ring is purely
    decorative team identity (dynamic branding) — it never carries meaning on its own,
    so a missing color just falls back to the neutral border, not a broken chip.
    """
    url = logos.get(team, "")
    if url:
        inner = f'<img src="{url}" width="{size}" height="{size}" style="object-fit:contain;" />'
    else:
        initials = "".join(w[0] for w in team.split()[:2]).upper()
        inner = f'<span style="font-family:\'Bebas Neue\',sans-serif;font-size:{size // 2}px;color:#0d0f14;">{initials}</span>'
    pad = max(2, size // 8)
    chip_size = size + pad * 2
    ring_color = team_colors.get(team, "")
    border = f'border: 2px solid {ring_color};' if ring_color else ""
    return f'<span class="logo-chip" style="width:{chip_size}px;height:{chip_size}px;{border}">{inner}</span>'


def fav_star(team: str) -> str:
    """A small marker for the sidebar's favorite team, prefixed the same way rank_badge()
    prefixes AP/Coaches rank — so it's visible in any listing without a dedicated card."""
    return "⭐ " if favorite_team and team == favorite_team else ""


# ── Favorite team highlight ──────────────────────────────────────────────────────
if favorite_team:
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
        if neutral_site is None:
            site_str = ""
        elif neutral_site:
            site_str = f"🏟 {venue}" if venue else "🏟 Neutral Site"
        else:
            site_str = f"🏠 {venue}" if venue else "🏠 Home Game"

        st.markdown(
            f'<div class="pickem-card tier-{tier}" style="max-width:420px;">'
            f'<div class="pickem-card-top">'
            f'<div class="pickem-rank">⭐ Your Team</div>'
            f'<div class="pickem-tier-badge tier-{tier}">TIER {tier}</div>'
            f'</div>'
            f'<div class="pickem-logos">{logo_img(away, 32)}<span class="pickem-vs">@</span>{logo_img(home, 32)}</div>'
            f'<div class="pickem-matchup">{fav_star(away)}{model.rank_badge(away, rankings_data)}{away} @ '
            f'{fav_star(home)}{model.rank_badge(home, rankings_data)}{home}</div>'
            f'<div class="pickem-hero">'
            f'<span class="pickem-cover-prob" style="color:{tier_color};">{cover:.0%}</span>'
            f'</div>'
            f'<div class="pickem-confidence-bar">'
            f'<div class="pickem-confidence-fill" style="width:{cover * 100:.0f}%;background:{tier_color};"></div>'
            f'</div>'
            f'<div class="pickem-pick">&#10003; Pick: <b>{model.rank_badge(pick_team, rankings_data)}{pick_team}</b></div>'
            f'<div class="pickem-meta">'
            f'Edge: <b>{edge:+.1f} pts</b> &nbsp;|&nbsp; Spread: {spread:+.1f}'
            f'{"<br/>" + site_str if site_str else ""}'
            f'{"<br/>🗓 " + game_date if game_date else ""}'
            f'</div></div>',
            unsafe_allow_html=True,
        )
    st.markdown("---")


# ── Shared context passed to every tabs/*.py render(ctx) ──────────────────────
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
)


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab0, tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📅  Today's Games",
    "🏆  CBS Pick'em Top 12",
    "🎰  Team Parlays",
    "💰  Moneylines & O/U",
    "🥇  Rankings & ATS",
    "📊  Model Accuracy",
    "📈  Stats",
])

with tab0:
    today.render(ctx)

with tab1:
    pickem.render(ctx)

with tab2:
    parlays.render(ctx)

with tab3:
    markets.render(ctx)

with tab4:
    rankings.render(ctx)

with tab5:
    accuracy.render(ctx)

with tab6:
    stats.render(ctx)
