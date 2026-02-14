import math
import os
import itertools
from datetime import date
import streamlit as st
import pandas as pd


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

    /* Tabs */
    .stTabs [data-baseweb="tab"] {
        font-family: 'Bebas Neue', sans-serif; font-size: 16px;
        letter-spacing: 1px; border-radius: 6px; padding: 8px 20px;
    }

    /* RUN MODEL button */
    div.stButton > button[kind="primary"] {
        background: #22c55e; color: #0d0f14;
        font-family: 'Bebas Neue', sans-serif; font-size: 18px;
        letter-spacing: 2px; border: none; border-radius: 6px;
        padding: 10px 32px; width: 100%; transition: background 0.2s;
    }
    div.stButton > button[kind="primary"]:hover { background: #16a34a; color: #fff; }

    /* Pick'em grid */
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

    /* Parlay cards */
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

    /* +/- leg counter */
    .leg-display { font-family: 'Bebas Neue', sans-serif; font-size: 52px; color: #22c55e; line-height: 1; text-align: center; }
    .leg-label { font-size: 11px; opacity: 0.5; letter-spacing: 1px; text-align: center; margin-top: 2px; }

    /* Championship/futures cards */
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
    .futures-team { font-size: 12px; opacity: 0.6; }
    .futures-odds { font-family: 'Bebas Neue', sans-serif; font-size: 22px; color: #22c55e; }
    .futures-implied { font-size: 11px; opacity: 0.5; }
</style>
""", unsafe_allow_html=True)


# ── math helpers ──────────────────────────────────────────────────────────────
def normal_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

def classify_tier(p):
    if p >= 0.60: return "A"
    if p >= 0.55: return "B"
    if p >= 0.52: return "C"
    return "Pass"


# ── constants ─────────────────────────────────────────────────────────────────
SPREAD_STD_DEV    = 13.0
EDGE_THRESHOLD    = 2.0
COVER_PROB_THRESH = 0.55
PROVIDER          = "consensus"


# ── session state defaults ────────────────────────────────────────────────────
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
    season_type = st.radio(
        "Season Type",
        options=["regular", "postseason"],
        format_func=lambda x: "Regular Season" if x == "regular" else "Postseason / Bowls",
        horizontal=True,
    )
    week = st.slider(
        "Week",
        min_value=1, max_value=20,
        value=default_week if season_type == "regular" else 1,
        step=1,
        help="Postseason: Week 1 = early bowls, Week 2 = CFP quarters, Week 3 = CFP semis, Week 4 = National Championship",
    )
    st.markdown("### Model")
    home_field = st.number_input(
        "Home Field Advantage (pts)",
        min_value=0.0, max_value=10.0, value=2.5, step=0.5,
        help="Suggested: 2.5 pts. Bowl games are often neutral site — consider setting to 0.",
    )
    run_btn = st.button("RUN MODEL")


# ── header ────────────────────────────────────────────────────────────────────
season_label = f"WK {week}" if season_type == "regular" else f"POSTSEASON WK {week}"
st.markdown(f"# CFB — {year} {season_label}")
st.markdown("SP+ ratings vs. consensus market spreads · Edge-based ATS picks")
st.markdown("---")

if not run_btn:
    st.info("Configure parameters in the sidebar, then press **RUN MODEL**.")
    st.stop()

# ── imports ───────────────────────────────────────────────────────────────────
try:
    import cfbd
    from pathlib import Path
    import json
except ImportError:
    st.error("Run `python -m pip install cfbd` and restart.")
    st.stop()

if not bearer_token:
    st.error("No Bearer Token found. Set BEARER_TOKEN in Streamlit secrets.")
    st.stop()


# ── API setup ─────────────────────────────────────────────────────────────────
CACHE_DIR = Path("cfb_cache")
CACHE_DIR.mkdir(exist_ok=True)

def make_client():
    return cfbd.ApiClient(cfbd.Configuration(access_token=bearer_token))


# ── CFBD data fetchers ────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=3600)
def get_sp_ratings(yr):
    cache_file = CACHE_DIR / f"sp_{yr}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    ratings = {}
    with make_client() as client:
        for t in cfbd.RatingsApi(client).get_sp(year=yr):
            v = getattr(t, "rating", None)
            if v is not None:
                ratings[t.team] = float(v)
    cache_file.write_text(json.dumps(ratings))
    return ratings

@st.cache_data(show_spinner=False, ttl=3600)
def get_weekly_lines(yr, wk, stype):
    cache_file = CACHE_DIR / f"lines_{yr}_{stype}_wk{wk}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    with make_client() as client:
        games = cfbd.BettingApi(client).get_lines(year=yr, week=wk, season_type=stype)
    result = [{"home_team": g.home_team, "away_team": g.away_team,
               "lines": [{"provider": ln.provider, "spread": ln.spread} for ln in (g.lines or [])]}
              for g in games]
    cache_file.write_text(json.dumps(result))
    return result

@st.cache_data(show_spinner=False, ttl=86400)
def get_team_logos(yr):
    cache_file = CACHE_DIR / f"logos_{yr}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    logos = {}
    try:
        with make_client() as client:
            for t in cfbd.TeamsApi(client).get_fbs_teams(year=yr):
                if t.logos:
                    logos[t.school] = t.logos[0]
    except Exception:
        pass
    cache_file.write_text(json.dumps(logos))
    return logos


# ── Model ─────────────────────────────────────────────────────────────────────
def pick_line(game, pref):
    lines = game.get("lines") or []
    if not lines: return None
    for ln in lines:
        if (ln.get("provider") or "").lower() == pref.lower():
            return ln
    return lines[0]

def build_picks(yr, wk, stype, hf, std, prov):
    ratings = get_sp_ratings(yr)
    games   = get_weekly_lines(yr, wk, stype)
    rows    = []
    for game in games:
        ln = pick_line(game, prov)
        if ln is None or ln.get("spread") is None: continue
        home, away = game["home_team"], game["away_team"]
        if home not in ratings or away not in ratings: continue
        model_spread  = (ratings[home] - ratings[away]) + hf
        market_spread = float(ln["spread"])
        edge          = model_spread + market_spread
        z             = (-market_spread - model_spread) / std
        home_cover    = 1.0 - normal_cdf(z)
        if edge > 0:
            pick, cover, pick_team = f"HOME ({home})", home_cover, home
        elif edge < 0:
            pick, cover, pick_team = f"AWAY ({away})", 1.0 - home_cover, away
        else:
            pick, cover, pick_team = "NO EDGE", 0.5, ""
        rows.append({
            "Home": home, "Away": away, "pick_team": pick_team,
            "Provider": ln.get("provider"),
            "SP+ Home": round(ratings[home], 2), "SP+ Away": round(ratings[away], 2),
            "Model Spread": round(model_spread, 2), "Market Spread": market_spread,
            "Edge (pts)": round(edge, 2), "Cover Prob": round(cover, 3),
            "Tier": classify_tier(cover), "Pick": pick,
        })
    return pd.DataFrame(rows)


# ── Fetch ─────────────────────────────────────────────────────────────────────
with st.spinner("Fetching ratings, lines, and logos…"):
    try:
        df    = build_picks(year, week, season_type, home_field, SPREAD_STD_DEV, PROVIDER)
        logos = get_team_logos(year)
    except Exception as e:
        st.error(f"API error: {e}")
        st.stop()

if df.empty:
    st.warning("No games returned. Try adjusting year/week.")
    st.stop()

strong = df[
    (df["Edge (pts)"].abs() >= EDGE_THRESHOLD)
    & (df["Cover Prob"] >= COVER_PROB_THRESH)
    & (df["Tier"] != "Pass")
]

# ── Summary metrics ───────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Games",    len(df))
c2.metric("Strong Picks",   len(strong))
c3.metric("Tier A Picks",   len(df[df["Tier"] == "A"]))
c4.metric("Avg Cover Prob", f"{df['Cover Prob'].mean():.3f}")
st.markdown("---")


# ── Logo helper ───────────────────────────────────────────────────────────────
def logo_img(team, size=32):
    url = logos.get(team, "")
    if url:
        return f'<img src="{url}" width="{size}" height="{size}" style="object-fit:contain;vertical-align:middle;" />'
    initials = "".join(w[0] for w in team.split()[:2]).upper()
    return f'<span style="font-family:\'Bebas Neue\',sans-serif;font-size:{size//2}px;color:#64748b;">{initials}</span>'


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

    top12 = (df[df["Tier"] != "Pass"]
             .sort_values("Cover Prob", ascending=False)
             .head(12).reset_index(drop=True))

    if top12.empty:
        st.info("Not enough picks above Pass tier for a top 12.")
    else:
        cards_html = '<div class="pickem-grid">'
        for i, row in top12.iterrows():
            tier, home, away      = row["Tier"], row["Home"], row["Away"]
            pick_team, cover, edge = row["pick_team"], row["Cover Prob"], row["Edge (pts)"]
            spread                 = row["Market Spread"]
            spread_str = f"Spread: {spread:+.1f}" if spread else ""
            cards_html += (
                f'<div class="pickem-card tier-{tier}">'
                f'<div class="pickem-rank">#{i + 1}</div>'
                f'<div class="pickem-logos">{logo_img(away, 32)}<span class="pickem-vs">@</span>{logo_img(home, 32)}</div>'
                f'<div class="pickem-matchup">{away} @ {home}</div>'
                f'<div class="pickem-pick">&#10003; {pick_team}</div>'
                f'<div class="pickem-meta">'
                f'Cover Prob: <b style="color:#e2e8f0">{cover:.1%}</b> &nbsp;|&nbsp; '
                f'Edge: <b style="color:#e2e8f0">{edge:+.1f} pts</b> &nbsp;|&nbsp; '
                f'Tier: <b style="color:#e2e8f0">{tier}</b>'
                f'{"<br/>" + spread_str if spread_str else ""}'
                f'</div></div>'
            )
        cards_html += "</div>"
        st.markdown(cards_html, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("## 📋 All Games")
    tier_filter = st.multiselect("Filter by Tier", ["A","B","C","Pass"], default=["A","B","C","Pass"], key="tf1")
    filtered = df[df["Tier"].isin(tier_filter)] if tier_filter else df
    st.dataframe(
        filtered.drop(columns=["pick_team"]).sort_values("Edge (pts)", key=lambda s: s.abs(), ascending=False).reset_index(drop=True),
        use_container_width=True, height=min(50 + 35 * len(filtered), 600),
    )
    st.markdown("---")
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button("⬇️ All Games (CSV)", data=df.drop(columns=["pick_team"]).to_csv(index=False),
                           file_name=f"all_games_{year}_{season_type}_wk{week}.csv", mime="text/csv")
    with dl2:
        if not strong.empty:
            st.download_button("⬇️ Strong Picks (CSV)", data=strong.drop(columns=["pick_team"]).to_csv(index=False),
                               file_name=f"strong_picks_{year}_{season_type}_wk{week}.csv", mime="text/csv")


# ── TAB 2: Parlays ────────────────────────────────────────────────────────────
@st.fragment
def render_parlay_tab(df_inner, logos_inner):
    st.markdown("## 🎰 Team Parlays")
    st.caption("Built from Tier A & B picks · Combined prob = product of cover probs · Est. payout assumes −110 per leg")

    # Callbacks defined inside fragment so they trigger a fragment-only rerun
    def dec_legs():
        if st.session_state["parlay_legs"] > 2:
            st.session_state["parlay_legs"] -= 1

    def inc_legs():
        if st.session_state["parlay_legs"] < 6:
            st.session_state["parlay_legs"] += 1

    # +/- counter — narrow columns so buttons sit tight around the number
    col_minus, col_display, col_plus = st.columns([1, 1, 1])
    with col_minus:
        st.button(
            "−", key="legs_minus",
            on_click=dec_legs,
            use_container_width=True,
            disabled=(st.session_state["parlay_legs"] <= 2),
        )
    with col_display:
        st.markdown(
            f'<div class="leg-display">{st.session_state["parlay_legs"]}</div>'
            f'<div class="leg-label">LEGS</div>',
            unsafe_allow_html=True,
        )
    with col_plus:
        st.button("＋",
            key="legs_plus",
            on_click=inc_legs,
            use_container_width=True,
            disabled=(st.session_state["parlay_legs"] >= 6),
        )

    leg_count = st.session_state["parlay_legs"]
    pool_size = leg_count + 4

    parlay_pool = (
        df_inner[df_inner["Tier"].isin(["A", "B"]) & (df_inner["pick_team"] != "")]
        .sort_values("Cover Prob", ascending=False)
        .head(pool_size)
        .reset_index(drop=True)
    )

    if len(parlay_pool) < leg_count:
        st.info(f"Not enough Tier A/B picks for a {leg_count}-leg parlay. Try reducing legs or lowering thresholds.")
        return

    combos = list(itertools.combinations(parlay_pool.index, leg_count))
    parlay_rows = sorted(
        [{"joint_prob": round(parlay_pool.loc[list(c), "Cover Prob"].prod(), 4),
          "legs": parlay_pool.loc[list(c)]} for c in combos],
        key=lambda x: x["joint_prob"], reverse=True,
    )
    payout = round(((100 / 110) + 1) ** leg_count, 2)

    all_html = ""
    for i, p in enumerate(parlay_rows[:5]):
        legs_html = ""
        for _, leg in p["legs"].iterrows():
            lm = logos_inner.get(leg["pick_team"], "")
            logo_tag = (
                f'<img src="{lm}" width="20" height="20" style="object-fit:contain;vertical-align:middle;" />'
                if lm else ""
            )
            legs_html += (
                f'<div class="parlay-leg">'
                f'{logo_tag}&nbsp;<b>{leg["pick_team"]}</b> ATS'
                f'&nbsp;<span style="color:#64748b">({leg["Away"]} @ {leg["Home"]})</span>'
                f'&nbsp;&middot;&nbsp;Cover Prob: <b style="color:#facc15">{leg["Cover Prob"]:.1%}</b>'
                f'&nbsp;&middot;&nbsp;Edge: <b>{leg["Edge (pts)"]:+.1f} pts</b>'
                f'&nbsp;&middot;&nbsp;Tier {leg["Tier"]}'
                f'</div>'
            )
        all_html += (
            f'<div class="parlay-card">'
            f'<div class="parlay-title">Parlay #{i + 1}'
            f'&nbsp;<span style="font-size:14px;color:#64748b;font-family:\'IBM Plex Mono\',monospace;">'
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


# ── TAB 3: Championship Futures ───────────────────────────────────────────────
with tab3:
    st.markdown("## 🥇 National Championship Favorites")
    st.caption(f"Based on SP+ ratings through Week {week} · {year} season · Higher rating = stronger team")

    sp_ratings = get_sp_ratings(year)

    if not sp_ratings:
        st.warning("No SP+ ratings found for this year/week combination.")
    else:
        sp_df = (
            pd.DataFrame(list(sp_ratings.items()), columns=["Team", "SP+ Rating"])
            .sort_values("SP+ Rating", ascending=False)
            .reset_index(drop=True)
        )

        top_n_champ   = 25
        display_champ = sp_df.head(top_n_champ)

        # SP+ range for normalizing the bar width
        sp_max = display_champ["SP+ Rating"].max()
        sp_min = display_champ["SP+ Rating"].min()

        cards_html = '<div class="futures-grid">'
        for i, row in display_champ.iterrows():
            rank      = i + 1
            team      = row["Team"]
            rating    = row["SP+ Rating"]
            rank_class = {1: "rank-1", 2: "rank-2", 3: "rank-3"}.get(rank, "rank-other")
            medal      = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")
            logo_tag   = logo_img(team, 40)
            bar_pct    = int((rating - sp_min) / (sp_max - sp_min + 0.001) * 100) if sp_max != sp_min else 80
            cards_html += (
                f'<div class="futures-card {rank_class}">'
                f'<div class="futures-rank">{medal}</div>'
                f'{logo_tag}'
                f'<div class="futures-name">{team}</div>'
                f'<div class="futures-odds" style="font-size:20px;">{rating:+.1f}</div>'
                f'<div class="futures-implied">SP+ Rating</div>'
                f'<div style="margin-top:6px;background:#1e2330;border-radius:4px;height:4px;width:100%;">'
                f'<div style="background:#22c55e;border-radius:4px;height:4px;width:{bar_pct}%;"></div>'
                f'</div>'
                f'</div>'
            )
        cards_html += "</div>"
        st.markdown(cards_html, unsafe_allow_html=True)

        # st.markdown("---")
        # st.dataframe(
        #     display_champ.rename(columns={"SP+ Rating": "SP+ Rating (higher = better)"}).reset_index(drop=True),
        #     use_container_width=True, hide_index=True
        # )


# ── Heisman player stats fetcher ──────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=3600)
def get_player_stats(yr: int, wk: int) -> pd.DataFrame:
    """
    Pull cumulative season player stats through `wk` from CFBD.
    Returns a DataFrame with one row per player.
    """
    cache_file = CACHE_DIR / f"player_stats_{yr}_wk{wk}.json"
    if cache_file.exists():
        try:
            return pd.read_json(cache_file)
        except Exception:
            cache_file.unlink()   # corrupt cache — delete and re-fetch

    categories  = ["passing", "rushing", "receiving"]
    player_map  = {}   # keyed by (player_id, name, team)

    with make_client() as client:
        players_api = cfbd.PlayersApi(client)
        for cat in categories:
            try:
                stats = players_api.get_player_season_stats(
                    year=yr,
                    end_week=wk,
                    season_type="regular",
                    category=cat,
                )
            except Exception:
                continue

            for s in stats:
                # Newer cfbd library uses snake_case attributes
                pid   = getattr(s, "player_id",  None) or getattr(s, "id", None)
                name  = getattr(s, "player",     "") or getattr(s, "name", "")
                team  = getattr(s, "team",        "")
                stype = getattr(s, "stat_type",   "") or getattr(s, "type", "")
                val   = float(getattr(s, "stat",  0) or 0)

                key = (pid, name, team)
                if key not in player_map:
                    player_map[key] = {
                        "name": name, "team": team,
                        "pass_yds": 0, "pass_td": 0,
                        "rush_yds": 0, "rush_td": 0,
                        "rec_yds":  0, "rec_td":  0,
                    }

                # Map stat_type string → field
                field = {
                    ("passing",   "YDS"): "pass_yds",
                    ("passing",   "TD"):  "pass_td",
                    ("rushing",   "YDS"): "rush_yds",
                    ("rushing",   "TD"):  "rush_td",
                    ("receiving", "YDS"): "rec_yds",
                    ("receiving", "TD"):  "rec_td",
                }.get((cat, stype))

                if field:
                    player_map[key][field] += val

    if not player_map:
        return pd.DataFrame()

    df_out = pd.DataFrame(list(player_map.values()))
    df_out.to_json(cache_file)
    return df_out