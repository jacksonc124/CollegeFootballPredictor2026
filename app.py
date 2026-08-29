import itertools
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd

import backtest
import model
import pick_log

EASTERN = ZoneInfo("America/New_York")


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
        background: #22c55e; color: #0d0f14;
        font-family: 'Bebas Neue', sans-serif; font-size: 18px;
        letter-spacing: 2px; border: none; border-radius: 6px;
        padding: 10px 32px; width: 100%; transition: background 0.2s;
    }
    div.stButton > button[kind="primary"]:hover { background: #16a34a; color: #fff; }

    .pickem-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
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
    .pickem-rank { font-family: 'Bebas Neue', sans-serif; font-size: 28px; line-height: 1; opacity: 0.4; }
    .pickem-matchup { font-size: 13px; opacity: 0.6; }
    .pickem-pick { font-family: 'Bebas Neue', sans-serif; font-size: 20px; letter-spacing: 1px; }
    .pickem-meta { font-size: 11px; opacity: 0.5; }
    .pickem-logos { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
    .pickem-vs { font-size: 11px; opacity: 0.4; }

    .parlay-card {
        background: var(--background-color);
        border: 1px solid #22c55e44;
        border-radius: 10px; padding: 16px 20px; margin-bottom: 14px;
    }
    .parlay-title {
        font-family: 'Bebas Neue', sans-serif; font-size: 22px;
        color: #22c55e; letter-spacing: 1px; margin-bottom: 8px;
    }
    .parlay-leg { font-size: 13px; padding: 4px 0; border-bottom: 1px solid rgba(128,128,128,0.15); }
    .parlay-leg:last-child { border-bottom: none; }
    .parlay-prob { font-family: 'Bebas Neue', sans-serif; font-size: 18px; color: #facc15; margin-top: 10px; }

    .leg-display { font-family: 'Bebas Neue', sans-serif; font-size: 52px; color: #22c55e; line-height: 1; text-align: center; }
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
    .futures-score { font-family: 'Bebas Neue', sans-serif; font-size: 22px; color: #22c55e; }
    .futures-label { font-size: 11px; opacity: 0.5; }
    .bar-bg { margin-top: 6px; background: rgba(128,128,128,0.15); border-radius: 4px; height: 4px; width: 100%; }
    .bar-fill { border-radius: 4px; height: 4px; }

    /* Light chip behind every team logo so dark/transparent PNG artwork stays visible
       regardless of the app's light/dark theme. */
    .logo-chip {
        display: inline-flex; align-items: center; justify-content: center;
        background: rgba(255,255,255,0.94);
        border: 1px solid rgba(0,0,0,0.08);
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
}


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


# ── sidebar ───────────────────────────────────────────────────────────────────
_today = date.today()
default_year, default_week = model.resolve_current_week(get_calendar_cached(_today.year), _today.year, _today)

with st.sidebar:
    st.markdown("# 🏈 CFB MODEL")
    st.markdown("---")
    st.markdown("### 📅 Season")
    year = st.number_input("Year", min_value=2000, max_value=2030, value=default_year, step=1)
    postseason = st.checkbox("📬 Postseason / Bowl Games", value=False,
                             help="Fetches every bowl & CFP game for the selected year, ignoring week. "
                                  "CFBD groups all of them under one 'week', so the week selector doesn't apply here.")
    week = st.slider("Week", min_value=1, max_value=15, value=default_week, step=1,
                     disabled=postseason)

    week0_filter = "All"
    if week == 1 and not postseason:
        week0_filter = st.radio(
            "Week 1 slate", ["All", "Week 0 only", "Week 1 only"], horizontal=True,
            help="CFBD lumps the early season-opening games (what fans call 'Week 0') and the "
                 "Labor Day weekend slate together under one 'week 1' — there's no such split in "
                 "their data. This filters by actual game date instead (cutoff: the Thursday "
                 "before Labor Day).",
        )

    st.markdown("### ⚙️ Model")
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
def get_team_logos(yr):
    return model.get_team_logos(bearer_token, yr)


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

if week0_filter != "All":
    is_week0 = df["start_date"].apply(lambda d: model.is_week_zero_game(d, year))
    df = df[is_week0 if week0_filter == "Week 0 only" else ~is_week0].reset_index(drop=True)
    if df.empty:
        st.warning(f"No games found for '{week0_filter}'. Try 'All' instead.")
        st.stop()

df["start_date"] = df.apply(lambda r: format_game_date(r["start_date"], r["start_time_tbd"]), axis=1)
df = df.drop(columns=["start_time_tbd"])

strong = model.strong_picks(df)

# ── Summary metrics ───────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Games",    len(df))
c2.metric("Strong Picks",   len(strong))
c3.metric("Tier A Picks",   len(df[df["tier"] == "A"]))
c4.metric("Avg Cover Prob", f"{df['cover_prob'].mean():.3f}")

# ── Week-at-a-glance chart ──────────────────────────────────────────────────────
TIER_COLORS = {"A": "#22c55e", "B": "#facc15", "C": "#fb923c", "Pass": "#6b7280"}
chart_df = df[["edge_points", "cover_prob", "tier"]].rename(
    columns={"edge_points": "Edge (pts)", "cover_prob": "Cover Prob"}
)
chart_df["Tier Color"] = df["tier"].map(TIER_COLORS)
st.scatter_chart(chart_df, x="Edge (pts)", y="Cover Prob", color="Tier Color", height=220, use_container_width=True)
st.caption("Each dot is one game · farther from center = bigger edge (either direction) · "
           "higher = more confident · color = tier (🟢 A · 🟡 B · 🟠 C · ⚪ Pass)")
st.markdown("---")


# ── Logo helper ───────────────────────────────────────────────────────────────
def logo_img(team, size=32):
    """
    Render a team logo (or initials fallback) inside a light circular chip.
    The chip guarantees contrast regardless of app theme or how dark/transparent
    a given team's logo artwork is — some logos are otherwise invisible on a
    dark background.
    """
    url = logos.get(team, "")
    if url:
        inner = f'<img src="{url}" width="{size}" height="{size}" style="object-fit:contain;" />'
    else:
        initials = "".join(w[0] for w in team.split()[:2]).upper()
        inner = f'<span style="font-family:\'Bebas Neue\',sans-serif;font-size:{size // 2}px;color:#0d0f14;">{initials}</span>'
    pad = max(2, size // 8)
    chip_size = size + pad * 2
    return f'<span class="logo-chip" style="width:{chip_size}px;height:{chip_size}px;">{inner}</span>'


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🏆  CBS Pick'em Top 12",
    "🎰  Team Parlays",
    "💰  Moneylines & O/U",
    "🥇  Championship Favorites",
    "📊  Model Accuracy",
    "📈  Stats",
])


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
            if st.button("📌 Log Picks", key="log_picks_btn", use_container_width=True):
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
            cards_html += (
                f'<div class="pickem-card tier-{tier}">'
                f'<div class="pickem-rank">#{i + 1}</div>'
                f'<div class="pickem-logos">{logo_img(away, 32)}<span class="pickem-vs">@</span>{logo_img(home, 32)}</div>'
                f'<div class="pickem-matchup">{model.rank_badge(away, rankings)}{away} @ '
                f'{model.rank_badge(home, rankings)}{home}</div>'
                f'<div class="pickem-pick">&#10003; {model.rank_badge(pick_team, rankings)}{pick_team}</div>'
                f'<div class="pickem-meta">'
                f'Cover Prob: <b>{cover:.1%}</b> &nbsp;|&nbsp; '
                f'Edge: <b>{edge:+.1f} pts</b> &nbsp;|&nbsp; '
                f'Tier: <b>{tier}</b>'
                f'{"<br/>" + spread_str if spread_str else ""}'
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

    TIER_CELL_COLORS = {"A": "#22c55e33", "B": "#facc1533", "C": "#fb923c33", "Pass": "transparent"}

    def _shade_tier(val):
        return f"background-color: {TIER_CELL_COLORS.get(val, 'transparent')}"

    table_df = (
        filtered.drop(columns=["pick_team"]).rename(columns=DISPLAY_COLUMNS)
                .sort_values("Edge (pts)", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
    )
    # ATS lookups use the clean team name, so compute them before the rank-badge prefix is added.
    table_df["Home ATS"] = table_df["Home"].map(lambda t: model.ats_record_str(t, ats_records))
    table_df["Away ATS"] = table_df["Away"].map(lambda t: model.ats_record_str(t, ats_records))
    table_df["Home"] = table_df["Home"].map(lambda t: f"{model.rank_badge(t, rankings)}{t}")
    table_df["Away"] = table_df["Away"].map(lambda t: f"{model.rank_badge(t, rankings)}{t}")
    st.dataframe(
        table_df.style.map(_shade_tier, subset=["Tier"]),
        use_container_width=True, height=min(50 + 35 * len(filtered), 600),
        column_config={
            "Cover Prob": st.column_config.ProgressColumn("Cover Prob", min_value=0.0, max_value=1.0),
            "Edge (pts)": st.column_config.NumberColumn("Edge (pts)", format="%+.1f"),
            "Model Spread": st.column_config.NumberColumn("Model Spread", format="%+.1f"),
            "Market Spread": st.column_config.NumberColumn("Market Spread", format="%+.1f"),
            "SP+ Home": st.column_config.NumberColumn("SP+ Home", format="%+.1f"),
            "SP+ Away": st.column_config.NumberColumn("SP+ Away", format="%+.1f"),
            "Neutral Site": st.column_config.CheckboxColumn("Neutral Site"),
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
                    f'&nbsp;&middot;&nbsp;Prob: <b style="color:#facc15">{leg["leg_prob"]:.1%}</b>'
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
        ml_display = (
            ml_df[["home_team", "away_team", "home_moneyline", "away_moneyline",
                   "ml_pick_team", "ml_model_prob", "ml_market_prob", "ml_edge"]]
            .rename(columns={
                "home_team": "Home", "away_team": "Away",
                "home_moneyline": "Home ML", "away_moneyline": "Away ML",
                "ml_pick_team": "Pick", "ml_model_prob": "Model Win Prob",
                "ml_market_prob": "Market Win Prob", "ml_edge": "Edge",
            })
            .sort_values("Edge", ascending=False)
            .reset_index(drop=True)
        )
        ml_display["Home"] = ml_display["Home"].map(lambda t: f"{model.rank_badge(t, rankings)}{t}")
        ml_display["Away"] = ml_display["Away"].map(lambda t: f"{model.rank_badge(t, rankings)}{t}")
        st.dataframe(
            ml_display, use_container_width=True, hide_index=True,
            column_config={
                "Model Win Prob": st.column_config.ProgressColumn("Model Win Prob", min_value=0.0, max_value=1.0),
                "Market Win Prob": st.column_config.ProgressColumn("Market Win Prob", min_value=0.0, max_value=1.0),
                "Edge": st.column_config.NumberColumn("Edge", format="%.3f"),
            },
        )
        strong_ml = ml_df[ml_df["ml_edge"] >= model.ML_EDGE_THRESHOLD]
        st.caption(f"{len(strong_ml)} game(s) with edge ≥ {model.ML_EDGE_THRESHOLD:.0%} — these are the ones "
                   f"eligible for the parlay pool on the Team Parlays tab.")

    st.markdown("#### Over/Under")
    if total_df.empty:
        st.info("No over/under lines available, or no scoring data yet to build a predicted total.")
    else:
        total_cols = ["home_team", "away_team", "market_total", "predicted_total",
                      "total_edge", "total_pick", "total_cover_prob"]
        rename_map = {
            "home_team": "Home", "away_team": "Away", "market_total": "Market O/U",
            "predicted_total": "Predicted Total", "total_edge": "Edge (pts)",
            "total_pick": "Pick", "total_cover_prob": "Cover Prob",
        }
        if "opponent_adjustment" in total_df.columns:
            total_cols.append("opponent_adjustment")
            rename_map["opponent_adjustment"] = "Opp Adj"
        if "weather_adjustment" in total_df.columns:
            total_cols.append("weather_adjustment")
            rename_map["weather_adjustment"] = "Weather Adj"

        total_display = (
            total_df[total_cols]
            .rename(columns=rename_map)
            .sort_values("Edge (pts)", key=lambda s: s.abs(), ascending=False)
            .reset_index(drop=True)
        )
        total_display["Home"] = total_display["Home"].map(lambda t: f"{model.rank_badge(t, rankings)}{t}")
        total_display["Away"] = total_display["Away"].map(lambda t: f"{model.rank_badge(t, rankings)}{t}")
        st.dataframe(
            total_display, use_container_width=True, hide_index=True,
            column_config={
                "Cover Prob": st.column_config.ProgressColumn("Cover Prob", min_value=0.0, max_value=1.0),
                "Opp Adj": st.column_config.NumberColumn("Opp Adj", format="%+.1f",
                                                          help="Points added/removed by opponent-adjusted EPA"),
                "Weather Adj": st.column_config.NumberColumn("Weather Adj", format="%+.1f",
                                                              help="Points removed for wind/precipitation/snow"),
            },
        )


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
                f'<div class="bar-bg"><div class="bar-fill" style="background:#22c55e;width:{bar_pct}%;"></div></div>'
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
            st.dataframe(poll_df, use_container_width=True, hide_index=True, height=min(50 + 35 * len(poll_df), 600))

    st.markdown("---")
    st.markdown("### 📈 Best & Worst Against the Spread")
    st.caption(f"{year} real ATS record (CFBD-graded, not a model output) · "
               "ranked by average cover margin, the size of the beat/miss vs. the closing line, not just win/loss.")

    if not ats_records:
        st.info("No ATS records available for this year yet.")
    else:
        # get_teams_ats has no classification filter either (same situation as player
        # season stats) — filter to FBS using the team names already fetched for logos.
        fbs_ats_teams = set(logos.keys()) or set(ats_records.keys())
        ats_df = (
            pd.DataFrame([
                {"Team": team, "Record": model.ats_record_str(team, ats_records),
                 "Games": r["games"], "Avg Cover Margin": r["avg_cover_margin"]}
                for team, r in ats_records.items()
                if r["avg_cover_margin"] is not None and team in fbs_ats_teams
            ])
            .sort_values("Avg Cover Margin", ascending=False)
            .reset_index(drop=True)
        )
        ats_cols = st.columns(2)
        with ats_cols[0]:
            st.markdown("**Best ATS**")
            st.dataframe(ats_df.head(10), use_container_width=True, hide_index=True)
        with ats_cols[1]:
            st.markdown("**Worst ATS**")
            st.dataframe(ats_df.tail(10).sort_values("Avg Cover Margin"), use_container_width=True, hide_index=True)


# ── TAB 5: Model Accuracy ─────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=21600)
def get_season_backtest(yr):
    return backtest.backtest_season(bearer_token, yr, range(1, 16), "regular")


with tab5:
    st.markdown("## 📊 Model Accuracy")
    st.caption(f"SP+ vs. market ATS picks graded against actual final scores · {year} regular season")

    st.warning(
        "⚠️ **Look-ahead bias.** CFBD's SP+ ratings are one value per team per *year* — "
        "the fully-converged, end-of-season rating — not what was knowable the week a game "
        "was actually played. Early-season weeks especially are graded using ratings that "
        "already reflect games that hadn't happened yet, which inflates these numbers. "
        "There's no clean fix (CFBD doesn't expose historical weekly SP+ snapshots), so treat "
        "this as a rough calibration check, not a claim about live performance. The week-by-week "
        "chart below makes the bias visible: a real edge shouldn't swing this much week to week.",
        icon="⚠️",
    )

    if "accuracy_loaded_year" not in st.session_state:
        st.session_state["accuracy_loaded_year"] = None
    is_loaded = st.session_state["accuracy_loaded_year"] == year

    if not is_loaded:
        st.info(f"This checks results for every completed week of {year} — up to ~3× the API calls the "
                f"rest of the app uses combined. It's cached afterward (6 hours), so this only costs "
                f"quota on the first run per season.")
        if st.button("🔄 Run Season Backtest", key="run_accuracy"):
            st.session_state["accuracy_loaded_year"] = year
            st.rerun()
    else:
        with st.spinner("Backtesting every completed week of the season…"):
            graded = get_season_backtest(year)

        if graded.empty:
            st.info("No completed games with results yet for this season.")
        else:
            acc = backtest.overall_accuracy(graded)
            a1, a2, a3, a4 = st.columns(4)
            a1.metric("Graded Picks", acc["n"])
            a2.metric("Win Rate", f"{acc['win_rate']:.1%}" if acc["win_rate"] is not None else "—")
            a3.metric("Wins / Losses", f"{acc['wins']} / {acc['losses']}")
            a4.metric("Pushes", acc["pushes"])

            st.markdown("#### Calibration by tier")
            st.caption("Predicted cover probability vs. actual win rate — a well-calibrated tier has these close together.")
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

            st.markdown("#### Win rate by week")
            week_summary = backtest.summarize_by_week(graded).set_index("week")
            st.bar_chart(week_summary["win_rate"], height=220, use_container_width=True)

    st.markdown("---")
    st.markdown("## ✅ Verified Accuracy (Logged Picks)")
    st.caption("Only picks explicitly logged *before* their games were played — unlike the season "
               "backtest above, this has no look-ahead bias. It's the real record, but it only "
               "covers whatever's been logged via the 📌 Log Picks button on the Pick'em tab.")

    logged_df = pick_log.load_log()
    if logged_df.empty:
        st.info("No picks logged yet. Use the 📌 Log Picks button on the Pick'em tab each week "
                "to start building a real track record.")
    else:
        with st.spinner("Grading logged picks against final scores…"):
            graded_log = pick_log.grade_logged_picks(bearer_token)
        log_acc = backtest.overall_accuracy(graded_log)
        if log_acc["n"] == 0:
            st.info(f"{len(logged_df)} pick(s) logged, but none have final scores yet.")
        else:
            lg1, lg2, lg3 = st.columns(3)
            lg1.metric("Logged Picks Graded", log_acc["n"])
            lg2.metric("Win Rate", f"{log_acc['win_rate']:.1%}" if log_acc["win_rate"] is not None else "—")
            lg3.metric("Wins / Losses", f"{log_acc['wins']} / {log_acc['losses']}")

        st.markdown("#### Logged slates")
        weeks_df = pd.DataFrame(pick_log.logged_weeks(), columns=["Year", "Week", "Season Type"])
        st.dataframe(weeks_df, use_container_width=True, hide_index=True)

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
        if st.button("📊 Load Player Stats", key="run_stats"):
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
            st.dataframe(
                display, use_container_width=True, hide_index=True,
                column_config={
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
            st.dataframe(
                leaders.rename(columns={"player": "Player", "team": "Team", "position": "Pos", "value": value_label}),
                use_container_width=True, hide_index=True,
                column_config={value_label: st.column_config.NumberColumn(value_label, format="%.0f")},
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
