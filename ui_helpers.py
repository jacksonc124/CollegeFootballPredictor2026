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


def tier_badge_text_color(tier: str) -> str:
    """Pass tier's gray (#6b7280) is too mid-toned for dark text to read well on — every
    other tier color (green/yellow/orange) is bright enough that dark text always has
    good contrast. Shared by the tier badge and by the 'pick' flag on a highlighted logo,
    since both paint this same text color onto this same background color."""
    return "#f3f4f6" if tier == "Pass" else "#111827"


def team_slot_html(name: str, chip_html: str, is_pick: bool, tier_color: str = "") -> str:
    """One side of a matchup's team row: a logo chip plus its name, with a '✓ Pick' flag
    and a tier-colored glow around the chip when this is the side the model picked. The
    chip itself (grayscale'd or not) is rendered by the caller's logo_img — this only adds
    the label/flag chrome, so which team is 'dimmed' is decided once, by the caller, and
    reflected consistently in both the chip's own filter and this slot's highlight."""
    if not is_pick:
        return f'<div class="team-slot">{chip_html}<span class="team-slot-name">{name}</span></div>'
    color = tier_color or ACCENT
    return (
        f'<div class="team-slot is-pick" style="--pick-color:{color};">'
        f'<span class="pick-flag" style="background:{color};">&#10003; Pick</span>'
        f'{chip_html}<span class="team-slot-name">{name}</span></div>'
    )


def team_row_html(away_slot_html: str, home_slot_html: str, at_label: str = "@") -> str:
    """Wraps two team_slot_html() results into one matchup row with a separator between
    them ('@' for a true home/away game, 'vs' when the caller knows it's neutral-site)."""
    return f'<div class="team-row">{away_slot_html}<div class="at-sep">{at_label}</div>{home_slot_html}</div>'


