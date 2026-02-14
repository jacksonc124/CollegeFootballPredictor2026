import math
import os
import itertools
from datetime import date
import streamlit as st
import pandas as pd
import json
from pathlib import Path

# ── CFB week helper ───────────────────────────────────────────────────────────
def get_current_cfb_week() -> int:
    today = date.today()
    season_start = date(today.year, 9, 1)
    if today < season_start:
        return 1
    # Continuous weeks: 1-14 Regular, 15+ Postseason
    return min((today - season_start).days // 7 + 1, 20)

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="CFB Betting Model", page_icon="🏈", layout="wide")

# ── styling (unchanged from previous) ─────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=IBM+Plex+Mono:wght@400;600&display=swap');
    html, body, [class*="css"] { font-family: 'IBM Plex Mono', monospace; }
    h1, h2, h3 { font-family: 'Bebas Neue', sans-serif; letter-spacing: 2px; }
    div.stButton > button[kind="primary"] {
        background: #22c55e; color: #0d0f14; font-family: 'Bebas Neue', sans-serif; 
        font-size: 18px; letter-spacing: 2px; border-radius: 6px; width: 100%;
    }
    .pickem-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }
    .pickem-card { background: var(--background-color); border: 1px solid var(--border-color); border-radius: 10px; padding: 14px; }
    .pickem-card.tier-A { border-left: 4px solid #22c55e; }
    .pickem-card.tier-B { border-left: 4px solid #facc15; }
    .pickem-card.tier-C { border-left: 4px solid #fb923c; }
</style>
""", unsafe_allow_html=True)

# ── constants & state ─────────────────────────────────────────────────────────
SPREAD_STD_DEV = 13.0
EDGE_THRESHOLD = 2.0
COVER_PROB_THRESH = 0.55
PROVIDER = "consensus"
CACHE_DIR = Path("cfb_cache")
CACHE_DIR.mkdir(exist_ok=True)

if "parlay_legs" not in st.session_state:
    st.session_state["parlay_legs"] = 3

try:
    bearer_token = st.secrets["BEARER_TOKEN"]
except:
    bearer_token = os.environ.get("BEARER_TOKEN", "")

# ── sidebar (CONTINUOUS WEEK SELECTOR) ────────────────────────────────────────
with st.sidebar:
    st.markdown("# 🏈 CFB MODEL")
    st.markdown("---")
    year = st.number_input("Year", min_value=2000, max_value=2030, value=date.today().year)
    
    # Continuous Week Selector
    current_wk = get_current_cfb_week()
    total_week = st.slider("Week Selection", 1, 20, value=current_wk, 
                           help="Weeks 1-14: Regular Season. Weeks 15-20: Postseason/Bowls/CFP.")
    
    # Logic to split the continuous week into API-friendly params
    if total_week <= 14:
        api_season_type = "regular"
        api_week = total_week
        st.info(f"Mode: Regular Season (Week {api_week})")
    else:
        api_season_type = "postseason"
        api_week = total_week - 14  # Week 15 becomes Postseason Week 1
        st.success(f"Mode: Postseason (API Week {api_week})")

    home_field = st.number_input("Home Field Advantage (pts)", 0.0, 10.0, 2.5, 0.5)
    run_btn = st.button("RUN MODEL", kind="primary")

# ── Logic & API (Refactored) ──────────────────────────────────────────────────
import cfbd

def normal_cdf(z): return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
def classify_tier(p):
    if p >= 0.60: return "A"
    if p >= 0.55: return "B"
    if p >= 0.52: return "C"
    return "Pass"

@st.cache_data(ttl=3600)
def fetch_data(yr, wk, stype):
    conf = cfbd.Configuration(access_token=bearer_token)
    with cfbd.ApiClient(conf) as client:
        # Ratings
        ratings = {t.team: float(t.rating) for t in cfbd.RatingsApi(client).get_sp(year=yr) if t.rating}
        # Lines
        games = cfbd.BettingApi(client).get_lines(year=yr, week=wk, season_type=stype)
        # Logos
        logos = {t.school: t.logos[0] for t in cfbd.TeamsApi(client).get_fbs_teams(year=yr) if t.logos}
    return ratings, games, logos

# ── Main UI ───────────────────────────────────────────────────────────────────
if run_btn:
    ratings, games, logos = fetch_data(year, api_week, api_season_type)
    
    rows = []
    for g in games:
        lns = g.lines or []
        ln = next((l for l in lns if l.provider.lower() == PROVIDER), lns[0] if lns else None)
        if not ln or ln.spread is None: continue
        
        home, away = g.home_team, g.away_team
        if home not in ratings or away not in ratings: continue
        
        model_spread = (ratings[home] - ratings[away]) + home_field
        market_spread = float(ln.spread)
        edge = model_spread + market_spread
        z = (-market_spread - model_spread) / SPREAD_STD_DEV
        prob = 1.0 - normal_cdf(z) if edge > 0 else normal_cdf(z)
        pick_team = home if edge > 0 else away
        
        rows.append({
            "Home": home, "Away": away, "pick_team": pick_team, "Tier": classify_tier(prob),
            "Model Spread": round(model_spread, 1), "Market": market_spread, 
            "Edge": round(abs(edge), 1), "Cover Prob": prob
        })
    
    df = pd.DataFrame(rows)

    # Tabs (HEISMAN REMOVED)
    tab1, tab2, tab3 = st.tabs(["🏆 Pick'em", "🎰 Parlays", "🥇 Power Rankings"])

    with tab1:
        st.markdown("### Top 12 ATS Picks")
        top12 = df.sort_values("Cover Prob", ascending=False).head(12)
        # Grid rendering... (omitted for brevity, same as previous version)
        st.dataframe(df.drop(columns="pick_team"), use_container_width=True)

    with tab2:
        st.markdown("### Suggested Parlays")
        # Logic for parlay combos... (omitted for brevity)

    with tab3:
        st.markdown("### SP+ Power Rankings")
        st.dataframe(pd.DataFrame(list(ratings.items()), columns=["Team", "SP+"]).sort_values("SP+", ascending=False))