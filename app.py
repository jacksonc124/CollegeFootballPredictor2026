import math
import os
import itertools
import requests
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
st.set_page_config(page_title="CFB Betting Model", page_icon="🏈", layout="wide")

# ── styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=IBM+Plex+Mono:wght@400;600&display=swap');
    html, body, [class*="css"] { font-family: 'IBM Plex Mono', monospace; }
    h1, h2, h3 { font-family: 'Bebas Neue', sans-serif; letter-spacing: 2px; }
    .stApp { background-color: #0d0f14; color: #e2e8f0; }
    section[data-testid="stSidebar"] { background-color: #13161e; border-right: 1px solid #1e2330; }
    [data-testid="metric-container"] {
        background: #13161e; border: 1px solid #1e2330;
        border-radius: 8px; padding: 12px 16px;
    }
    thead tr th {
        background-color: #1e2330 !important; color: #94a3b8 !important;
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 11px !important; letter-spacing: 1px;
    }
    div.stButton > button {
        background: #22c55e; color: #0d0f14;
        font-family: 'Bebas Neue', sans-serif; font-size: 18px;
        letter-spacing: 2px; border: none; border-radius: 6px;
        padding: 10px 32px; width: 100%; transition: background 0.2s;
    }
    div.stButton > button:hover { background: #16a34a; color: #fff; }
    .stTabs [data-baseweb="tab-list"] { background: #13161e; border-radius: 8px; padding: 4px; gap: 4px; }
    .stTabs [data-baseweb="tab"] {
        font-family: 'Bebas Neue', sans-serif; font-size: 16px;
        letter-spacing: 1px; color: #64748b; border-radius: 6px; padding: 8px 20px;
    }
    .stTabs [aria-selected="true"] { background: #1e2330 !important; color: #e2e8f0 !important; }

    /* Pick'em cards */
    .pickem-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; margin-top: 12px; }
    .pickem-card { background: #13161e; border: 1px solid #1e2330; border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; gap: 6px; }
    .pickem-card.tier-A { border-left: 4px solid #22c55e; }
    .pickem-card.tier-B { border-left: 4px solid #facc15; }
    .pickem-card.tier-C { border-left: 4px solid #fb923c; }
    .pickem-rank { font-family: 'Bebas Neue', sans-serif; font-size: 28px; color: #475569; line-height: 1; }
    .pickem-matchup { font-size: 13px; color: #94a3b8; }
    .pickem-pick { font-family: 'Bebas Neue', sans-serif; font-size: 20px; color: #e2e8f0; letter-spacing: 1px; }
    .pickem-meta { font-size: 11px; color: #64748b; }
    .pickem-logos { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
    .pickem-vs { font-size: 11px; color: #475569; }

    /* Parlay cards */
    .parlay-card { background: #13161e; border: 1px solid #22c55e44; border-radius: 10px; padding: 16px 20px; margin-bottom: 14px; }
    .parlay-title { font-family: 'Bebas Neue', sans-serif; font-size: 22px; color: #22c55e; letter-spacing: 1px; margin-bottom: 8px; }
    .parlay-leg { font-size: 13px; color: #cbd5e1; padding: 4px 0; border-bottom: 1px solid #1e2330; }
    .parlay-leg:last-child { border-bottom: none; }
    .parlay-prob { font-family: 'Bebas Neue', sans-serif; font-size: 18px; color: #facc15; margin-top: 10px; }

    /* Futures cards */
    .futures-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; margin-top: 12px; }
    .futures-card { background: #13161e; border: 1px solid #1e2330; border-radius: 10px; padding: 16px; display: flex; flex-direction: column; gap: 6px; }
    .futures-card.rank-1 { border-left: 4px solid #f59e0b; }
    .futures-card.rank-2 { border-left: 4px solid #94a3b8; }
    .futures-card.rank-3 { border-left: 4px solid #b45309; }
    .futures-card.rank-other { border-left: 4px solid #1e2330; }
    .futures-rank { font-family: 'Bebas Neue', sans-serif; font-size: 26px; color: #475569; line-height: 1; }
    .futures-name { font-family: 'Bebas Neue', sans-serif; font-size: 20px; color: #e2e8f0; letter-spacing: 1px; }
    .futures-team { font-size: 12px; color: #94a3b8; }
    .futures-odds { font-family: 'Bebas Neue', sans-serif; font-size: 22px; color: #22c55e; }
    .futures-implied { font-size: 11px; color: #64748b; }
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

def american_to_implied(odds: int) -> float:
    if odds > 0:
        return round(100 / (odds + 100) * 100, 1)
    else:
        return round(abs(odds) / (abs(odds) + 100) * 100, 1)

def fmt_odds(odds: int) -> str:
    return f"+{odds}" if odds > 0 else str(odds)


# ── constants ─────────────────────────────────────────────────────────────────
SPREAD_STD_DEV    = 13.0
EDGE_THRESHOLD    = 2.0
COVER_PROB_THRESH = 0.55
PROVIDER          = "consensus"
SEASON_TYPE       = "regular"


# ── secrets ───────────────────────────────────────────────────────────────────
try:
    bearer_token = st.secrets["BEARER_TOKEN"]
except Exception:
    bearer_token = os.environ.get("BEARER_TOKEN", "")

try:
    odds_api_key = st.secrets["ODDS_API_KEY"]
except Exception:
    odds_api_key = os.environ.get("ODDS_API_KEY", "")


# ── sidebar ───────────────────────────────────────────────────────────────────
default_year, default_week = get_current_cfb_week()

with st.sidebar:
    st.markdown("# 🏈 CFB MODEL")
    st.markdown("---")
    st.markdown("### Season")
    year = st.number_input("Year", min_value=2000, max_value=2030, value=default_year, step=1)
    week = st.number_input("Week", min_value=1,    max_value=20,   value=default_week, step=1)
    st.markdown("### Model")
    home_field = st.number_input("Home Field Advantage (pts)", min_value=0.0, max_value=10.0, value=2.5, step=0.5, help="Suggested: 2.5 pts")
    run_btn = st.button("RUN MODEL")


# ── header ────────────────────────────────────────────────────────────────────
st.markdown(f"# CFB BETTING MODEL — {year} WK {week}")
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
    cache_file = CACHE_DIR / f"lines_{yr}_wk{wk}.json"
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


# ── The Odds API fetchers ─────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=3600)
def get_futures_odds(market: str) -> list | str:
    """
    Fetch NCAAF futures from The Odds API.
    Uses the /v4/sports/.../events + /v4/sports/.../events/{id}/odds endpoint
    which is the correct endpoint for futures/outrights.
    Returns list of { name, team, odds, implied_prob } or an error string.
    """
    if not odds_api_key:
        return []

    # Futures live under the outrights sport key for NCAAF
    sport_key = "americanfootball_ncaaf_championship_winner" if "championship" in market else "americanfootball_ncaaf_heisman_trophy_winner"

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        "apiKey":     odds_api_key,
        "regions":    "us",
        "markets":    "outrights",
        "oddsFormat": "american",
        "bookmakers": "draftkings",
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
    except Exception as e:
        return f"Request failed: {e}"

    # API error response is a dict with 'message' key
    if isinstance(data, dict):
        return data.get("message", "Unknown API error")

    if not isinstance(data, list) or len(data) == 0:
        return "no_data"

    outcomes = []
    for event in data:
        if not isinstance(event, dict):
            continue
        for bm in event.get("bookmakers", []):
            for mkt in bm.get("markets", []):
                for o in mkt.get("outcomes", []):
                    name = o.get("name", "")
                    odds = o.get("price", 0)
                    desc = o.get("description", "")
                    if name and isinstance(odds, (int, float)):
                        outcomes.append({
                            "name":         name,
                            "team":         desc,
                            "odds":         int(odds),
                            "implied_prob": american_to_implied(int(odds)),
                        })

    if not outcomes:
        return "no_data"

    # De-dupe by name, keep best odds
    seen = {}
    for o in outcomes:
        key = o["name"]
        if key not in seen or o["odds"] < seen[key]["odds"]:
            seen[key] = o

    return sorted(seen.values(), key=lambda x: x["odds"])


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
        df    = build_picks(year, week, SEASON_TYPE, home_field, SPREAD_STD_DEV, PROVIDER)
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
tab1, tab2, tab3, tab4 = st.tabs([
    "🏆  CBS Pick'em Top 12",
    "🎰  3-Team Parlays",
    "🥇  Championship Futures",
    "🏅  Heisman Favorites",
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
                           file_name=f"all_games_{year}_wk{week}.csv", mime="text/csv")
    with dl2:
        if not strong.empty:
            st.download_button("⬇️ Strong Picks (CSV)", data=strong.drop(columns=["pick_team"]).to_csv(index=False),
                               file_name=f"strong_picks_{year}_wk{week}.csv", mime="text/csv")


# ── TAB 2: Parlays ────────────────────────────────────────────────────────────
with tab2:
    st.markdown("## 🎰 Suggested Parlays")
    st.caption("Built from Tier A & B picks · Combined prob = product of cover probs · Est. payout assumes −110 per leg")

    leg_count = st.slider("Number of legs", min_value=2, max_value=6, value=3, step=1, key="parlay_legs")

    # Pool size: need enough picks to form meaningful combos — use top (leg_count + 4)
    pool_size  = leg_count + 4
    parlay_pool = (df[df["Tier"].isin(["A","B"]) & (df["pick_team"] != "")]
                   .sort_values("Cover Prob", ascending=False)
                   .head(pool_size).reset_index(drop=True))

    if len(parlay_pool) < leg_count:
        st.info(f"Not enough Tier A/B picks to build {leg_count}-team parlays. Try lowering your thresholds or reducing leg count.")
    else:
        combos = list(itertools.combinations(parlay_pool.index, leg_count))
        parlay_rows = sorted(
            [{"joint_prob": round(parlay_pool.loc[list(c), "Cover Prob"].prod(), 4),
              "legs": parlay_pool.loc[list(c)]} for c in combos],
            key=lambda x: x["joint_prob"], reverse=True
        )

        # Payout at -110 per leg: ((100/110) + 1)^n
        payout = round(((100 / 110) + 1) ** leg_count, 2)

        all_html = ""
        for i, p in enumerate(parlay_rows[:5]):
            legs_html = ""
            for _, leg in p["legs"].iterrows():
                legs_html += (
                    f'<div class="parlay-leg">'
                    f'{logo_img(leg["pick_team"], 20)}&nbsp;<b>{leg["pick_team"]}</b> ATS'
                    f'&nbsp;<span style="color:#64748b">({leg["Away"]} @ {leg["Home"]})</span>'
                    f'&nbsp;&middot;&nbsp;Cover Prob: <b style="color:#facc15">{leg["Cover Prob"]:.1%}</b>'
                    f'&nbsp;&middot;&nbsp;Edge: <b>{leg["Edge (pts)"]:+.1f} pts</b>'
                    f'&nbsp;&middot;&nbsp;Tier {leg["Tier"]}'
                    f'</div>'
                )
            all_html += (
                f'<div class="parlay-card">'
                f'<div class="parlay-title">Parlay #{i + 1} &nbsp;'
                f'<span style="font-size:14px;color:#64748b;font-family:\'IBM Plex Mono\',monospace;">'
                f'{leg_count}-leg</span></div>'
                f'{legs_html}'
                f'<div class="parlay-prob">'
                f'Combined Probability: {p["joint_prob"]:.1%}'
                f'&nbsp;&middot;&nbsp;Est. Payout (&minus;110 each): ~{payout}x'
                f'</div></div>'
            )
        st.markdown(all_html, unsafe_allow_html=True)


# ── TAB 3: Championship Futures ───────────────────────────────────────────────
with tab3:
    st.markdown("## 🥇 National Championship Futures")
    st.caption("Live odds via The Odds API (DraftKings) · Sorted by implied probability")

    if not odds_api_key:
        st.warning("No ODDS_API_KEY found in secrets. Add your free key from [the-odds-api.com](https://the-odds-api.com) to see live futures.")
    else:
        with st.spinner("Fetching championship odds…"):
            champ_odds = get_futures_odds("championship_winner")

        if isinstance(champ_odds, str):
            if champ_odds == "no_data":
                st.info("No championship odds are available yet — check back once the season is underway.")
            else:
                st.error(f"Odds API error: {champ_odds}")
        elif not champ_odds:
            st.error("Could not fetch championship odds. Check your ODDS_API_KEY or try again later.")
        else:
            top_n = st.slider("Show top N teams", min_value=5, max_value=min(30, len(champ_odds)), value=12, step=1, key="champ_slider")
            display = champ_odds[:top_n]

            cards_html = '<div class="futures-grid">'
            for i, item in enumerate(display):
                rank_class = {0: "rank-1", 1: "rank-2", 2: "rank-3"}.get(i, "rank-other")
                medal      = {0: "🥇", 1: "🥈", 2: "🥉"}.get(i, f"#{i+1}")
                logo_tag   = logo_img(item["name"], 40)
                cards_html += (
                    f'<div class="futures-card {rank_class}">'
                    f'<div class="futures-rank">{medal}</div>'
                    f'{logo_tag}'
                    f'<div class="futures-name">{item["name"]}</div>'
                    f'<div class="futures-odds">{fmt_odds(item["odds"])}</div>'
                    f'<div class="futures-implied">Implied: {item["implied_prob"]}%</div>'
                    f'</div>'
                )
            cards_html += "</div>"
            st.markdown(cards_html, unsafe_allow_html=True)

            st.markdown("---")
            champ_df = pd.DataFrame(display).rename(columns={
                "name": "Team", "odds": "American Odds",
                "implied_prob": "Implied Prob (%)", "team": "Description"
            }).drop(columns=["Description"], errors="ignore")
            champ_df["American Odds"] = champ_df["American Odds"].apply(fmt_odds)
            st.dataframe(champ_df, use_container_width=True, hide_index=True)


# ── TAB 4: Heisman ───────────────────────────────────────────────────────────
with tab4:
    st.markdown("## 🏅 Heisman Trophy Favorites")
    st.caption("Live odds via The Odds API (DraftKings) · Sorted by implied probability")

    if not odds_api_key:
        st.warning("No ODDS_API_KEY found in secrets. Add your free key from [the-odds-api.com](https://the-odds-api.com) to see live futures.")
    else:
        with st.spinner("Fetching Heisman odds…"):
            heisman_odds = get_futures_odds("heisman_trophy_winner")

        if isinstance(heisman_odds, str):
            if heisman_odds == "no_data":
                st.info("No Heisman odds are available yet — check back once the season is underway.")
            else:
                st.error(f"Odds API error: {heisman_odds}")
        elif not heisman_odds:
            st.error("Could not fetch Heisman odds. Check your ODDS_API_KEY or try again later.")
        else:
            top_n_h = st.slider("Show top N players", min_value=5, max_value=min(30, len(heisman_odds)), value=12, step=1, key="heisman_slider")
            display_h = heisman_odds[:top_n_h]

            cards_html = '<div class="futures-grid">'
            for i, item in enumerate(display_h):
                rank_class = {0: "rank-1", 1: "rank-2", 2: "rank-3"}.get(i, "rank-other")
                medal      = {0: "🥇", 1: "🥈", 2: "🥉"}.get(i, f"#{i+1}")
                team_tag   = f'<div class="futures-team">{item["team"]}</div>' if item.get("team") else ""
                cards_html += (
                    f'<div class="futures-card {rank_class}">'
                    f'<div class="futures-rank">{medal}</div>'
                    f'<div class="futures-name">{item["name"]}</div>'
                    f'{team_tag}'
                    f'<div class="futures-odds">{fmt_odds(item["odds"])}</div>'
                    f'<div class="futures-implied">Implied: {item["implied_prob"]}%</div>'
                    f'</div>'
                )
            cards_html += "</div>"
            st.markdown(cards_html, unsafe_allow_html=True)

            st.markdown("---")
            heisman_df = pd.DataFrame(display_h).rename(columns={
                "name": "Player", "team": "Team",
                "odds": "American Odds", "implied_prob": "Implied Prob (%)"
            })
            heisman_df["American Odds"] = heisman_df["American Odds"].apply(fmt_odds)
            st.dataframe(heisman_df, use_container_width=True, hide_index=True)