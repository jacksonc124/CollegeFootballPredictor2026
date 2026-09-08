import itertools
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd

import backtest
import model
import pick_log

EASTERN = ZoneInfo("America/New_York")

# Single source of truth for the app's color language (60-30-10 discipline): tier colors
# mean ONE thing — pick confidence — and appear nowhere else. ACCENT is the neutral color
# for UI chrome (buttons, headline numbers that aren't a tier signal) so it never competes
# with tier meaning. These are duplicated into the <style> block below (Vega-Lite charts
# and pandas Styler can't read CSS custom properties, so a single templated source isn't
# practical) — keep both in sync if changing.
TIER_COLORS = {"A": "#22c55e", "B": "#facc15", "C": "#fb923c", "Pass": "#6b7280"}
ACCENT = "#38bdf8"


def format_game_date(iso_start_date, start_time_tbd) -> str:
    """Format a UTC ISO start_date (from get_game_info) as an ET date, with time unless TBD."""
    if not iso_start_date:
        return ""
    try:
        dt_et = datetime.fromisoformat(iso_start_date).astimezone(EASTERN)
    except ValueError:
        return ""
    date_part = dt_et.strftime("%b %d")
    if start_time_tbd:
        return date_part
    time_part = dt_et.strftime("%I:%M %p").lstrip("0")
    return f"{date_part}, {time_part} ET"


# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="CFB Gambling Model", page_icon="🏈", layout="wide")

