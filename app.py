import itertools
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd

import backtest
import model

EASTERN = ZoneInfo("America/New_York")


# ── CFB week helper ───────────────────────────────────────────────────────────
def get_current_cfb_week() -> tuple:
    today        = date.today()
    current_year = today.year
    season_start = date(current_year, 9, 1)
    if today < season_start:
        return current_year - 1, 1
    week = min((today - season_start).days // 7 + 1, 15)
    return current_year, week


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


# ── sidebar ───────────────────────────────────────────────────────────────────
default_year, default_week = get_current_cfb_week()

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


# ── Fetch ─────────────────────────────────────────────────────────────────────
with st.spinner("Fetching ratings, lines, and logos…"):
    try:
        ratings       = get_sp_ratings(year)
        games         = get_weekly_lines(year, api_week, season_type)
        game_info     = get_game_info(year, api_week, season_type)
        scoring_stats = get_scoring_stats(year)
        df            = model.build_picks(ratings, games, model.DEFAULT_PROVIDER, home_field, model.SPREAD_STD_DEV,
                                           game_info=game_info, scoring_stats=scoring_stats)
        logos         = get_team_logos(year)
    except Exception as e:
        st.error(f"API error: {e}")
        st.stop()

if df.empty:
    st.warning("No games returned. Try a different year or toggle postseason.")
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
                f'<div class="pickem-matchup">{away} @ {home}</div>'
                f'<div class="pickem-pick">&#10003; {pick_team}</div>'
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
def build_parlay_leg_pool(df_inner: pd.DataFrame) -> pd.DataFrame:
    """
    Unify Tier A/B ATS picks and high-value moneyline picks into one candidate-leg
    pool, so parlays can mix bet types. Each leg keeps its originating (home, away)
    game so combos can be filtered to one leg per game (see render_parlay_tab).
    """
    # leg_odds carries each leg's real American odds so parlay payout is computed from
    # actual odds per leg instead of assuming every leg is standard -110 juice — a heavy
    # moneyline favorite pays far less than -110 would imply (see model.american_to_decimal_odds).
    leg_cols = ["home_team", "away_team", "leg_type", "leg_team", "leg_prob", "leg_label", "leg_detail", "leg_odds"]

    ats_legs = df_inner[df_inner["tier"].isin(["A", "B"]) & (df_inner["pick_team"] != "")].copy()
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
            & (df_inner["ml_edge"] >= model.ML_EDGE_THRESHOLD)
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
    st.caption("Built from Tier A/B ATS picks and high-value moneylines "
               f"(edge ≥ {model.ML_EDGE_THRESHOLD:.0%}) · Combined prob = product of leg probabilities "
               "· Payout uses each leg's real odds (−110 assumed for ATS/O-U, actual moneyline for ML legs)")
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

    leg_count = st.session_state["parlay_legs"]
    pool_size = leg_count + 4

    leg_pool = build_parlay_leg_pool(df_inner)
    parlay_pool = leg_pool.sort_values("leg_prob", ascending=False).head(pool_size).reset_index(drop=True)

    if len(parlay_pool) < leg_count:
        st.info(f"Not enough Tier A/B ATS or high-value moneyline picks for a {leg_count}-leg parlay. "
                f"Try reducing legs.")
        return

    # One leg per game: exclude combos where two legs share the same (home, away) matchup.
    combos = [
        c for c in itertools.combinations(parlay_pool.index, leg_count)
        if parlay_pool.loc[list(c), ["home_team", "away_team"]].drop_duplicates().shape[0] == leg_count
    ]

    if not combos:
        st.info(f"No valid {leg_count}-leg combos — the top picks are too concentrated in the same games. "
                f"Try reducing legs.")
        return

    parlay_rows = sorted(
        [{"joint_prob": round(parlay_pool.loc[list(c), "leg_prob"].prod(), 4),
          "payout": round(parlay_pool.loc[list(c), "leg_odds"].map(model.american_to_decimal_odds).prod(), 2),
          "legs": parlay_pool.loc[list(c)]} for c in combos],
        key=lambda x: x["joint_prob"], reverse=True,
    )

    all_html = ""
    for i, p in enumerate(parlay_rows[:5]):
        legs_html = ""
        for _, leg in p["legs"].iterrows():
            legs_html += (
                f'<div class="parlay-leg">'
                f'{logo_img(leg["leg_team"], 20)}&nbsp;<b>{leg["leg_label"]}</b>'
                f'&nbsp;<span style="opacity:0.5">({leg["away_team"]} @ {leg["home_team"]})</span>'
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


with tab2:
    render_parlay_tab(df)


# ── TAB 3: Moneylines & O/U ────────────────────────────────────────────────────
with tab3:
    st.markdown("## 💰 Moneylines & Over/Under")
    st.caption("Moneyline edge = model win probability vs. the market's vig-removed implied probability.")
    st.info(
        "ℹ️ **Over/Under is informational only — no model pick.** The rest of this app predicts "
        "*margin* (SP+ vs. market spread); total points is a different, noisier thing to predict "
        "and needs its own signal. The 'Predicted Total' column below comes from a simple blended "
        "estimate (each team's own scoring average blended with their opponent's average points "
        "allowed) — treat it as a rough guide, not a calibrated model like the spread picks.",
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
        total_display = (
            total_df[["home_team", "away_team", "market_total", "predicted_total",
                      "total_edge", "total_pick", "total_cover_prob"]]
            .rename(columns={
                "home_team": "Home", "away_team": "Away", "market_total": "Market O/U",
                "predicted_total": "Predicted Total", "total_edge": "Edge (pts)",
                "total_pick": "Pick", "total_cover_prob": "Cover Prob",
            })
            .sort_values("Edge (pts)", key=lambda s: s.abs(), ascending=False)
            .reset_index(drop=True)
        )
        st.dataframe(
            total_display, use_container_width=True, hide_index=True,
            column_config={
                "Cover Prob": st.column_config.ProgressColumn("Cover Prob", min_value=0.0, max_value=1.0),
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
                f'<div class="futures-name">{team}</div>'
                f'<div class="futures-score">{rating:+.1f}</div>'
                f'<div class="futures-label">SP+ Rating</div>'
                f'<div class="bar-bg"><div class="bar-fill" style="background:#22c55e;width:{bar_pct}%;"></div></div>'
                f'</div>'
            )
        cards_html += "</div>"
        st.markdown(cards_html, unsafe_allow_html=True)


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

    with st.spinner("Fetching player season stats…"):
        try:
            passing_stats = get_player_season_stats(year, "passing")
            rushing_stats = get_player_season_stats(year, "rushing")
            receiving_stats = get_player_season_stats(year, "receiving")
        except Exception as e:
            st.error(f"API error: {e}")
            passing_stats, rushing_stats, receiving_stats = [], [], []

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
