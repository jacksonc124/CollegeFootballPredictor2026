"""Moneylines & Over/Under — one card per game, not one card per bet type. A game with
both a moneyline edge and an O/U edge used to show up twice (two cards, same two team
logos repeated) across two separate sections; now it's one card with both picks on it."""

import pandas as pd
import streamlit as st

import model
from ui_helpers import ACCENT, stat_row_html, team_row_html, team_slot_html


def render(ctx):
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

    df = ctx.df
    has_ml_col = "ml_pick_team" in df.columns
    has_total_col = "total_pick" in df.columns
    has_ml = df["ml_pick_team"].notna() if has_ml_col else pd.Series(False, index=df.index)
    has_total = df["total_pick"].notna() if has_total_col else pd.Series(False, index=df.index)
    combined = df[has_ml | has_total].copy()

    if combined.empty:
        st.info("No moneylines or over/under lines available for this slate's lines provider.")
        return

    # Rank moneyline-edge games first (the original Moneylines section's order), then
    # O/U-only games after, by their own edge — two bet types with different scales
    # don't have one combined "best" ordering, but this keeps each individually sorted
    # the same way it always was, just merged into one list instead of two sections.
    combined["_sort_ml"] = (combined["ml_edge"] if has_ml_col else pd.Series(dtype=float)).fillna(float("-inf"))
    combined["_sort_total"] = (combined["total_edge"].abs() if has_total_col else pd.Series(dtype=float)).fillna(float("-inf"))
    combined = combined.sort_values(["_sort_ml", "_sort_total"], ascending=False).reset_index(drop=True)

    has_opp_adj = "opponent_adjustment" in combined.columns
    has_weather_adj = "weather_adjustment" in combined.columns

    cards_html = '<div class="market-grid">'
    for _, row in combined.iterrows():
        home, away = row["home_team"], row["away_team"]
        ml_pick_team = row.get("ml_pick_team") if has_ml_col else None
        has_ml_row = pd.notna(ml_pick_team)
        has_total_row = has_total_col and pd.notna(row.get("total_pick"))
        neutral_html = '<div class="neutral-badge">⭐ Neutral Site</div>' if row.get("neutral_site") is True else ""

        # O/U has no team to pick, so when a game has only an O/U edge (no moneyline
        # edge), neither logo is highlighted or dimmed — same as before this merge.
        away_slot = team_slot_html(
            f"{ctx.fav_star(away)}{model.rank_badge(away, ctx.rankings)}{away}",
            ctx.logo_img(away, 56, dim=has_ml_row and ml_pick_team == home),
            is_pick=has_ml_row and ml_pick_team == away, tier_color=ACCENT,
        )
        home_slot = team_slot_html(
            f"{ctx.fav_star(home)}{model.rank_badge(home, ctx.rankings)}{home}",
            ctx.logo_img(home, 56, dim=has_ml_row and ml_pick_team == away),
            is_pick=has_ml_row and ml_pick_team == home, tier_color=ACCENT,
        )

        pick_lines, stat_tiles, secondary_html = [], [], ""

        if has_ml_row:
            pick_lines.append(f'ML: <b>{model.rank_badge(ml_pick_team, ctx.rankings)}{ml_pick_team}</b>')
            stat_tiles += [
                (f"{row['ml_model_prob']:.0%}", "Win Prob"),
                (f"{row['ml_edge']:+.1%}", "ML Edge"),
            ]
            secondary_html += (
                f'<div><span class="today-stat-label">Home ML</span><span class="today-stat-value">{row["home_moneyline"]:+.0f}</span></div>'
                f'<div><span class="today-stat-label">Away ML</span><span class="today-stat-value">{row["away_moneyline"]:+.0f}</span></div>'
            )
            # Only worth surfacing when some other book actually beats the price already shown.
            best_ml = row.get("best_ml_value")
            if pd.notna(best_ml):
                shown_ml = row["home_moneyline"] if ml_pick_team == home else row["away_moneyline"]
                if best_ml > shown_ml:
                    secondary_html += (
                        f'<div><span class="today-stat-label">🛒 Best ML</span>'
                        f'<span class="today-stat-value">{best_ml:+.0f} @ {row["best_ml_provider"]}</span></div>'
                    )

        if has_total_row:
            pick_lines.append(f'O/U: <b>{row["total_pick"]}</b>')
            stat_tiles += [
                (f"{row['total_cover_prob']:.0%}", "O/U Prob"),
                (f"{row['total_edge']:+.1f}", "O/U Edge"),
            ]
            secondary_html += (
                f'<div><span class="today-stat-label">Market O/U</span><span class="today-stat-value">{row["market_total"]:.1f}</span></div>'
                f'<div><span class="today-stat-label">Predicted</span><span class="today-stat-value">{row["predicted_total"]:.1f}</span></div>'
            )
            if has_opp_adj and pd.notna(row.get("opponent_adjustment")):
                secondary_html += (f'<div><span class="today-stat-label">Opp Adj</span>'
                                    f'<span class="today-stat-value">{row["opponent_adjustment"]:+.1f}</span></div>')
            if has_weather_adj and pd.notna(row.get("weather_adjustment")):
                secondary_html += (f'<div><span class="today-stat-label">Weather Adj</span>'
                                    f'<span class="today-stat-value">{row["weather_adjustment"]:+.1f}</span></div>')

        pick_line_html = (
            f'<div class="market-pick-line">{" &nbsp;·&nbsp; ".join(pick_lines)}</div>' if pick_lines else ""
        )
        cards_html += (
            f'<div class="matchup-card" style="--tier:{ACCENT};--tier-text:#111827;">'
            f'{team_row_html(away_slot, home_slot)}'
            f'{neutral_html}'
            f'{pick_line_html}'
            f'{stat_row_html(stat_tiles)}'
            f'<div class="today-stats">{secondary_html}</div>'
            f'</div>'
        )
    cards_html += "</div>"
    st.markdown(cards_html, unsafe_allow_html=True)

    strong_ml_count = int((combined["_sort_ml"] >= model.ML_EDGE_THRESHOLD).sum()) if has_ml_col else 0
    st.caption(f"{len(combined)} game(s) with a moneyline or O/U edge · {strong_ml_count} with ML edge ≥ "
               f"{model.ML_EDGE_THRESHOLD:.0%} (eligible for the parlay pool below).")
