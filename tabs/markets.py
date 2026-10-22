"""Tab 3: Moneylines & Over/Under."""

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
    ml_df = df[df["ml_pick_team"].notna()].copy() if "ml_pick_team" in df.columns else pd.DataFrame()
    total_df = df[df["total_pick"].notna()].copy() if "total_pick" in df.columns else pd.DataFrame()

    st.markdown("#### Moneylines")
    if ml_df.empty:
        st.info("No moneylines available for this slate's lines provider.")
    else:
        ml_sorted = ml_df.sort_values("ml_edge", ascending=False).reset_index(drop=True)
        ml_cards_html = '<div class="market-grid">'
        for _, row in ml_sorted.iterrows():
            home, away = row["home_team"], row["away_team"]
            pick_team  = row["ml_pick_team"]
            neutral_html = '<div class="neutral-badge">⭐ Neutral Site</div>' if row.get("neutral_site") is True else ""
            ml_stats_html = (
                f'<div><span class="today-stat-label">Home ML</span><span class="today-stat-value">{row["home_moneyline"]:+.0f}</span></div>'
                f'<div><span class="today-stat-label">Away ML</span><span class="today-stat-value">{row["away_moneyline"]:+.0f}</span></div>'
                f'<div><span class="today-stat-label">Market Prob</span><span class="today-stat-value">{row["ml_market_prob"]:.1%}</span></div>'
                f'<div><span class="today-stat-label">Edge</span><span class="today-stat-value">{row["ml_edge"]:+.1%}</span></div>'
            )
            # Only worth surfacing when some other book actually beats the price already shown.
            best_ml = row.get("best_ml_value")
            if pd.notna(best_ml):
                shown_ml = row["home_moneyline"] if pick_team == home else row["away_moneyline"]
                if best_ml > shown_ml:
                    ml_stats_html += (
                        f'<div><span class="today-stat-label">🛒 Best ML</span>'
                        f'<span class="today-stat-value">{best_ml:+.0f} @ {row["best_ml_provider"]}</span></div>'
                    )
            away_slot = team_slot_html(
                f"{ctx.fav_star(away)}{model.rank_badge(away, ctx.rankings)}{away}",
                ctx.logo_img(away, 56, dim=pick_team == home),
                is_pick=pick_team == away, tier_color=ACCENT,
            )
            home_slot = team_slot_html(
                f"{ctx.fav_star(home)}{model.rank_badge(home, ctx.rankings)}{home}",
                ctx.logo_img(home, 56, dim=pick_team == away),
                is_pick=pick_team == home, tier_color=ACCENT,
            )
            ml_stat_row = stat_row_html([
                (f"{row['ml_model_prob']:.0%}", "Win Prob"),
                (f"{row['ml_market_prob']:.1%}", "Market Prob"),
                (f"{row['ml_edge']:+.1%}", "Edge"),
            ])
            ml_cards_html += (
                f'<div class="matchup-card" style="--tier:{ACCENT};--tier-text:#111827;">'
                f'{team_row_html(away_slot, home_slot)}'
                f'{neutral_html}'
                f'{ml_stat_row}'
                f'<div class="today-stats">{ml_stats_html}</div>'
                f'</div>'
            )
        ml_cards_html += "</div>"
        st.markdown(ml_cards_html, unsafe_allow_html=True)
        strong_ml = ml_df[ml_df["ml_edge"] >= model.ML_EDGE_THRESHOLD]
        st.caption(f"{len(strong_ml)} game(s) with edge ≥ {model.ML_EDGE_THRESHOLD:.0%} — these are the ones "
                   f"eligible for the parlay pool on the Team Parlays tab.")

    st.markdown("#### Over/Under")
    if total_df.empty:
        st.info("No over/under lines available, or no scoring data yet to build a predicted total.")
    else:
        total_sorted = total_df.sort_values("total_edge", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
        has_opp_adj = "opponent_adjustment" in total_sorted.columns
        has_weather_adj = "weather_adjustment" in total_sorted.columns

        total_cards_html = '<div class="market-grid">'
        for _, row in total_sorted.iterrows():
            home, away = row["home_team"], row["away_team"]
            cover      = row["total_cover_prob"]
            neutral_html = '<div class="neutral-badge">⭐ Neutral Site</div>' if row.get("neutral_site") is True else ""
            stats_html = (
                f'<div><span class="today-stat-label">Market O/U</span><span class="today-stat-value">{row["market_total"]:.1f}</span></div>'
                f'<div><span class="today-stat-label">Predicted</span><span class="today-stat-value">{row["predicted_total"]:.1f}</span></div>'
            )
            if has_opp_adj and pd.notna(row.get("opponent_adjustment")):
                stats_html += (f'<div><span class="today-stat-label">Opp Adj</span>'
                                f'<span class="today-stat-value">{row["opponent_adjustment"]:+.1f}</span></div>')
            if has_weather_adj and pd.notna(row.get("weather_adjustment")):
                stats_html += (f'<div><span class="today-stat-label">Weather Adj</span>'
                                f'<span class="today-stat-value">{row["weather_adjustment"]:+.1f}</span></div>')

            # Over/Under has no "team to pick" — it's a total, not a side — so neither
            # logo is highlighted or dimmed; the pick is the Over/Under line itself,
            # called out below the team row instead of on a logo.
            away_slot = team_slot_html(
                f"{ctx.fav_star(away)}{model.rank_badge(away, ctx.rankings)}{away}",
                ctx.logo_img(away, 56), is_pick=False,
            )
            home_slot = team_slot_html(
                f"{ctx.fav_star(home)}{model.rank_badge(home, ctx.rankings)}{home}",
                ctx.logo_img(home, 56), is_pick=False,
            )
            total_stat_row = stat_row_html([
                (f"{cover:.0%}", "Cover Prob"),
                (f"{row['total_edge']:+.1f}", "Edge (pts)"),
            ])
            total_cards_html += (
                f'<div class="matchup-card" style="--tier:{ACCENT};--tier-text:#111827;">'
                f'{team_row_html(away_slot, home_slot)}'
                f'{neutral_html}'
                f'<div class="total-pick-line">Pick: <b>{row["total_pick"]}</b></div>'
                f'{total_stat_row}'
                f'<div class="today-stats">{stats_html}</div>'
                f'</div>'
            )
        total_cards_html += "</div>"
        st.markdown(total_cards_html, unsafe_allow_html=True)
