import itertools
import os
from datetime import date

import streamlit as st
import pandas as pd

import model


# ── CFB week helper ───────────────────────────────────────────────────────────
def get_current_cfb_week() -> tuple:
    today        = date.today()
    current_year = today.year
    season_start = date(current_year, 9, 1)
    if today < season_start:
        return current_year - 1, 1
    week = min((today - season_start).days // 7 + 1, 15)
    return current_year, week


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
</style>
""", unsafe_allow_html=True)


# ── display column names (raw model.py columns → friendly UI headers) ─────────
DISPLAY_COLUMNS = {
    "home_team": "Home", "away_team": "Away", "provider": "Provider",
    "sp_home_rating": "SP+ Home", "sp_away_rating": "SP+ Away",
    "model_spread_home": "Model Spread", "market_spread_home": "Market Spread",
    "edge_points": "Edge (pts)", "cover_prob": "Cover Prob", "tier": "Tier",
    "model_pick": "Pick",
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
    st.markdown("### Season")
    year = st.number_input("Year", min_value=2000, max_value=2030, value=default_year, step=1)
    postseason = st.checkbox("📬 Postseason / Bowl Games", value=False,
                             help="Fetches all bowl & playoff games for the selected year, ignoring week.")
    week = st.slider("Week", min_value=1, max_value=15, value=default_week, step=1,
                     disabled=postseason)

    st.markdown("### Model")
    default_hf = 0.0 if postseason else model.DEFAULT_HOME_FIELD
    home_field = st.number_input(
        "Home Field Advantage (pts)",
        min_value=0.0, max_value=10.0, value=default_hf, step=0.5,
        help="Bowl/playoff games are neutral site — 0 recommended.",
    )
    run_btn = st.button("RUN MODEL")

# Resolve API params from sidebar state
season_type = "postseason" if postseason else "regular"
api_week    = None if postseason else week


# ── header ────────────────────────────────────────────────────────────────────
season_label = "POSTSEASON" if postseason else f"WK {week}"
st.markdown(f"# CFB — {year} · {season_label}")
st.markdown("SP+ ratings vs. consensus market spreads · Edge-based ATS picks")
st.markdown("---")

if not run_btn:
    st.info("Configure parameters in the sidebar, then press **RUN MODEL**.")
    st.stop()

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


@st.cache_data(show_spinner=False, ttl=86400)
def get_team_logos(yr):
    return model.get_team_logos(bearer_token, yr)


# ── Fetch ─────────────────────────────────────────────────────────────────────
with st.spinner("Fetching ratings, lines, and logos…"):
    try:
        ratings = get_sp_ratings(year)
        games   = get_weekly_lines(year, api_week, season_type)
        df      = model.build_picks(ratings, games, model.DEFAULT_PROVIDER, home_field, model.SPREAD_STD_DEV)
        logos   = get_team_logos(year)
    except Exception as e:
        st.error(f"API error: {e}")
        st.stop()

if df.empty:
    st.warning("No games returned. Try a different year or toggle postseason.")
    st.stop()

strong = model.strong_picks(df)

# ── Summary metrics ───────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Games",    len(df))
c2.metric("Strong Picks",   len(strong))
c3.metric("Tier A Picks",   len(df[df["tier"] == "A"]))
c4.metric("Avg Cover Prob", f"{df['cover_prob'].mean():.3f}")
st.markdown("---")


# ── Logo helper ───────────────────────────────────────────────────────────────
def logo_img(team, size=32):
    url = logos.get(team, "")
    if url:
        return f'<img src="{url}" width="{size}" height="{size}" style="object-fit:contain;vertical-align:middle;" />'
    initials = "".join(w[0] for w in team.split()[:2]).upper()
    return f'<span style="font-family:\'Bebas Neue\',sans-serif;font-size:{size//2}px;opacity:0.4;">{initials}</span>'


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3 = st.tabs([
    "🏆  CBS Pick'em Top 12",
    "🎰  Team Parlays",
    "🥇  Championship Favorites",
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
            spread_str = f"Spread: {spread:+.1f}" if spread is not None else ""
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
                f'</div></div>'
            )
        cards_html += "</div>"
        st.markdown(cards_html, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("## 📋 All Games")
    tier_filter = st.multiselect("Filter by Tier", ["A","B","C","Pass"], default=["A","B","C","Pass"], key="tf1")
    filtered = df[df["tier"].isin(tier_filter)] if tier_filter else df
    st.dataframe(
        filtered.drop(columns=["pick_team"]).rename(columns=DISPLAY_COLUMNS)
                .sort_values("Edge (pts)", key=lambda s: s.abs(), ascending=False).reset_index(drop=True),
        use_container_width=True, height=min(50 + 35 * len(filtered), 600),
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
@st.fragment
def render_parlay_tab(df_inner, logos_inner):
    st.markdown("## 🎰 Team Parlays")
    st.caption("Built from Tier A & B picks · Combined prob = product of cover probs · Est. payout assumes −110 per leg")
    st.caption("⚠️ Combined probability assumes each leg's outcome is statistically independent — "
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

    parlay_pool = (
        df_inner[df_inner["tier"].isin(["A", "B"]) & (df_inner["pick_team"] != "")]
        .sort_values("cover_prob", ascending=False)
        .head(pool_size)
        .reset_index(drop=True)
    )

    if len(parlay_pool) < leg_count:
        st.info(f"Not enough Tier A/B picks for a {leg_count}-leg parlay. Try reducing legs or lowering thresholds.")
        return

    combos = list(itertools.combinations(parlay_pool.index, leg_count))
    parlay_rows = sorted(
        [{"joint_prob": round(parlay_pool.loc[list(c), "cover_prob"].prod(), 4),
          "legs": parlay_pool.loc[list(c)]} for c in combos],
        key=lambda x: x["joint_prob"], reverse=True,
    )
    payout = round(((100 / 110) + 1) ** leg_count, 2)

    all_html = ""
    for i, p in enumerate(parlay_rows[:5]):
        legs_html = ""
        for _, leg in p["legs"].iterrows():
            lm = logos_inner.get(leg["pick_team"], "")
            logo_tag = (f'<img src="{lm}" width="20" height="20" style="object-fit:contain;vertical-align:middle;" />'
                        if lm else "")
            legs_html += (
                f'<div class="parlay-leg">'
                f'{logo_tag}&nbsp;<b>{leg["pick_team"]}</b> ATS'
                f'&nbsp;<span style="opacity:0.5">({leg["away_team"]} @ {leg["home_team"]})</span>'
                f'&nbsp;&middot;&nbsp;Cover Prob: <b style="color:#facc15">{leg["cover_prob"]:.1%}</b>'
                f'&nbsp;&middot;&nbsp;Edge: <b>{leg["edge_points"]:+.1f} pts</b>'
                f'&nbsp;&middot;&nbsp;Tier {leg["tier"]}'
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
            f'&nbsp;&middot;&nbsp;Est. Payout (&minus;110 each): ~{payout}x'
            f'</div></div>'
        )
    st.markdown(all_html, unsafe_allow_html=True)


with tab2:
    render_parlay_tab(df, logos)


# ── TAB 3: Championship Favorites ─────────────────────────────────────────────
with tab3:
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