def stat_row_html(tiles) -> str:
    """The headline numbers under a matchup's team row (e.g. cover prob / spread / edge),
    as equal-width tiles in one line. tiles is an iterable of (value, label) strings
    already formatted by the caller (e.g. '67%', 'Cover Prob')."""
    cells = "".join(
        f'<div class="stat-tile"><div class="stat-num tabular">{value}</div>'
        f'<div class="stat-label">{label}</div></div>'
        for value, label in tiles
    )
    return f'<div class="stat-row">{cells}</div>'


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
#
# Visual language: a stadium Jumbotron video-board, chosen after comparing four sports-
# media-inspired directions (see the design pitch). Team logos are the biggest thing on
# every matchup card, and the model's pick is never ambiguous — the picked team's logo
# gets a tier-colored glow + a "✓ Pick" flag, while the other team fades to black-and-
# white, the same way a broadcast graphic dims the losing side. Everything else (cover
# prob, spread, edge) is secondary: readable, but visually quieter than the pick itself.
STYLES = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Anton&family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

    html, body, [class*="css"] { font-family: 'IBM Plex Mono', monospace; }
    h1, h2, h3 { font-family: 'Anton', sans-serif; letter-spacing: 1px; font-weight: 400; }

    /* The stadium video-board backdrop, behind every tab — committing to one dark world
       throughout (not just on the pick cards) is what makes this read as a deliberate
       design instead of a light app with some dark widgets glued on. */
    .stApp {
        background: radial-gradient(ellipse at 50% -10%, #111826 0%, #020203 55%) fixed;
    }

    .stTabs [data-baseweb="tab"] {
        font-family: 'Barlow Condensed', sans-serif; font-weight: 600; font-size: 16px;
        letter-spacing: 1px; border-radius: 6px; padding: 8px 20px;
    }

    div.stButton > button[kind="primary"] {
        background: #38bdf8; color: #0d0f14;
        font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 18px;
        letter-spacing: 1.5px; border: none; border-radius: 6px;
        padding: 10px 32px; width: 100%; transition: background 0.2s;
    }
    div.stButton > button[kind="primary"]:hover { background: #0ea5e9; color: #fff; }

    /* ── Matchup cards (Pick'em Top 12, Today's Games, Moneylines) ──────────────────
       One shared layout: rank/date + tier badge on top, a big team-vs-team logo row
       in the middle (the pick highlighted, the other side dimmed), then a compact
       stat row, then any secondary detail as small muted text. --tier is set inline
       per card (a TIER_COLORS hex, or ACCENT for cards with no tier concept). */
    .matchup-grid, .pickem-grid, .today-grid, .market-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: 16px; margin-top: 14px;
    }
    .matchup-card {
        position: relative; border-radius: 14px;
        background: #10131c;
        border: 2px solid var(--tier, #6b7280);
        box-shadow: 0 18px 36px -22px rgba(0,0,0,.8), 0 0 0 1px rgba(255,255,255,.03) inset;
        padding: 20px 22px 18px;
        display: flex; flex-direction: column;
    }
    .matchup-card-top { display: flex; justify-content: space-between; align-items: center; }
    .matchup-rank {
        font-family: 'Anton', sans-serif; font-weight: 400; color: #aab2c0;
        font-size: 13px; letter-spacing: .05em;
    }
    .tier-badge {
        font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 12px;
        letter-spacing: .07em; padding: 3px 11px; border-radius: 4px;
        background: var(--tier, #6b7280); color: var(--tier-text, #111827);
    }

    /* Team row: the headline of every matchup card. Logos are large and centered;
       whichever side the model picked gets a glow ring + flag (color set via
       --pick-color), the other side is grayscale'd by logo_img(dim=True) so the two
       signals (highlight vs. black-and-white) always travel together. */
    .team-row { display: flex; align-items: flex-start; justify-content: center; gap: 16px; margin: 18px 0 16px; }
    .team-slot { display: flex; flex-direction: column; align-items: center; gap: 8px; flex: 1; min-width: 0; position: relative; padding-top: 20px; }
    .team-slot-name {
        font-family: 'Barlow Condensed', sans-serif; font-weight: 600; font-size: 14px;
        color: #8a909c; text-align: center; line-height: 1.25;
    }
    .team-slot.is-pick .team-slot-name { color: #fff; font-weight: 700; }
    .team-slot.is-pick .logo-chip {
        box-shadow: 0 0 0 4px var(--pick-color, #22c55e), 0 0 20px -3px var(--pick-color, #22c55e);
    }
    .at-sep { font-family: 'Anton', sans-serif; font-weight: 400; font-size: 13px; color: #4d5560; flex: 0 0 auto; align-self: center; margin-top: 32px; }
    .pick-flag {
        position: absolute; top: 0; left: 50%; transform: translateX(-50%);
        font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 10px; letter-spacing: .07em;
        color: #111827; padding: 2px 9px; border-radius: 20px; white-space: nowrap;
    }

    /* Headline stat row — cover prob / spread / edge and similar. Demoted from a giant
       hero number (the old design) to a clean row of equal tiles, since the picked
       team's logo is now what answers "who do I pick"; this row only needs to answer
       "how confident, and what's the number." */
    .stat-row {
        display: grid; grid-template-columns: repeat(auto-fit, minmax(78px, 1fr));
        border-top: 1px solid rgba(255,255,255,.1); padding-top: 13px; margin-top: 2px;
    }
    .stat-tile { text-align: center; padding: 0 4px; border-left: 1px solid rgba(255,255,255,.08); }
    .stat-tile:first-child { border-left: none; }
    .stat-num { font-family: 'Anton', sans-serif; font-weight: 400; font-size: 20px; color: #fff; line-height: 1; }
    .stat-label { font-family: 'Barlow Condensed', sans-serif; font-size: 10px; letter-spacing: .07em; text-transform: uppercase; color: #8a909c; margin-top: 4px; }

    /* Secondary details below the stat row (site/date/notes, line-shopping, live score,
       moneyline/O-U specifics) — present, but visually quieter than the pick and the
       headline stats above it. */
    .extra-meta { font-size: 11px; color: #8a909c; line-height: 1.8; margin-top: 10px; }
    .extra-meta b { color: #e5e7eb; font-weight: 600; }
    .today-stats {
        display: grid; grid-template-columns: repeat(2, 1fr);
        gap: 0 12px; margin-top: 10px; font-size: 12px;
    }
    .today-stats > div {
        display: flex; justify-content: space-between;
        border-bottom: 1px solid rgba(255,255,255,.08); padding: 4px 0;
    }
    .today-stat-label { color: #8a909c; }
    .today-stat-value { font-weight: 600; color: #e5e7eb; }
    .today-live {
        font-size: 12px; font-weight: 600; margin-top: 2px; padding: 3px 8px;
        border-radius: 4px; display: inline-block;
    }
    .today-live.status-live { background: #ef444422; color: #ef4444; }
    .today-live.status-final-win { background: #22c55e22; color: #22c55e; }
    .today-live.status-final-loss { background: #ef444422; color: #ef4444; }
    .today-live.status-final-push { background: rgba(128,128,128,0.15); color: #9ca3af; }
    .total-pick-line {
        font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 16px;
        color: #fff; text-align: center; margin-top: 4px;
    }
    .total-pick-line b { color: #38bdf8; }
    .neutral-badge { font-size: 11px; color: #8a909c; text-align: center; margin-top: -4px; }

    .parlay-card {
        background: #10131c;
        border: 1px solid #38bdf844;
        border-radius: 14px; padding: 18px 20px; margin-bottom: 14px;
        box-shadow: 0 18px 36px -22px rgba(0,0,0,.8);
    }
    .parlay-title {
        font-family: 'Anton', sans-serif; font-weight: 400; font-size: 22px;
        color: #38bdf8; letter-spacing: 1px; margin-bottom: 8px;
    }
    .parlay-leg { font-size: 13px; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,.08); display: flex; align-items: center; }
    .parlay-leg:last-child { border-bottom: none; }
    .parlay-prob { font-family: 'Anton', sans-serif; font-weight: 400; font-size: 18px; color: #38bdf8; margin-top: 10px; }

    .leg-display { font-family: 'Anton', sans-serif; font-weight: 400; font-size: 52px; color: #38bdf8; line-height: 1; text-align: center; }
    .leg-label { font-family: 'Barlow Condensed', sans-serif; font-size: 11px; color: #8a909c; letter-spacing: 1px; text-align: center; margin-top: 2px; }

    /* Rankings/futures list — a single team per card (no "pick" to highlight, no versus),
       so the logo is simply large and centered, same fonts/colors as everywhere else. */
    .futures-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
        gap: 14px; margin-top: 12px;
    }
    .futures-card {
        background: #10131c;
        border: 2px solid var(--tier, rgba(255,255,255,.1));
        border-radius: 14px; padding: 18px;
        display: flex; flex-direction: column; align-items: center; gap: 6px; text-align: center;
        box-shadow: 0 18px 36px -22px rgba(0,0,0,.8);
    }
    .futures-rank { font-family: 'Anton', sans-serif; font-weight: 400; font-size: 26px; line-height: 1; color: #aab2c0; }
    .futures-name { font-family: 'Barlow Condensed', sans-serif; font-weight: 600; font-size: 17px; margin-top: 4px; }
    .futures-score { font-family: 'Anton', sans-serif; font-weight: 400; font-size: 24px; color: #38bdf8; margin-top: 2px; }
    .futures-label { font-size: 11px; color: #8a909c; }
    .bar-bg { margin-top: 6px; background: rgba(255,255,255,.1); border-radius: 4px; height: 4px; width: 100%; }
    .bar-fill { border-radius: 4px; height: 4px; }

    /* Slate confidence breakdown — a single proportional bar (segment width = share of
       games in that tier) reads at a glance; the scatter chart it replaced required
       parsing two abstract axes to get the same information. */
    .tier-bar { display: flex; height: 16px; border-radius: 8px; overflow: hidden; margin-top: 6px; }
    .tier-bar-seg { height: 100%; transition: flex-grow 0.2s; }
    .tier-bar-legend {
        font-size: 13px; color: #c3c9cf; margin-top: 10px;
        display: flex; gap: 18px; flex-wrap: wrap;
    }
    .tier-bar-legend b { font-family: 'Barlow Condensed', sans-serif; font-weight: 700; letter-spacing: 0.5px; }

    /* Light chip behind every team logo so dark/transparent PNG artwork stays visible
       regardless of the card's dark background. The colored ring (set inline per-logo,
       since it's each team's own brand color) adds a subtle bit of team identity without
       touching text contrast — decorative only, never load-bearing for readability.
       logo-chip-dim is the "this team isn't the pick" signal: grayscale + a touch of
       faded opacity, same idea as a broadcast graphic dimming the losing side. */
    .logo-chip {
        display: inline-flex; align-items: center; justify-content: center;
        background: rgba(255,255,255,0.94);
        border: 2px solid rgba(0,0,0,0.08);
        border-radius: 50%;
        flex-shrink: 0;
        transition: filter .15s, box-shadow .15s;
    }
    .logo-chip-dim { filter: grayscale(1); opacity: .75; }

    .fetch-caption { font-size: 12px; color: #8a909c; margin-top: 4px; }

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

    @media (max-width: 460px) {
        .team-slot-name { font-size: 12px; }
        .stat-num { font-size: 17px; }
    }
</style>
"""
