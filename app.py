import math
import os
import itertools
from datetime import date
import streamlit as st
import pandas as pd


# ── current CFB week helper ───────────────────────────────────────────────────
# CFB regular season starts ~Sep 1; each week is 7 days.
def get_current_cfb_week() -> tuple:
    today        = date.today()
    current_year = today.year
    season_start = date(current_year, 9, 1)
    if today < season_start:
        # Offseason — show most recent completed season week 1
        return current_year - 1, 1
    delta_days = (today - season_start).days
    week = min((delta_days // 7) + 1, 15)
    return current_year, week

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CFB Betting Model",
    page_icon="🏈",
    layout="wide",
)

# ── styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=IBM+Plex+Mono:wght@400;600&display=swap');

    html, body, [class*="css"] { font-family: 'IBM Plex Mono', monospace; }
    h1, h2, h3 { font-family: 'Bebas Neue', sans-serif; letter-spacing: 2px; }
    .stApp { background-color: #0d0f14; color: #e2e8f0; }

    section[data-testid="stSidebar"] {
        background-color: #13161e;
        border-right: 1px solid #1e2330;
    }
    [data-testid="metric-container"] {
        background: #13161e;
        border: 1px solid #1e2330;
        border-radius: 8px;
        padding: 12px 16px;
    }
    thead tr th {
        background-color: #1e2330 !important;
        color: #94a3b8 !important;
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 11px !important;
        letter-spacing: 1px;
    }
    div.stButton > button {
        background: #22c55e; color: #0d0f14;
        font-family: 'Bebas Neue', sans-serif;
        font-size: 18px; letter-spacing: 2px;
        border: none; border-radius: 6px;
        padding: 10px 32px; width: 100%;
        transition: background 0.2s;
    }
    div.stButton > button:hover { background: #16a34a; color: #fff; }

    /* Pick'em card grid */
    .pickem-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
        gap: 14px;
        margin-top: 12px;
    }
    .pickem-card {
        background: #13161e;
        border: 1px solid #1e2330;
        border-radius: 10px;
        padding: 14px 16px;
        display: flex;
        flex-direction: column;
        gap: 6px;
    }
    .pickem-card.tier-A { border-left: 4px solid #22c55e; }
    .pickem-card.tier-B { border-left: 4px solid #facc15; }
    .pickem-card.tier-C { border-left: 4px solid #fb923c; }
    .pickem-rank {
        font-family: 'Bebas Neue', sans-serif;
        font-size: 28px;
        color: #475569;
        line-height: 1;
    }
    .pickem-matchup { font-size: 13px; color: #94a3b8; }
    .pickem-pick {
        font-family: 'Bebas Neue', sans-serif;
        font-size: 20px;
        color: #e2e8f0;
        letter-spacing: 1px;
    }
    .pickem-meta { font-size: 11px; color: #64748b; }
    .pickem-logos {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 4px;
    }
    .pickem-logos img { width: 32px; height: 32px; object-fit: contain; border-radius: 4px; }
    .pickem-vs { font-size: 11px; color: #475569; }

    /* Parlay cards */
    .parlay-card {
        background: #13161e;
        border: 1px solid #22c55e44;
        border-radius: 10px;
        padding: 16px 20px;
        margin-bottom: 14px;
    }
    .parlay-title {
        font-family: 'Bebas Neue', sans-serif;
        font-size: 22px;
        color: #22c55e;
        letter-spacing: 1px;
        margin-bottom: 8px;
    }
    .parlay-leg {
        font-size: 13px;
        color: #cbd5e1;
        padding: 4px 0;
        border-bottom: 1px solid #1e2330;
    }
    .parlay-leg:last-child { border-bottom: none; }
    .parlay-prob {
        font-family: 'Bebas Neue', sans-serif;
        font-size: 18px;
        color: #facc15;
        margin-top: 10px;
    }
</style>
""", unsafe_allow_html=True)


# ── math helpers ──────────────────────────────────────────────────────────────

def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def classify_tier(cover_prob: float) -> str:
    if cover_prob >= 0.60:   return "A"
    elif cover_prob >= 0.55: return "B"
    elif cover_prob >= 0.52: return "C"
    return "Pass"


# ── fixed model constants (not exposed to UI) ─────────────────────────────────
SPREAD_STD_DEV    = 13.0
EDGE_THRESHOLD    = 2.0
COVER_PROB_THRESH = 0.55
PROVIDER          = "consensus"
SEASON_TYPE       = "regular"

# ── bearer token from Streamlit secrets ───────────────────────────────────────
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
    week = st.number_input("Week", min_value=1,    max_value=20,   value=default_week, step=1)

    st.markdown("### Model")
    home_field = st.number_input(
        "Home Field Advantage (pts)",
        min_value=0.0, max_value=10.0, value=2.5, step=0.5,
        help="Suggested: 2.5 pts"
    )

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
    st.error("No Bearer Token found. Make sure BEARER_TOKEN is set in your Streamlit secrets.")
    st.stop()

# ── API setup ─────────────────────────────────────────────────────────────────

CACHE_DIR = Path("cfb_cache")
CACHE_DIR.mkdir(exist_ok=True)


def make_client():
    return cfbd.ApiClient(cfbd.Configuration(access_token=bearer_token))


# ── data fetchers ─────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False, ttl=3600)
def get_sp_ratings(yr: int) -> dict:
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
def get_weekly_lines(yr: int, wk: int, stype: str) -> list:
    cache_file = CACHE_DIR / f"lines_{yr}_wk{wk}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    with make_client() as client:
        games = cfbd.BettingApi(client).get_lines(year=yr, week=wk, season_type=stype)
    result = [{
        "home_team": g.home_team,
        "away_team": g.away_team,
        "lines": [{"provider": ln.provider, "spread": ln.spread} for ln in (g.lines or [])],
    } for g in games]
    cache_file.write_text(json.dumps(result))
    return result


@st.cache_data(show_spinner=False, ttl=86400)
def get_team_logos(yr: int) -> dict:
    """Returns { team_name: logo_url }"""
    cache_file = CACHE_DIR / f"logos_{yr}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    logos = {}
    try:
        with make_client() as client:
            teams = cfbd.TeamsApi(client).get_fbs_teams(year=yr)
        for t in teams:
            if t.logos:
                logos[t.school] = t.logos[0]
    except Exception:
        pass
    cache_file.write_text(json.dumps(logos))
    return logos


def pick_line(game: dict, pref: str):
    lines = game.get("lines") or []
    if not lines:
        return None
    for ln in lines:
        if (ln.get("provider") or "").lower() == pref.lower():
            return ln
    return lines[0]


# ── model ─────────────────────────────────────────────────────────────────────

def build_picks(yr, wk, stype, hf, std, prov):
    ratings = get_sp_ratings(yr)
    games   = get_weekly_lines(yr, wk, stype)
    rows    = []

    for game in games:
        ln = pick_line(game, prov)
        if ln is None or ln.get("spread") is None:
            continue
        home, away = game["home_team"], game["away_team"]
        if home not in ratings or away not in ratings:
            continue

        model_spread  = (ratings[home] - ratings[away]) + hf
        market_spread = float(ln["spread"])
        edge          = model_spread + market_spread

        z          = (-market_spread - model_spread) / std
        home_cover = 1.0 - normal_cdf(z)

        if edge > 0:
            pick, cover, pick_team = f"HOME ({home})", home_cover, home
        elif edge < 0:
            pick, cover, pick_team = f"AWAY ({away})", 1.0 - home_cover, away
        else:
            pick, cover, pick_team = "NO EDGE", 0.5, ""

        rows.append({
            "Home":          home,
            "Away":          away,
            "pick_team":     pick_team,
            "Provider":      ln.get("provider"),
            "SP+ Home":      round(ratings[home], 2),
            "SP+ Away":      round(ratings[away], 2),
            "Model Spread":  round(model_spread, 2),
            "Market Spread": market_spread,
            "Edge (pts)":    round(edge, 2),
            "Cover Prob":    round(cover, 3),
            "Tier":          classify_tier(cover),
            "Pick":          pick,
        })

    return pd.DataFrame(rows)


# ── fetch ─────────────────────────────────────────────────────────────────────

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

# ── summary metrics ───────────────────────────────────────────────────────────

strong = df[
    (df["Edge (pts)"].abs() >= EDGE_THRESHOLD)
    & (df["Cover Prob"] >= COVER_PROB_THRESH)
    & (df["Tier"] != "Pass")
]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Games",    len(df))
c2.metric("Strong Picks",   len(strong))
c3.metric("Tier A Picks",   len(df[df["Tier"] == "A"]))
c4.metric("Avg Cover Prob", f"{df['Cover Prob'].mean():.3f}")

st.markdown("---")


# ── logo helper ───────────────────────────────────────────────────────────────

def logo_img(team: str, size: int = 32) -> str:
    url = logos.get(team, "")
    if url:
        return f'<img src="{url}" width="{size}" height="{size}" style="object-fit:contain;vertical-align:middle;" />'
    initials = "".join(w[0] for w in team.split()[:2]).upper()
    return f'<span style="font-family:\'Bebas Neue\',sans-serif;font-size:{size // 2}px;color:#64748b;">{initials}</span>'


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — CBS PICK'EM TOP 12 (ATS)
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("## 🏆 CBS Pick'em — Top 12 ATS Picks")
st.caption("Ranked by cover probability · Against the spread")

top12 = (
    df[df["Tier"] != "Pass"]
    .sort_values("Cover Prob", ascending=False)
    .head(12)
    .reset_index(drop=True)
)

if top12.empty:
    st.info("Not enough picks above Pass tier for a top 12.")
else:
    cards_html = '<div class="pickem-grid">'
    for i, row in top12.iterrows():
        tier      = row["Tier"]
        home      = row["Home"]
        away      = row["Away"]
        pick_team = row["pick_team"]
        cover     = row["Cover Prob"]
        edge      = row["Edge (pts)"]
        spread    = row["Market Spread"]

        spread_str = f"Spread: {spread:+.1f}" if spread else ""
        home_logo  = logo_img(home, 32)
        away_logo  = logo_img(away, 32)

        cards_html += (
            f'<div class="pickem-card tier-{tier}">'
            f'<div class="pickem-rank">#{i + 1}</div>'
            f'<div class="pickem-logos">{away_logo}<span class="pickem-vs">@</span>{home_logo}</div>'
            f'<div class="pickem-matchup">{away} @ {home}</div>'
            f'<div class="pickem-pick">&#10003; {pick_team}</div>'
            f'<div class="pickem-meta">'
            f'Cover Prob: <b style="color:#e2e8f0">{cover:.1%}</b> &nbsp;|&nbsp; '
            f'Edge: <b style="color:#e2e8f0">{edge:+.1f} pts</b> &nbsp;|&nbsp; '
            f'Tier: <b style="color:#e2e8f0">{tier}</b>'
            f'{"<br/>" + spread_str if spread_str else ""}'
            f'</div>'
            f'</div>'
        )
    cards_html += "</div>"
    st.markdown(cards_html, unsafe_allow_html=True)

st.markdown("---")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — 3-TEAM PARLAY SUGGESTIONS
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("## 🎰 Suggested 3-Team Parlays")
st.caption("Built from Tier A & B picks · Combined prob = product of individual cover probs · Est. payout assumes −110 per leg")

parlay_pool = (
    df[df["Tier"].isin(["A", "B"]) & (df["pick_team"] != "")]
    .sort_values("Cover Prob", ascending=False)
    .head(8)
    .reset_index(drop=True)
)

if len(parlay_pool) < 3:
    st.info("Not enough Tier A/B picks to build parlays. Try lowering your thresholds.")
else:
    combos = list(itertools.combinations(parlay_pool.index, 3))
    parlay_rows = []
    for combo in combos:
        legs = parlay_pool.loc[list(combo)]
        parlay_rows.append({
            "joint_prob": round(legs["Cover Prob"].prod(), 4),
            "legs":       legs,
        })
    parlay_rows.sort(key=lambda x: x["joint_prob"], reverse=True)

    # Approx payout at -110 per leg: (100/110 + 1)^3 ≈ 6x
    payout = round(((100 / 110) + 1) ** 3, 2)

    # Build entire parlay section as one HTML block
    all_parlays_html = ""
    for i, p in enumerate(parlay_rows[:5]):
        joint = p["joint_prob"]
        legs  = p["legs"]

        legs_html = ""
        for _, leg in legs.iterrows():
            lm = logo_img(leg["pick_team"], 20)
            legs_html += (
                f'<div class="parlay-leg">'
                f'{lm}&nbsp;<b>{leg["pick_team"]}</b> ATS'
                f'&nbsp;<span style="color:#64748b">({leg["Away"]} @ {leg["Home"]})</span>'
                f'&nbsp;&middot;&nbsp;Cover Prob: <b style="color:#facc15">{leg["Cover Prob"]:.1%}</b>'
                f'&nbsp;&middot;&nbsp;Edge: <b>{leg["Edge (pts)"]:+.1f} pts</b>'
                f'&nbsp;&middot;&nbsp;Tier {leg["Tier"]}'
                f'</div>'
            )

        all_parlays_html += (
            f'<div class="parlay-card">'
            f'<div class="parlay-title">Parlay #{i + 1}</div>'
            f'{legs_html}'
            f'<div class="parlay-prob">'
            f'Combined Probability: {joint:.1%}'
            f'&nbsp;&middot;&nbsp;Est. Payout (&minus;110 each): ~{payout}x'
            f'</div>'
            f'</div>'
        )

    st.markdown(all_parlays_html, unsafe_allow_html=True)

st.markdown("---")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — STRONG PICKS TABLE
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("## ⚡ Strong Picks")
if strong.empty:
    st.info("No picks meet the current thresholds.")
else:
    st.dataframe(
        strong.drop(columns=["pick_team"]).sort_values("Cover Prob", ascending=False).reset_index(drop=True),
        use_container_width=True,
        height=min(50 + 35 * len(strong), 500),
    )

st.markdown("---")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — ALL GAMES TABLE
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("## 📋 All Games")

tier_filter = st.multiselect(
    "Filter by Tier", options=["A", "B", "C", "Pass"],
    default=["A", "B", "C", "Pass"]
)
filtered = df[df["Tier"].isin(tier_filter)] if tier_filter else df

st.dataframe(
    filtered.drop(columns=["pick_team"]).sort_values("Edge (pts)", key=lambda s: s.abs(), ascending=False).reset_index(drop=True),
    use_container_width=True,
    height=min(50 + 35 * len(filtered), 600),
)

st.markdown("---")


# ── downloads ─────────────────────────────────────────────────────────────────

dl1, dl2 = st.columns(2)
with dl1:
    st.download_button(
        "⬇️ Download All Games (CSV)",
        data=df.drop(columns=["pick_team"]).to_csv(index=False),
        file_name=f"all_games_{year}_wk{week}.csv",
        mime="text/csv",
    )
with dl2:
    if not strong.empty:
        st.download_button(
            "⬇️ Download Strong Picks (CSV)",
            data=strong.drop(columns=["pick_team"]).to_csv(index=False),
            file_name=f"strong_picks_{year}_wk{week}.csv",
            mime="text/csv",
        )