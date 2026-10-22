"""
Pure presentation helpers shared across app.py and the tabs/ modules — colors/constants,
small formatting functions, and the parlay leg-pool builder. Nothing here imports streamlit
or touches any of app.py's runtime-fetched state (df, logos, etc.), so every function is
testable in isolation (see tests/test_ui_helpers.py) without needing a running Streamlit
session or network access.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

import model

CENTRAL = ZoneInfo("America/Chicago")

# Single source of truth for the app's color language (60-30-10 discipline): tier colors
# mean ONE thing — pick confidence — and appear nowhere else. ACCENT is the neutral color
# for UI chrome (buttons, headline numbers that aren't a tier signal) so it never competes
# with tier meaning. These are duplicated into CSS (Vega-Lite charts and pandas Styler can't
# read CSS custom properties, so a single templated source isn't practical) — keep both in
# sync if changing.
TIER_COLORS = {"A": "#22c55e", "B": "#facc15", "C": "#fb923c", "Pass": "#6b7280"}
ACCENT = "#38bdf8"

# Win/loss is a different axis of meaning than tier confidence (a graded result, not a
# pick's confidence), so it gets its own green/red rather than reusing TIER_COLORS —
# they never appear in the same table, so there's no risk of the two meanings colliding.
OUTCOME_COLORS = {"win": "#22c55e", "loss": "#ef4444"}

# Raw model.py columns → friendly UI headers, shared by every dataframe display in the app.
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


def format_game_date(iso_start_date, start_time_tbd) -> str:
    """Format a UTC ISO start_date (from get_game_info) as a CT date, with time unless TBD."""
    if not iso_start_date:
        return ""
    try:
        dt_ct = datetime.fromisoformat(iso_start_date).astimezone(CENTRAL)
    except ValueError:
        return ""
    date_part = dt_ct.strftime("%b %d")
    if start_time_tbd:
        return date_part
    time_part = dt_ct.strftime("%I:%M %p").lstrip("0")
    return f"{date_part}, {time_part} CT"


def tier_row_css(tier: str) -> str:
    """Full-row background tint for a tier value, shared by every dataframe Styler that has
    a Tier column — one definition so 'what a tinted row means' stays consistent app-wide."""
    color = TIER_COLORS.get(tier, "")
    return f"background-color: {color}22" if color and tier != "Pass" else ""


def outcome_row_css(outcome: str) -> str:
    """Full-row background tint for a graded pick's outcome (win/loss); push/pending get no tint."""
    color = OUTCOME_COLORS.get(outcome, "")
    return f"background-color: {color}22" if color else ""


def build_parlay_leg_pool(df_inner: pd.DataFrame, ats_tiers=("A", "B"),
                          ml_edge_threshold: float = model.ML_EDGE_THRESHOLD) -> pd.DataFrame:
    """
    Unify ATS picks (from ats_tiers) and moneyline picks with edge >= ml_edge_threshold
    into one candidate-leg pool, so parlays can mix bet types. Each leg keeps its
    originating (home, away) game so combos can be filtered to one leg per game
    (see tabs/parlays.py). Pass ats_tiers=() or ml_edge_threshold=inf to exclude a
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


# ── CSS (60-30-10 color discipline — see TIER_COLORS/ACCENT above; keep literal hexes in
# sync with those if changing, since Vega-Lite charts and pandas Styler can't read CSS
# custom properties) ────────────────────────────────────────────────────────────────────
STYLES = """
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
    .today-live {
        font-size: 12px; font-weight: 600; margin-top: 4px; padding: 3px 8px;
        border-radius: 4px; display: inline-block;
    }
    .today-live.status-live { background: #ef444422; color: #ef4444; }
    .today-live.status-final-win { background: #22c55e22; color: #22c55e; }
    .today-live.status-final-loss { background: #ef444422; color: #ef4444; }
    .today-live.status-final-push { background: rgba(128,128,128,0.15); color: #6b7280; }
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
"""