# ── styling ───────────────────────────────────────────────────────────────────
# Color discipline (60-30-10): 60% neutral background/structure, 30% text/border
# structure, 10% color — and that 10% is reserved almost entirely for TIER color (the
# one signal that matters: pick confidence). ACCENT (blue) is the only other color,
# used for UI chrome that isn't a tier signal (buttons, headline stat numbers), so it
# never gets confused with "this is a strong pick." Keep these literal hexes in sync
# with TIER_COLORS/ACCENT above — Vega-Lite charts and pandas Styler can't read CSS
# custom properties, so a single templated source isn't practical here.
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=IBM+Plex+Mono:wght@400;600&display=swap');

    html, body, [class*="css"] { font-family: 'IBM Plex Mono', monospace; }
    h1, h2, h3 { font-family: 'Bebas Neue', sans-serif; letter-spacing: 2px; }

    .stTabs [data-baseweb="tab"] {
        font-family: 'Bebas Neue', sans-serif; font-size: 16px;
        letter-spacing: 1px; border-radius: 6px; padding: 8px 20px;
    }

    div.stButton > button[kind="primary"] {
        background: #38bdf8; color: #0d0f14;
        font-family: 'Bebas Neue', sans-serif; font-size: 18px;
        letter-spacing: 2px; border: none; border-radius: 6px;
        padding: 10px 32px; width: 100%; transition: background 0.2s;
    }
    div.stButton > button[kind="primary"]:hover { background: #0ea5e9; color: #fff; }

    .pickem-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
        gap: 14px; margin-top: 12px;
    }
    .pickem-card {
        background: var(--background-color);
        border: 1px solid var(--border-color);
        border-radius: 10px; padding: 14px 16px;
        display: flex; flex-direction: column; gap: 6px;
    }
    .pickem-card.tier-A { border-left: 4px solid #22c55e; }
    .pickem-card.tier-B { border-left: 4px solid #facc15; }
    .pickem-card.tier-C { border-left: 4px solid #fb923c; }
    .pickem-card-top { display: flex; align-items: baseline; justify-content: space-between; }
    .pickem-rank { font-family: 'Bebas Neue', sans-serif; font-size: 24px; line-height: 1; opacity: 0.4; }
    .pickem-tier-badge {
        font-family: 'Bebas Neue', sans-serif; font-size: 13px; letter-spacing: 1px;
        padding: 2px 9px; border-radius: 4px; color: #0d0f14;
    }
    .pickem-tier-badge.tier-A { background: #22c55e; }
    .pickem-tier-badge.tier-B { background: #facc15; }
    .pickem-tier-badge.tier-C { background: #fb923c; }
    /* The Pick'em tab never shows Pass-tier cards (filtered out upstream), but the Today
       tab shows every game including Pass, so this badge needs its own readable style. */
    .pickem-tier-badge.tier-Pass { background: #6b7280; color: #f3f4f6; }
    .pickem-matchup { font-size: 13px; opacity: 0.65; }
    /* The hero number — this is this app's "score," so it gets the boldest, biggest
       treatment on the card, matching how scores/timers read in a sports app. */
    .pickem-hero { display: flex; align-items: baseline; gap: 10px; margin: 2px 0; }
    .pickem-cover-prob {
        font-family: 'Bebas Neue', sans-serif; font-size: 40px; line-height: 1;
    }
    .pickem-pick { font-size: 13px; opacity: 0.85; }
    .pickem-pick b { font-size: 14px; }
    .pickem-confidence-bar {
        background: rgba(128,128,128,0.15); border-radius: 3px; height: 5px; width: 100%;
        margin: 2px 0 4px;
    }
    .pickem-confidence-fill { border-radius: 3px; height: 5px; }
    .pickem-meta { font-size: 11px; opacity: 0.55; line-height: 1.6; }
    .pickem-logos { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
    .pickem-vs { font-size: 11px; opacity: 0.4; }

    .parlay-card {
        background: var(--background-color);
        border: 1px solid #38bdf844;
        border-radius: 10px; padding: 16px 20px; margin-bottom: 14px;
    }
    .parlay-title {
        font-family: 'Bebas Neue', sans-serif; font-size: 22px;
        color: #38bdf8; letter-spacing: 1px; margin-bottom: 8px;
    }
    .parlay-leg { font-size: 13px; padding: 4px 0; border-bottom: 1px solid rgba(128,128,128,0.15); }
    .parlay-leg:last-child { border-bottom: none; }
    .parlay-prob { font-family: 'Bebas Neue', sans-serif; font-size: 18px; color: #38bdf8; margin-top: 10px; }

    .leg-display { font-family: 'Bebas Neue', sans-serif; font-size: 52px; color: #38bdf8; line-height: 1; text-align: center; }
    .leg-label { font-size: 11px; opacity: 0.5; letter-spacing: 1px; text-align: center; margin-top: 2px; }

    .futures-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
        gap: 12px; margin-top: 12px;
    }
    .futures-card {
        background: var(--background-color);
        border: 1px solid var(--border-color);
        border-radius: 10px; padding: 16px;
        display: flex; flex-direction: column; gap: 6px;
    }
    .futures-card.rank-1 { border-left: 4px solid #f59e0b; }
    .futures-card.rank-2 { border-left: 4px solid #94a3b8; }
    .futures-card.rank-3 { border-left: 4px solid #b45309; }
    .futures-card.rank-other { border-left: 4px solid rgba(128,128,128,0.2); }
    .futures-rank { font-family: 'Bebas Neue', sans-serif; font-size: 26px; line-height: 1; opacity: 0.4; }
    .futures-name { font-family: 'Bebas Neue', sans-serif; font-size: 20px; letter-spacing: 1px; }
    .futures-score { font-family: 'Bebas Neue', sans-serif; font-size: 22px; color: #38bdf8; }
    .futures-label { font-size: 11px; opacity: 0.5; }
    .bar-bg { margin-top: 6px; background: rgba(128,128,128,0.15); border-radius: 4px; height: 4px; width: 100%; }
    .bar-fill { border-radius: 4px; height: 4px; }

    /* Slate confidence breakdown — a single proportional bar (segment width = share of
       games in that tier) reads at a glance; the scatter chart it replaced required
       parsing two abstract axes to get the same information. */
    .tier-bar { display: flex; height: 16px; border-radius: 8px; overflow: hidden; margin-top: 6px; }
    .tier-bar-seg { height: 100%; transition: flex-grow 0.2s; }
    .tier-bar-legend {
        font-size: 13px; opacity: 0.8; margin-top: 10px;
        display: flex; gap: 18px; flex-wrap: wrap;
    }
    .tier-bar-legend b { font-family: 'Bebas Neue', sans-serif; letter-spacing: 0.5px; }

    .today-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
        gap: 14px; margin-top: 12px;
    }
    .today-card {
        background: var(--background-color);
        border: 1px solid var(--border-color);
        border-radius: 10px; padding: 14px 16px;
        display: flex; flex-direction: column; gap: 6px;
    }
    .today-card.tier-A { border-left: 4px solid #22c55e; }
    .today-card.tier-B { border-left: 4px solid #facc15; }
    .today-card.tier-C { border-left: 4px solid #fb923c; }
    .today-card-top { display: flex; align-items: baseline; justify-content: space-between; }
    .today-kickoff { font-size: 12px; opacity: 0.6; }
    .today-stats {
        display: grid; grid-template-columns: repeat(2, 1fr);
        gap: 0 12px; margin-top: 8px; font-size: 12px;
    }
    .today-stats > div {
        display: flex; justify-content: space-between;
        border-bottom: 1px solid rgba(128,128,128,0.12); padding: 4px 0;
    }
    .today-stat-label { opacity: 0.6; }
    .today-stat-value { font-weight: 600; }

    /* Moneyline / O-U cards — same shape as Pick'em/Today cards, but these picks have no
       tier (no A/B/C confidence bucket), so the hero number is plain ACCENT rather than a
       tier color, and there's no colored border-left. */
    .market-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
        gap: 14px; margin-top: 12px;
    }
    .market-card {
        background: var(--background-color);
        border: 1px solid var(--border-color);
        border-radius: 10px; padding: 14px 16px;
        display: flex; flex-direction: column; gap: 6px;
    }
    .market-hero { font-family: 'Bebas Neue', sans-serif; font-size: 36px; color: #38bdf8; line-height: 1; margin-top: 2px; }
    .market-hero-label { font-size: 11px; opacity: 0.55; letter-spacing: 0.5px; }
    .market-pick { font-size: 13px; opacity: 0.85; margin-top: 2px; }
    .market-pick b { font-size: 14px; }
    .neutral-badge { font-size: 11px; opacity: 0.7; margin-top: -2px; }

    /* Light chip behind every team logo so dark/transparent PNG artwork stays visible
       regardless of the app's light/dark theme. The colored ring (set inline per-logo,
       since it's each team's own brand color) adds a subtle bit of team identity without
       touching text contrast — decorative only, never load-bearing for readability. */
    .logo-chip {
        display: inline-flex; align-items: center; justify-content: center;
        background: rgba(255,255,255,0.94);
        border: 2px solid rgba(0,0,0,0.08);
        border-radius: 50%;
        flex-shrink: 0;
    }

    .fetch-caption { font-size: 12px; opacity: 0.6; margin-top: 4px; }

    /* Streamlit stacks st.columns() vertically below ~640px by default, which turns the
       −/legs/+ stepper into three separate full-width rows on mobile. Force just this row
       to stay horizontal so it remains a compact stepper instead of eating vertical space. */
    [data-testid="stHorizontalBlock"]:has(.leg-display) {
        flex-direction: row !important;
    }
    [data-testid="stHorizontalBlock"]:has(.leg-display) > div {
        width: auto !important;
        flex: 1 1 0 !important;
        min-width: 0 !important;
    }
</style>
""", unsafe_allow_html=True)


# ── display column names (raw model.py columns → friendly UI headers) ─────────
DISPLAY_COLUMNS = {
    "home_team": "Home", "away_team": "Away", "provider": "Provider",
    "sp_home_rating": "SP+ Home", "sp_away_rating": "SP+ Away",
    "model_spread_home": "Model Spread", "market_spread_home": "Market Spread",
    "edge_points": "Edge (pts)", "cover_prob": "Cover Prob", "tier": "Tier",
    "model_pick": "Pick", "neutral_site": "Neutral Site", "game_notes": "Game",
    "start_date": "Date", "venue": "Venue",
    "best_spread_value": "Best Spread", "best_spread_provider": "Best Spread Book",
    "best_ml_value": "Best ML", "best_ml_provider": "Best ML Book",
}


def tier_row_css(tier: str) -> str:
    """Full-row background tint for a tier value, shared by every dataframe Styler that has
    a Tier column — one definition so 'what a tinted row means' stays consistent app-wide."""
    color = TIER_COLORS.get(tier, "")
    return f"background-color: {color}22" if color and tier != "Pass" else ""


# Win/loss is a different axis of meaning than tier confidence (a graded result, not a
# pick's confidence), so it gets its own green/red rather than reusing TIER_COLORS —
# they never appear in the same table, so there's no risk of the two meanings colliding.
OUTCOME_COLORS = {"win": "#22c55e", "loss": "#ef4444"}


def outcome_row_css(outcome: str) -> str:
    """Full-row background tint for a graded pick's outcome (win/loss); push/pending get no tint."""
    color = OUTCOME_COLORS.get(outcome, "")
    return f"background-color: {color}22" if color else ""


# ── session state ─────────────────────────────────────────────────────────────
if "parlay_legs" not in st.session_state:
    st.session_state["parlay_legs"] = 3

# ── secrets ───────────────────────────────────────────────────────────────────
try:
    bearer_token = st.secrets["BEARER_TOKEN"]
except Exception:
    bearer_token = os.environ.get("BEARER_TOKEN", "")


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
# date.today() is the server's system clock, not Eastern — on a UTC host it flips to
# "tomorrow" as early as 8pm Eastern, hours before it's actually tomorrow for anyone
# watching a game. Every "today" in this app needs to mean Eastern-today specifically.
_today = datetime.now(EASTERN).date()
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
                             help="Filter to just games kicking off today (in ET, matching the "
                                  "kickoff times shown on each card).")

    # Both only depend on `year`, fetched here (not in the main fetch block below, which
    # doesn't run until after the sidebar) so these controls have real options on first
    # render. Caught broadly and degraded to "no options" rather than crashing the sidebar —
    # e.g. if cfbd isn't installed yet, that's reported by the friendlier check further down.
    try:
        _sidebar_team_names = sorted(get_team_logos(year).keys())
        _sidebar_conferences = sorted(set(get_team_conferences(year).values()))
    except Exception:
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


# ── Fetch ─────────────────────────────────────────────────────────────────────
with st.spinner("Fetching ratings, lines, and logos…"):
    try:
        ratings          = get_sp_ratings(year)
        games            = get_weekly_lines(year, api_week, season_type)
        game_info        = get_game_info(year, api_week, season_type)
        scoring_stats    = get_scoring_stats(year)
        rankings         = get_rankings(year, api_week, season_type)
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
    is_today = df["start_date"].apply(lambda d: model.is_game_on_date(d, _today, EASTERN))
    df = df[is_today].reset_index(drop=True)
    if df.empty:
        st.warning("No games today for this slate. Try turning off 'Today's games only'.")
        st.stop()

# Snapshot for the "Today's Games" landing tab — computed on raw (pre-format) start_date,
# independent of the "Today's games only" sidebar checkbox, so that tab always reflects
# literally today regardless of whether the user has that filter on.
today_df = df[df["start_date"].apply(lambda d: model.is_game_on_date(d, _today, EASTERN))].copy()
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
            f'<div class="pickem-matchup">{fav_star(away)}{model.rank_badge(away, rankings)}{away} @ '
            f'{fav_star(home)}{model.rank_badge(home, rankings)}{home}</div>'
            f'<div class="pickem-hero">'
            f'<span class="pickem-cover-prob" style="color:{tier_color};">{cover:.0%}</span>'
            f'</div>'
            f'<div class="pickem-confidence-bar">'
            f'<div class="pickem-confidence-fill" style="width:{cover * 100:.0f}%;background:{tier_color};"></div>'
            f'</div>'
            f'<div class="pickem-pick">&#10003; Pick: <b>{model.rank_badge(pick_team, rankings)}{pick_team}</b></div>'
            f'<div class="pickem-meta">'
            f'Edge: <b>{edge:+.1f} pts</b> &nbsp;|&nbsp; Spread: {spread:+.1f}'
            f'{"<br/>" + site_str if site_str else ""}'
            f'{"<br/>🗓 " + game_date if game_date else ""}'
            f'</div></div>',
            unsafe_allow_html=True,
        )
    st.markdown("---")


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


# ── TAB 0: Today's Games ─────────────────────────────────────────────────────
with tab0:
    st.markdown(f"## 📅 Today's Games — {_today.strftime('%A, %B %d')}")
    st.caption("Everything kicking off today, spread/moneylines/O-U side by side · "
               "full detail (parlays, rankings, accuracy) lives in the other tabs.")

    if today_df.empty:
        st.info("No games today in the slate currently selected in the sidebar. "
                "Adjust Year/Week there to jump to a different day.")
    else:
        has_ml = "home_moneyline" in today_df.columns
        has_total = "market_total" in today_df.columns

        today_cards_html = '<div class="today-grid">'
        for _, row in today_df.iterrows():
            tier, home, away = row["tier"], row["home_team"], row["away_team"]
            pick_team, cover  = row["pick_team"], row["cover_prob"]
            spread            = row["market_spread_home"]
            tier_color        = TIER_COLORS.get(tier, ACCENT)

            stats_html = (
                f'<div><span class="today-stat-label">Spread</span>'
                f'<span class="today-stat-value">{spread:+.1f}</span></div>'
                if spread is not None else ""
            )
            if has_ml and pd.notna(row.get("home_moneyline")):
                stats_html += (
                    f'<div><span class="today-stat-label">Home ML</span>'
                    f'<span class="today-stat-value">{row["home_moneyline"]:+.0f}</span></div>'
                    f'<div><span class="today-stat-label">Away ML</span>'
                    f'<span class="today-stat-value">{row["away_moneyline"]:+.0f}</span></div>'
                )
            if has_total and pd.notna(row.get("market_total")):
                stats_html += (
                    f'<div><span class="today-stat-label">O/U Line</span>'
                    f'<span class="today-stat-value">{row["market_total"]:.1f}</span></div>'
                )
                if pd.notna(row.get("total_pick")) and row["total_pick"]:
                    stats_html += (
                        f'<div><span class="today-stat-label">Total Pick</span>'
                        f'<span class="today-stat-value">{row["total_pick"]}</span></div>'
                    )

            today_cards_html += (
                f'<div class="today-card tier-{tier}">'
                f'<div class="today-card-top">'
                f'<div class="today-kickoff">🗓 {row["start_date"]}</div>'
                f'<div class="pickem-tier-badge tier-{tier}">TIER {tier}</div>'
                f'</div>'
                f'<div class="pickem-logos">{logo_img(away, 32)}<span class="pickem-vs">@</span>{logo_img(home, 32)}</div>'
                f'<div class="pickem-matchup">{fav_star(away)}{model.rank_badge(away, rankings)}{away} @ '
                f'{fav_star(home)}{model.rank_badge(home, rankings)}{home}</div>'
                f'<div class="pickem-hero">'
                f'<span class="pickem-cover-prob" style="color:{tier_color};">{cover:.0%}</span>'
                f'</div>'
                f'<div class="pickem-confidence-bar">'
                f'<div class="pickem-confidence-fill" style="width:{cover * 100:.0f}%;background:{tier_color};"></div>'
                f'</div>'
                f'<div class="pickem-pick">&#10003; ATS Pick: <b>{model.rank_badge(pick_team, rankings)}{pick_team}</b></div>'
                f'<div class="today-stats">{stats_html}</div>'
                f'</div>'
            )
        today_cards_html += "</div>"
        st.markdown(today_cards_html, unsafe_allow_html=True)
        st.caption(f"{len(today_df)} game(s) today · sorted as returned by the lines provider — "
                   "see the Pick'em tab for a ranked top 12.")


# ── TAB 1: CBS Pick'em ────────────────────────────────────────────────────────
with tab1:
    st.markdown("## 🏆 CBS Pick'em — Top 12 ATS Picks")
    st.caption("Ranked by cover probability · Against the spread")

    log_col, btn_col = st.columns([4, 1])
    with log_col:
        if pick_log.already_logged(year, api_week, season_type):
            reason = "auto-logged (this is the current week)" if is_current_slate else "logged"
            st.caption(f"✅ This slate's picks are {reason} for unbiased accuracy tracking — "
                       "see the Model Accuracy tab.")
        elif is_current_slate:
            st.caption("📌 Auto-logging this slate now (current week) for a genuinely unbiased "
                       "accuracy record — see the Model Accuracy tab.")
        else:
            st.caption("📌 This isn't the current week, so it won't auto-log — use the button to log it "
                       "manually if you want it tracked anyway. See the Model Accuracy tab.")
    with btn_col:
        if not pick_log.already_logged(year, api_week, season_type):
            if st.button("📌 Log Picks", key="log_picks_btn", use_container_width=True, type="primary"):
                pick_log.log_picks(df, year, api_week, season_type)
                st.rerun()
    st.markdown("---")

    top12 = (df[df["tier"] != "Pass"]
             .sort_values("cover_prob", ascending=False)
             .head(12).reset_index(drop=True))

    if top12.empty:
        st.info("Not enough picks above Pass tier for a top 12.")
    else:
        cards_html = '<div class="pickem-grid">'
        for i, row in top12.iterrows():
            tier, home, away       = row["tier"], row["home_team"], row["away_team"]
            pick_team, cover, edge = row["pick_team"], row["cover_prob"], row["edge_points"]
            spread                 = row["market_spread_home"]
            neutral_site, notes    = row.get("neutral_site"), row.get("game_notes") or ""
            game_date               = row.get("start_date") or ""
            venue                   = row.get("venue") or ""
            spread_str = f"Spread: {spread:+.1f}" if spread is not None else ""
            if neutral_site is None:
                site_str = ""
            elif neutral_site:
                site_str = f"🏟 {venue}" if venue else "🏟 Neutral Site"
            else:
                site_str = f"🏠 {venue}" if venue else "🏠 Home Game"
            date_str = f"🗓 {game_date}" if game_date else ""
            note_str = f"<br/>{notes}" if notes else ""
            # Line shopping: only worth a line when some other book actually beats the
            # number already shown above (a tie or worse isn't "extra value").
            best_str = ""
            best_spread = row.get("best_spread_value")
            if pd.notna(best_spread) and spread is not None:
                shown_side_spread = spread if pick_team == home else -spread
                if best_spread > shown_side_spread:
                    best_str = f"🛒 Best: {best_spread:+.1f} @ {row['best_spread_provider']}"
            tier_color = TIER_COLORS.get(tier, ACCENT)
            cards_html += (
                f'<div class="pickem-card tier-{tier}">'
                f'<div class="pickem-card-top">'
                f'<div class="pickem-rank">#{i + 1}</div>'
                f'<div class="pickem-tier-badge tier-{tier}">TIER {tier}</div>'
                f'</div>'
                f'<div class="pickem-logos">{logo_img(away, 32)}<span class="pickem-vs">@</span>{logo_img(home, 32)}</div>'
                f'<div class="pickem-matchup">{fav_star(away)}{model.rank_badge(away, rankings)}{away} @ '
                f'{fav_star(home)}{model.rank_badge(home, rankings)}{home}</div>'
                f'<div class="pickem-hero">'
                f'<span class="pickem-cover-prob" style="color:{tier_color};">{cover:.0%}</span>'
                f'</div>'
                f'<div class="pickem-confidence-bar">'
                f'<div class="pickem-confidence-fill" style="width:{cover * 100:.0f}%;background:{tier_color};"></div>'
                f'</div>'
                f'<div class="pickem-pick">&#10003; Pick: <b>{model.rank_badge(pick_team, rankings)}{pick_team}</b></div>'
                f'<div class="pickem-meta">'
                f'Edge: <b>{edge:+.1f} pts</b>'
                f'{"<br/>" + spread_str if spread_str else ""}'
                f'{"<br/>" + best_str if best_str else ""}'
                f'{"<br/>" + site_str if site_str else ""}'
                f'{"<br/>" + date_str if date_str else ""}'
                f'{note_str}'
                f'</div></div>'
            )
        cards_html += "</div>"
        st.markdown(cards_html, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("## 📋 All Games")
    tier_filter = st.multiselect("Filter by Tier", ["A","B","C","Pass"], default=["A","B","C","Pass"], key="tf1")
    filtered = df[df["tier"].isin(tier_filter)] if tier_filter else df

    # Subtle full-row tint (not just the Tier cell) so the strongest picks are scannable
    # at a glance without reading every row — same tier colors as everywhere else in the app.
    def _shade_row(row):
        return [tier_row_css(row["Tier"])] * len(row)

    table_df = (
        filtered.drop(columns=["pick_team"]).rename(columns=DISPLAY_COLUMNS)
                .sort_values("Edge (pts)", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
    )
    # ATS lookups use the clean team name, so compute them before the rank-badge prefix is added.
    table_df["Home ATS"] = table_df["Home"].map(lambda t: model.ats_record_str(t, ats_records))
    table_df["Away ATS"] = table_df["Away"].map(lambda t: model.ats_record_str(t, ats_records))
    table_df["Home"] = table_df["Home"].map(lambda t: f"{fav_star(t)}{model.rank_badge(t, rankings)}{t}")
    table_df["Away"] = table_df["Away"].map(lambda t: f"{fav_star(t)}{model.rank_badge(t, rankings)}{t}")
    st.dataframe(
        table_df.style.apply(_shade_row, axis=1),
        use_container_width=True, height=min(50 + 35 * len(filtered), 600),
        column_config={
            "Cover Prob": st.column_config.ProgressColumn("Cover Prob", min_value=0.0, max_value=1.0),
            "Edge (pts)": st.column_config.NumberColumn("Edge (pts)", format="%+.1f"),
            "Model Spread": st.column_config.NumberColumn("Model Spread", format="%+.1f"),
            "Market Spread": st.column_config.NumberColumn("Market Spread", format="%+.1f"),
            "SP+ Home": st.column_config.NumberColumn("SP+ Home", format="%+.1f"),
            "SP+ Away": st.column_config.NumberColumn("SP+ Away", format="%+.1f"),
            "Neutral Site": st.column_config.CheckboxColumn("Neutral Site"),
            "Best Spread": st.column_config.NumberColumn("Best Spread", format="%+.1f",
                                                           help="Best available spread across every book CFBD returned "
                                                                "for whichever side the model picked ATS."),
            "Best ML": st.column_config.NumberColumn("Best ML", format="%+.0f",
                                                       help="Best available moneyline price across every book CFBD "
                                                            "returned for whichever side the model picked straight-up."),
        },
    )
    st.markdown("---")
    dl1, dl2 = st.columns(2)
    with dl1:
        fname = f"all_games_{year}_postseason" if postseason else f"all_games_{year}_wk{week}"
        st.download_button("⬇️ All Games (CSV)",
                           data=df.drop(columns=["pick_team"]).rename(columns=DISPLAY_COLUMNS).to_csv(index=False),
                           file_name=f"{fname}.csv", mime="text/csv")
    with dl2:
        if not strong.empty:
            fname2 = f"strong_picks_{year}_postseason" if postseason else f"strong_picks_{year}_wk{week}"
            st.download_button("⬇️ Strong Picks (CSV)",
                               data=strong.drop(columns=["pick_team"]).rename(columns=DISPLAY_COLUMNS).to_csv(index=False),
                               file_name=f"{fname2}.csv", mime="text/csv")


# ── TAB 2: Parlays ────────────────────────────────────────────────────────────
def build_parlay_leg_pool(df_inner: pd.DataFrame, ats_tiers=("A", "B"),
                           ml_edge_threshold: float = model.ML_EDGE_THRESHOLD) -> pd.DataFrame:
    """
    Unify ATS picks (from ats_tiers) and moneyline picks with edge >= ml_edge_threshold
    into one candidate-leg pool, so parlays can mix bet types. Each leg keeps its
    originating (home, away) game so combos can be filtered to one leg per game
    (see render_parlay_tab). Pass ats_tiers=() or ml_edge_threshold=inf to exclude a
    bet type entirely.
    """
    # leg_odds carries each leg's real American odds so parlay payout is computed from
    # actual odds per leg instead of assuming every leg is standard -110 juice — a heavy
    # moneyline favorite pays far less than -110 would imply (see model.american_to_decimal_odds).
    leg_cols = ["home_team", "away_team", "leg_type", "leg_team", "leg_prob", "leg_label", "leg_detail", "leg_odds"]

    ats_legs = df_inner[df_inner["tier"].isin(ats_tiers) & (df_inner["pick_team"] != "")].copy()
    ats_legs["leg_type"] = "ATS"
    ats_legs["leg_team"] = ats_legs["pick_team"]
    ats_legs["leg_prob"] = ats_legs["cover_prob"]
    ats_legs["leg_label"] = ats_legs["leg_team"] + " ATS"
    ats_legs["leg_detail"] = "Edge: " + ats_legs["edge_points"].map(lambda e: f"{e:+.1f} pts")
    ats_legs["leg_odds"] = -110  # standard assumed juice for spread/total bets

    pools = [ats_legs[leg_cols]]

    if "ml_pick_team" in df_inner.columns:
        ml_legs = df_inner[
            df_inner["ml_pick_team"].notna() & (df_inner["ml_pick_team"] != "")
            & (df_inner["ml_edge"] >= ml_edge_threshold)
        ].copy()
        if not ml_legs.empty:
            ml_legs["leg_type"] = "ML"
            ml_legs["leg_team"] = ml_legs["ml_pick_team"]
            ml_legs["leg_prob"] = ml_legs["ml_model_prob"]
            ml_legs["leg_label"] = ml_legs["leg_team"] + " ML"
            ml_legs["leg_detail"] = "Edge: " + ml_legs["ml_edge"].map(lambda e: f"{e:.1%}")
            ml_legs["leg_odds"] = ml_legs.apply(
                lambda r: r["home_moneyline"] if r["leg_team"] == r["home_team"] else r["away_moneyline"], axis=1
            )
            pools.append(ml_legs[leg_cols])

    return pd.concat(pools, ignore_index=True)


@st.fragment
def render_parlay_tab(df_inner):
    st.markdown("## 🎰 Team Parlays")
    st.caption("Combined prob = product of leg probabilities · Payout uses each leg's real odds "
               "(−110 assumed for ATS/O-U, actual moneyline for ML legs)")
    st.caption("⚠️ Each combo uses at most one leg per game (no stacking an ATS and moneyline pick on "
               "the same matchup), but legs from *different* games are still assumed independent — "
               "correlated results (e.g. conference-wide trends) aren't modeled.")

    def dec_legs():
        if st.session_state["parlay_legs"] > 2:
            st.session_state["parlay_legs"] -= 1

    def inc_legs():
        if st.session_state["parlay_legs"] < 6:
            st.session_state["parlay_legs"] += 1

    col_minus, col_display, col_plus = st.columns([1, 1, 1])
    with col_minus:
        st.button("−", key="legs_minus", on_click=dec_legs,
                  use_container_width=True, disabled=(st.session_state["parlay_legs"] <= 2))
    with col_display:
        st.markdown(
            f'<div class="leg-display">{st.session_state["parlay_legs"]}</div>'
            f'<div class="leg-label">LEGS</div>',
            unsafe_allow_html=True,
        )
    with col_plus:
        st.button("+", key="legs_plus", on_click=inc_legs,
                  use_container_width=True, disabled=(st.session_state["parlay_legs"] >= 6))

    with st.expander("⚙️ Customize"):
        cc1, cc2 = st.columns(2)
        with cc1:
            include_types = st.multiselect("Bet Types", ["ATS", "ML"], default=["ATS", "ML"],
                                            key="parlay_bet_types")
            ats_tiers = st.multiselect("ATS Tiers", ["A", "B", "C"], default=["A", "B"],
                                        help="Tier C picks have a smaller edge/lower cover probability — "
                                             "riskier legs than the default A/B.",
                                        key="parlay_ats_tiers")
        with cc2:
            ml_edge_pct = st.slider("Min Moneyline Edge", min_value=0, max_value=30,
                                     value=int(model.ML_EDGE_THRESHOLD * 100), step=1, format="%d%%",
                                     help="Model win probability minus the market's vig-removed "
                                          "implied probability. Lower = more moneyline legs qualify.",
                                     key="parlay_ml_edge_pct")
            min_payout = st.number_input("Minimum Payout", min_value=1.0, max_value=50.0, value=1.0, step=0.5,
                                          help="Hide any combo paying out less than this multiplier.",
                                          key="parlay_min_payout")

    leg_count = st.session_state["parlay_legs"]
    # Deliberately wider than just the safest legs — sorting by probability alone and
    # taking a small pool meant every parlay ended up all heavy-favorite moneylines,
    # since those have the highest individual probability by construction. A wider pool
    # keeps some higher-variance, higher-payout legs in the mix (see the two sections
    # below: "Safest" vs. "Higher Payout").
    pool_size = leg_count + 12

    leg_pool = build_parlay_leg_pool(df_inner, tuple(ats_tiers), ml_edge_pct / 100)
    if include_types:
        leg_pool = leg_pool[leg_pool["leg_type"].isin(include_types)]
    else:
        leg_pool = leg_pool.iloc[0:0]
    parlay_pool = leg_pool.sort_values("leg_prob", ascending=False).head(pool_size).reset_index(drop=True)

    if len(parlay_pool) < leg_count:
        st.info(f"Not enough qualifying picks for a {leg_count}-leg parlay with the current filters. "
                f"Try reducing legs, widening ATS Tiers, or lowering Min Moneyline Edge.")
        return

    probs = parlay_pool["leg_prob"].to_numpy()
    decimal_odds = parlay_pool["leg_odds"].map(model.american_to_decimal_odds).to_numpy()
    games = list(zip(parlay_pool["home_team"], parlay_pool["away_team"]))

    parlay_rows = []
    for c in itertools.combinations(range(len(parlay_pool)), leg_count):
        if len({games[i] for i in c}) != leg_count:
            continue  # one leg per game
        joint_prob = 1.0
        payout = 1.0
        for i in c:
            joint_prob *= probs[i]
            payout *= decimal_odds[i]
        if payout < min_payout:
            continue
        parlay_rows.append({"joint_prob": round(joint_prob, 4), "payout": round(payout, 2),
                             "legs": parlay_pool.iloc[list(c)]})

    if not parlay_rows:
        st.info(f"No {leg_count}-leg combos meet the current filters (try lowering Minimum Payout, "
                f"reducing legs, or widening ATS Tiers / Min Moneyline Edge).")
        return

    def render_parlay_cards(rows, title, subtitle):
        st.markdown(f"#### {title}")
        st.caption(subtitle)
        all_html = ""
        for i, p in enumerate(rows[:5]):
            legs_html = ""
            for _, leg in p["legs"].iterrows():
                legs_html += (
                    f'<div class="parlay-leg">'
                    f'{logo_img(leg["leg_team"], 20)}&nbsp;<b>{leg["leg_label"]}</b>'
                    f'&nbsp;<span style="opacity:0.5">({model.rank_badge(leg["away_team"], rankings)}{leg["away_team"]} @ '
                    f'{model.rank_badge(leg["home_team"], rankings)}{leg["home_team"]})</span>'
                    f'&nbsp;&middot;&nbsp;Prob: <b style="color:#38bdf8">{leg["leg_prob"]:.1%}</b>'
                    f'&nbsp;&middot;&nbsp;{leg["leg_detail"]}'
                    f'</div>'
                )
            all_html += (
                f'<div class="parlay-card">'
                f'<div class="parlay-title">Parlay #{i + 1}'
                f'&nbsp;<span style="font-size:14px;opacity:0.5;font-family:\'IBM Plex Mono\',monospace;">'
                f'{leg_count}-leg</span></div>'
                f'{legs_html}'
                f'<div class="parlay-prob">'
                f'Combined Probability: {p["joint_prob"]:.1%}'
                f'&nbsp;&middot;&nbsp;Est. Payout: ~{p["payout"]}x'
                f'</div></div>'
            )
        st.markdown(all_html, unsafe_allow_html=True)

    safest = sorted(parlay_rows, key=lambda x: x["joint_prob"], reverse=True)
    riskiest = sorted(parlay_rows, key=lambda x: x["payout"], reverse=True)

    render_parlay_cards(safest, "🛡️ Safest", "Highest combined probability")
    st.markdown("---")
    render_parlay_cards(riskiest, "🎲 Higher Payout", "Highest payout among the same qualifying picks — "
                                                       "lower probability, bigger swing if it hits")


with tab2:
    render_parlay_tab(df)


# ── TAB 3: Moneylines & O/U ────────────────────────────────────────────────────
with tab3:
    st.markdown("## 💰 Moneylines & Over/Under")
    st.caption("Moneyline edge = model win probability vs. the market's vig-removed implied probability.")
    st.info(
        "ℹ️ **Over/Under is a rough estimate, not a calibrated pick like the spread picks.** Base "
        "prediction blends each team's scoring average with their opponent's average points allowed, "
        "then adjusts for opponent-adjusted EPA/play (CFBD's adjustedMetrics) and weather (wind above "
        "15mph, precipitation, snow). The adjustments use real signal, but the conversion factors "
        "(EPA→points, wind→points) are disclosed heuristics, not empirically fit — see 'Opp Adj' and "
        "'Weather Adj' below for how much each moved the number, and treat the total as directional, "
        "not precise.",
        icon="ℹ️",
    )

    ml_df = df[df["ml_pick_team"].notna()].copy() if "ml_pick_team" in df.columns else pd.DataFrame()
    total_df = df[df["total_pick"].notna()].copy() if "total_pick" in df.columns else pd.DataFrame()

    st.markdown("#### Moneylines")
    if ml_df.empty:
        st.info("No moneylines available for this slate's lines provider.")
    else:
        ml_sorted = ml_df.sort_values("ml_edge", ascending=False).reset_index(drop=True)
        ml_cards_html = '<div class="market-grid">'
        for _, row in ml_sorted.iterrows():
            home, away = row["home_team"], row["away_team"]
            pick_team  = row["ml_pick_team"]
            neutral_html = '<div class="neutral-badge">⭐ Neutral Site</div>' if row.get("neutral_site") is True else ""
            ml_stats_html = (
                f'<div><span class="today-stat-label">Home ML</span><span class="today-stat-value">{row["home_moneyline"]:+.0f}</span></div>'
                f'<div><span class="today-stat-label">Away ML</span><span class="today-stat-value">{row["away_moneyline"]:+.0f}</span></div>'
                f'<div><span class="today-stat-label">Market Prob</span><span class="today-stat-value">{row["ml_market_prob"]:.1%}</span></div>'
                f'<div><span class="today-stat-label">Edge</span><span class="today-stat-value">{row["ml_edge"]:+.1%}</span></div>'
            )
            # Only worth surfacing when some other book actually beats the price already shown.
            best_ml = row.get("best_ml_value")
            if pd.notna(best_ml):
                shown_ml = row["home_moneyline"] if pick_team == home else row["away_moneyline"]
                if best_ml > shown_ml:
                    ml_stats_html += (
                        f'<div><span class="today-stat-label">🛒 Best ML</span>'
                        f'<span class="today-stat-value">{best_ml:+.0f} @ {row["best_ml_provider"]}</span></div>'
                    )
            ml_cards_html += (
                f'<div class="market-card">'
                f'<div class="pickem-logos">{logo_img(away, 28)}<span class="pickem-vs">@</span>{logo_img(home, 28)}</div>'
                f'<div class="pickem-matchup">{fav_star(away)}{model.rank_badge(away, rankings)}{away} @ '
                f'{fav_star(home)}{model.rank_badge(home, rankings)}{home}</div>'
                f'{neutral_html}'
                f'<div class="market-hero">{row["ml_model_prob"]:.0%}</div>'
                f'<div class="market-hero-label">MODEL WIN PROB</div>'
                f'<div class="market-pick">&#10003; ML Pick: <b>{model.rank_badge(pick_team, rankings)}{pick_team}</b></div>'
                f'<div class="today-stats">{ml_stats_html}</div>'
                f'</div>'
            )
        ml_cards_html += "</div>"
        st.markdown(ml_cards_html, unsafe_allow_html=True)
        strong_ml = ml_df[ml_df["ml_edge"] >= model.ML_EDGE_THRESHOLD]
        st.caption(f"{len(strong_ml)} game(s) with edge ≥ {model.ML_EDGE_THRESHOLD:.0%} — these are the ones "
                   f"eligible for the parlay pool on the Team Parlays tab.")

    st.markdown("#### Over/Under")
    if total_df.empty:
        st.info("No over/under lines available, or no scoring data yet to build a predicted total.")
    else:
        total_sorted = total_df.sort_values("total_edge", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
        has_opp_adj = "opponent_adjustment" in total_sorted.columns
        has_weather_adj = "weather_adjustment" in total_sorted.columns

        total_cards_html = '<div class="market-grid">'
        for _, row in total_sorted.iterrows():
            home, away = row["home_team"], row["away_team"]
            cover      = row["total_cover_prob"]
            neutral_html = '<div class="neutral-badge">⭐ Neutral Site</div>' if row.get("neutral_site") is True else ""
            stats_html = (
                f'<div><span class="today-stat-label">Market O/U</span><span class="today-stat-value">{row["market_total"]:.1f}</span></div>'
                f'<div><span class="today-stat-label">Predicted</span><span class="today-stat-value">{row["predicted_total"]:.1f}</span></div>'
                f'<div><span class="today-stat-label">Edge (pts)</span><span class="today-stat-value">{row["total_edge"]:+.1f}</span></div>'
            )
            if has_opp_adj and pd.notna(row.get("opponent_adjustment")):
                stats_html += (f'<div><span class="today-stat-label">Opp Adj</span>'
                                f'<span class="today-stat-value">{row["opponent_adjustment"]:+.1f}</span></div>')
            if has_weather_adj and pd.notna(row.get("weather_adjustment")):
                stats_html += (f'<div><span class="today-stat-label">Weather Adj</span>'
                                f'<span class="today-stat-value">{row["weather_adjustment"]:+.1f}</span></div>')

            total_cards_html += (
                f'<div class="market-card">'
                f'<div class="pickem-logos">{logo_img(away, 28)}<span class="pickem-vs">@</span>{logo_img(home, 28)}</div>'
                f'<div class="pickem-matchup">{fav_star(away)}{model.rank_badge(away, rankings)}{away} @ '
                f'{fav_star(home)}{model.rank_badge(home, rankings)}{home}</div>'
                f'{neutral_html}'
                f'<div class="pickem-hero"><span class="pickem-cover-prob" style="color:#38bdf8;">{cover:.0%}</span></div>'
                f'<div class="pickem-confidence-bar">'
                f'<div class="pickem-confidence-fill" style="width:{cover * 100:.0f}%;background:#38bdf8;"></div>'
                f'</div>'
                f'<div class="market-pick">&#10003; Total Pick: <b>{row["total_pick"]}</b></div>'
                f'<div class="today-stats">{stats_html}</div>'
                f'</div>'
            )
        total_cards_html += "</div>"
        st.markdown(total_cards_html, unsafe_allow_html=True)


# ── TAB 4: Championship Favorites ─────────────────────────────────────────────
with tab4:
    st.markdown("## 🥇 National Championship Favorites")
    st.caption(f"Based on SP+ ratings · {year} season · Higher rating = stronger team")

    sp_ratings = get_sp_ratings(year)

    if not sp_ratings:
        st.warning("No SP+ ratings found for this year.")
    else:
        sp_df = (
            pd.DataFrame(list(sp_ratings.items()), columns=["Team", "SP+ Rating"])
            .sort_values("SP+ Rating", ascending=False)
            .reset_index(drop=True)
        )
        display_champ = sp_df.head(25)
        sp_max = display_champ["SP+ Rating"].max()
        sp_min = display_champ["SP+ Rating"].min()

        cards_html = '<div class="futures-grid">'
        for i, row in display_champ.iterrows():
            rank       = i + 1
            team       = row["Team"]
            rating     = row["SP+ Rating"]
            rank_class = {1: "rank-1", 2: "rank-2", 3: "rank-3"}.get(rank, "rank-other")
            medal      = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")
            logo_tag   = logo_img(team, 40)
            bar_pct    = int((rating - sp_min) / (sp_max - sp_min + 0.001) * 100) if sp_max != sp_min else 80
            cards_html += (
                f'<div class="futures-card {rank_class}">'
                f'<div class="futures-rank">{medal}</div>'
                f'{logo_tag}'
                f'<div class="futures-name">{model.rank_badge(team, rankings)}{team}</div>'
                f'<div class="futures-score">{rating:+.1f}</div>'
                f'<div class="futures-label">SP+ Rating</div>'
                f'<div class="bar-bg"><div class="bar-fill" style="background:#38bdf8;width:{bar_pct}%;"></div></div>'
                f'</div>'
            )
        cards_html += "</div>"
        st.markdown(cards_html, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📰 AP & Coaches Top 25")
    st.caption(f"Actual human-voter poll rankings for {season_label.title()}, for comparison against SP+ above.")

    poll_cols = st.columns(2)
    for col, poll_name in zip(poll_cols, model.RANKING_POLLS):
        with col:
            st.markdown(f"**{poll_name}**")
            ranks = rankings.get(poll_name, {})
            if not ranks:
                st.caption("No rankings available for this week yet.")
                continue
            poll_df = (
                pd.DataFrame(list(ranks.items()), columns=["Team", "Rank"])
                .sort_values("Rank")
                .reset_index(drop=True)
            )
            poll_df["Logo"] = poll_df["Team"].map(lambda t: logos.get(t, ""))
            poll_df = poll_df[["Logo", "Rank", "Team"]]
            st.dataframe(
                poll_df, use_container_width=True, hide_index=True, height=min(50 + 35 * len(poll_df), 600),
                column_config={"Logo": st.column_config.ImageColumn("", width="small")},
            )

    st.markdown("---")
    st.markdown("### 📈 Best & Worst Against the Spread")
    st.caption(f"{year} real ATS record (CFBD-graded, not a model output) · "
               "ranked by average cover margin, the size of the beat/miss vs. the closing line, not just win/loss.")

    # get_teams_ats has no classification filter either (same situation as player
    # season stats) — filter to FBS using the team names already fetched for logos.
    fbs_ats_teams = set(logos.keys()) or set(ats_records.keys())
    ats_rows = [
        {"Team": team, "Record": model.ats_record_str(team, ats_records),
         "Games": r["games"], "Avg Cover Margin": r["avg_cover_margin"]}
        for team, r in ats_records.items()
        if r["avg_cover_margin"] is not None and team in fbs_ats_teams
    ]
    if not ats_rows:
        st.info("No ATS records available for this year yet — check back once games have been played.")
    else:
        ats_df = (
            pd.DataFrame(ats_rows)
            .sort_values("Avg Cover Margin", ascending=False)
            .reset_index(drop=True)
        )
        ats_df["Logo"] = ats_df["Team"].map(lambda t: logos.get(t, ""))
        ats_df = ats_df[["Logo", "Team", "Record", "Games", "Avg Cover Margin"]]
        ats_col_config = {"Logo": st.column_config.ImageColumn("", width="small")}
        ats_cols = st.columns(2)
        with ats_cols[0]:
            st.markdown("**Best ATS**")
            st.dataframe(ats_df.head(10), use_container_width=True, hide_index=True, column_config=ats_col_config)
        with ats_cols[1]:
            st.markdown("**Worst ATS**")
            st.dataframe(ats_df.tail(10).sort_values("Avg Cover Margin"), use_container_width=True,
                         hide_index=True, column_config=ats_col_config)


# ── TAB 5: Model Accuracy ─────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=21600)
def get_season_backtest(yr):
    return backtest.backtest_season(bearer_token, yr, range(1, 16), "regular")


with tab5:
    st.markdown("## 📊 Model Accuracy")

    # Deliberately small: this used to show a full win-rate/record breakdown, but that
    # number is inflated by look-ahead bias in a way CFBD's data makes unfixable (see the
    # warning below) — an impressive-looking but wrong number is worse than none at all in
    # a betting context. What survives that bias reasonably well is the *relative* question
    # "does higher confidence actually track with better results", so that's all this shows
    # now. The real, unbiased accuracy lives in Verified Accuracy below.
    st.markdown("#### 🎯 Tier Calibration Check")
    st.caption("Does higher confidence (Tier A) actually track with better results than lower "
               "confidence (Tier C)? Not a real accuracy number — see why below.")
    st.warning(
        "⚠️ **Look-ahead bias.** CFBD's SP+ ratings are one value per team per *year* — the "
        "fully-converged, end-of-season rating — not what was knowable the week a game was "
        "actually played. Grading past weeks with it means the 'prediction' already reflects "
        "games that hadn't happened yet, which inflates the numbers below. There's no clean fix "
        "(CFBD doesn't expose historical weekly snapshots), so treat this as a rough directional "
        "check — does Tier A actually beat Tier C — not a performance claim.",
        icon="⚠️",
    )

    if "accuracy_loaded_year" not in st.session_state:
        st.session_state["accuracy_loaded_year"] = None
    is_loaded = st.session_state["accuracy_loaded_year"] == year

    if not is_loaded:
        st.info(f"Checks every completed week of {year} — up to ~3× the API calls the rest of the "
                f"app uses combined. Cached afterward (6 hours), so this only costs quota once per season.")
        if st.button("🔄 Run Calibration Check", key="run_accuracy", type="primary"):
            st.session_state["accuracy_loaded_year"] = year
            st.rerun()
    else:
        with st.spinner("Backtesting every completed week of the season…"):
            graded = get_season_backtest(year)

        if graded.empty:
            st.info("No completed games with results yet for this season.")
        else:
            tier_summary = backtest.summarize_by_tier(graded)
            st.dataframe(
                tier_summary.rename(columns={
                    "tier": "Tier", "n": "N", "wins": "Wins",
                    "avg_predicted_cover_prob": "Predicted Cover Prob", "actual_win_rate": "Actual Win Rate",
                }),
                use_container_width=True, hide_index=True,
                column_config={
                    "Predicted Cover Prob": st.column_config.ProgressColumn("Predicted Cover Prob", min_value=0.0, max_value=1.0),
                    "Actual Win Rate": st.column_config.ProgressColumn("Actual Win Rate", min_value=0.0, max_value=1.0),
                },
            )

    st.markdown("---")
    st.markdown("## ✅ Verified Accuracy (Logged Picks)")
    st.caption("Only picks explicitly logged *before* their games were played — unlike the tier "
               "calibration check above, this has no look-ahead bias. It's the real record, but it "
               "only covers whatever's been logged via the 📌 Log Picks button on the Pick'em tab.")

    logged_df = pick_log.load_log()
    if logged_df.empty:
        st.info("No picks logged yet. Use the 📌 Log Picks button on the Pick'em tab each week "
                "to start building a real track record.")
    else:
        with st.spinner("Grading logged picks against final scores…"):
            graded_log = pick_log.grade_logged_picks(bearer_token)
        log_acc = backtest.overall_accuracy(graded_log)
        # This log is never cleared — a new slate gets auto-logged every time the "current
        # week" changes, so these numbers are a running total across every slate ever
        # logged, not just the current week's ~50 games. Surfacing the slate count here
        # (instead of leaving people to infer it from "92 seems like a lot") makes that
        # explicit instead of reading like a possible bug.
        week_record = pick_log.summarize_by_week(graded_log)
        if log_acc["n"] == 0:
            st.info(f"{len(logged_df)} pick(s) logged, but none have final scores yet.")
        else:
            lg1, lg2, lg3, lg4 = st.columns(4)
            lg1.metric("Logged Picks Graded", log_acc["n"])
            lg2.metric("Win Rate", f"{log_acc['win_rate']:.1%}" if log_acc["win_rate"] is not None else "—")
            lg3.metric("Wins / Losses", f"{log_acc['wins']} / {log_acc['losses']}")
            lg4.metric("Slates Logged", len(week_record))
            st.caption(f"Cumulative across {len(week_record)} logged slate(s) — see Record by week below "
                       f"for the breakdown per slate.")

        st.markdown("#### Record by week")
        st.caption("Every logged slate, win/loss record once results are in — 'Pending' means it's "
                   "logged but the games haven't finished yet.")
        # Built from logged_df (not logged_weeks()'s list-of-tuples helper) so the merge
        # key columns share the exact same dtypes as week_record's — both ultimately trace
        # back to the same load_log() call, avoiding a None-vs-NaN dtype mismatch on the
        # "week" column (None for postseason) that a fresh tuple-derived DataFrame risks.
        all_slates = logged_df[["year", "week", "season_type"]].drop_duplicates().sort_values(
            ["year", "week"], na_position="first"
        )
        weeks_display = all_slates.merge(week_record, on=["year", "week", "season_type"], how="left")
        weeks_display["Record"] = weeks_display.apply(
            lambda r: f"{int(r['wins'])}-{int(r['losses'])}" if pd.notna(r["wins"]) else "Pending", axis=1,
        )
        weeks_display = weeks_display.rename(
            columns={"year": "Year", "week": "Week", "season_type": "Season Type", "win_rate": "Win Rate"}
        )
        st.dataframe(
            weeks_display[["Year", "Week", "Season Type", "Record", "Win Rate"]],
            use_container_width=True, hide_index=True,
            column_config={"Win Rate": st.column_config.ProgressColumn("Win Rate", min_value=0.0, max_value=1.0)},
        )

        st.markdown("#### Game-by-game results")
        st.caption("Pick a logged slate to see exactly which games the model got right.")
        slate_options = list(all_slates.itertuples(index=False, name=None))

        def _format_slate(opt):
            yr, wk, stype = opt
            week_label = f"Week {int(wk)}" if pd.notna(wk) else "Postseason"
            return f"{int(yr)} {week_label} ({stype.title()})"

        selected_slate = st.selectbox(
            "Slate", options=slate_options, format_func=_format_slate,
            index=len(slate_options) - 1, key="game_results_slate",  # default to the most recently logged slate
        )
        sel_year, sel_week, sel_season_type = selected_slate
        week_mask = graded_log["week"].isna() if pd.isna(sel_week) else graded_log["week"] == sel_week
        slate_games = graded_log[
            (graded_log["year"] == sel_year) & week_mask & (graded_log["season_type"] == sel_season_type)
        ].sort_values("cover_prob", ascending=False).copy()

        def _result_str(r):
            if pd.isna(r["home_points"]):
                return "—"
            return f"{r['home_team']} {int(r['home_points'])}-{int(r['away_points'])} {r['away_team']}"

        outcome_labels = {"win": "✅ Win", "loss": "❌ Loss", "push": "🟰 Push"}
        slate_games["Home Logo"] = slate_games["home_team"].map(lambda t: logos.get(t, ""))
        slate_games["Away Logo"] = slate_games["away_team"].map(lambda t: logos.get(t, ""))
        slate_games["Result"] = slate_games.apply(_result_str, axis=1)
        slate_games["Outcome"] = slate_games["outcome"].map(lambda o: outcome_labels.get(o, "⏳ Pending"))

        game_display = slate_games.rename(columns={
            "home_team": "Home", "away_team": "Away",
            "market_spread_home": "Market Spread", "pick_team": "Pick", "tier": "Tier",
        })[["Home Logo", "Home", "Away Logo", "Away", "Market Spread", "Pick", "Tier", "Result", "Outcome"]]

        def _shade_outcome_row(row):
            return [outcome_row_css(slate_games.loc[row.name, "outcome"])] * len(row)

        st.dataframe(
            game_display.style.apply(_shade_outcome_row, axis=1),
            use_container_width=True, hide_index=True,
            column_config={
                "Home Logo": st.column_config.ImageColumn("", width="small"),
                "Away Logo": st.column_config.ImageColumn("", width="small"),
                "Market Spread": st.column_config.NumberColumn("Market Spread", format="%+.1f"),
            },
        )

    st.markdown("#### Backup / restore log")
    st.caption("⚠️ This log lives on the app's local disk and is **not** committed to git — a "
               "redeploy pulls a fresh container and wipes it. Download periodically to keep a "
               "permanent record, and restore after a reset.")
    bk_col1, bk_col2 = st.columns(2)
    with bk_col1:
        st.download_button("⬇️ Download Log (CSV)", data=logged_df.to_csv(index=False),
                           file_name="pick_log.csv", mime="text/csv", disabled=logged_df.empty)
    with bk_col2:
        uploaded_log = st.file_uploader("⬆️ Restore Log (CSV)", type="csv", key="restore_log_upload")
        if uploaded_log is not None:
            restored_df = pd.read_csv(uploaded_log)
            pick_log.restore_log(restored_df)
            st.success("Log restored — reload the page to see it reflected.")


# ── TAB 6: Stats ───────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=3600)
def get_player_season_stats(yr, category):
    return model.get_player_season_stats(bearer_token, yr, category, "regular")


with tab6:
    st.markdown("## 📈 Stats")
    st.caption(f"{year} regular season · Offensive stat leaderboard")

    st.info(
        "ℹ️ **Not real Heisman odds.** CFBD has no awards-odds market — no book prices a "
        "Heisman futures line through this API, so there's nothing legitimate to display as "
        "'odds.' What's below is a simple composite of real season stats instead: total yards "
        "+ 6 points per touchdown, summed across passing/rushing/receiving. It's a common "
        "informal 'total production' heuristic for gauging who's in the Heisman conversation, "
        "not a calibrated prediction.",
        icon="ℹ️",
    )

    if "stats_loaded_year" not in st.session_state:
        st.session_state["stats_loaded_year"] = None
    stats_loaded = st.session_state["stats_loaded_year"] == year

    if not stats_loaded:
        st.info(f"Fetches passing/rushing/receiving stats for every FBS player in {year} (3 API calls, "
                f"cached afterward for 1 hour).")
        if st.button("📊 Load Player Stats", key="run_stats", type="primary"):
            st.session_state["stats_loaded_year"] = year
            st.rerun()
    else:
        with st.spinner("Fetching player season stats…"):
            try:
                passing_stats = get_player_season_stats(year, "passing")
                rushing_stats = get_player_season_stats(year, "rushing")
                receiving_stats = get_player_season_stats(year, "receiving")
            except Exception as e:
                st.error(f"API error: {e}")
                passing_stats, rushing_stats, receiving_stats = [], [], []

        # get_player_season_stats has no classification filter (unlike the Games API), so it
        # returns every division mixed together. Filter to FBS using the team names already
        # fetched for logos — matches the rest of the app, which is FBS-only throughout.
        fbs_teams = set(logos.keys())
        if fbs_teams:
            passing_stats = [r for r in passing_stats if r["team"] in fbs_teams]
            rushing_stats = [r for r in rushing_stats if r["team"] in fbs_teams]
            receiving_stats = [r for r in receiving_stats if r["team"] in fbs_teams]

        leaderboard = model.build_stat_leaderboard(passing_stats, rushing_stats, receiving_stats, top_n=10)

        if leaderboard.empty:
            st.info("No player stats available yet for this season.")
        else:
            st.markdown("#### 🏈 Heisman Watch — Top 10 by Total Production")
            display = leaderboard[["player", "team", "position", "total_yards", "total_td", "score"]].rename(columns={
                "player": "Player", "team": "Team", "position": "Pos",
                "total_yards": "Total Yards", "total_td": "Total TDs", "score": "Score",
            })
            display["Logo"] = display["Team"].map(lambda t: logos.get(t, ""))
            display = display[["Logo", "Player", "Team", "Pos", "Total Yards", "Total TDs", "Score"]]
            st.dataframe(
                display, use_container_width=True, hide_index=True,
                column_config={
                    "Logo": st.column_config.ImageColumn("", width="small"),
                    "Total Yards": st.column_config.NumberColumn("Total Yards", format="%.0f"),
                    "Total TDs": st.column_config.NumberColumn("Total TDs", format="%.0f"),
                    "Score": st.column_config.NumberColumn("Score", format="%.0f",
                                                            help="Total yards + 6 × total TDs"),
                },
            )

        st.markdown("---")
        st.markdown("#### Category leaders")
        st.caption("Ranked within their own stat — unlike Heisman Watch above, these aren't blended "
                   "across categories, so rushers and receivers show up here on equal footing with passers.")

        def render_leader_table(rows, stat_type, value_label):
            leaders = model.top_stat_leaders(rows, stat_type, top_n=5)
            if leaders.empty:
                st.caption("No data.")
                return
            leaders = leaders.rename(columns={"player": "Player", "team": "Team", "position": "Pos", "value": value_label})
            leaders["Logo"] = leaders["Team"].map(lambda t: logos.get(t, ""))
            leaders = leaders[["Logo", "Player", "Team", "Pos", value_label]]
            st.dataframe(
                leaders, use_container_width=True, hide_index=True,
                column_config={
                    "Logo": st.column_config.ImageColumn("", width="small"),
                    value_label: st.column_config.NumberColumn(value_label, format="%.0f"),
                },
            )

        p1, p2 = st.columns(2)
        with p1:
            st.markdown("**Passing Yards**")
            render_leader_table(passing_stats, "YDS", "Yards")
        with p2:
            st.markdown("**Passing TDs**")
            render_leader_table(passing_stats, "TD", "TDs")

        r1, r2 = st.columns(2)
        with r1:
            st.markdown("**Rushing Yards**")
            render_leader_table(rushing_stats, "YDS", "Yards")
        with r2:
            st.markdown("**Rushing TDs**")
            render_leader_table(rushing_stats, "TD", "TDs")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Receiving Yards**")
            render_leader_table(receiving_stats, "YDS", "Yards")
        with c2:
            st.markdown("**Receiving TDs**")
            render_leader_table(receiving_stats, "TD", "TDs")
