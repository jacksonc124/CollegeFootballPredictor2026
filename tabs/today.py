"""A compact strip of today's games, pinned above the tabs next to the favorite-team
card — not a full tab of its own. Every stat here (tier, cover prob, spread, ML, O/U)
already has a dedicated home (Pick'em, Moneylines & O/U), so this only answers "what's
on today, and what's the score right now": logos + names once, the score once the game
is underway, and a time/status strip. No repeated team-name mentions, no tier badge,
no stat row."""

import streamlit as st

import backtest
from ui_helpers import ACCENT, TIER_COLORS, team_row_html, team_slot_html


def render_strip(ctx):
    if ctx.today_df.empty:
        return

    scoreboard = ctx.get_scoreboard(tuple(ctx.logos.keys()))
    st.markdown(f"##### 📅 Today — {ctx.today.strftime('%A, %B %d')}")

    cards_html = '<div class="today-strip">'
    for _, row in ctx.today_df.iterrows():
        tier, home, away = row["tier"], row["home_team"], row["away_team"]
        pick_team, spread = row["pick_team"], row["market_spread_home"]
        tier_color = TIER_COLORS.get(tier, ACCENT)

        # Pre-kickoff: no score yet, just the kickoff time as the whole "time strip".
        # Live/final: the score takes over as its own row, and the time strip becomes
        # a short status instead (quarter+clock, or FINAL) rather than restating names.
        time_label, status_class, score_html = row["start_date"], "", ""
        live = scoreboard.get((home, away))
        if live and live.get("home_points") is not None and live.get("away_points") is not None:
            hp, ap = int(live["home_points"]), int(live["away_points"])
            score_html = f'<div class="today-strip-score"><span>{ap}</span><span>{hp}</span></div>'
            status = live.get("status")
            if status == "in_progress":
                status_class = "status-live"
                time_label = (f"Q{live['period']} {live['clock']}"
                              if live.get("period") and live.get("clock") else "LIVE")
            elif status == "completed":
                # Reuses the exact same grading logic as Game-by-game results, so "did
                # the pick win" always means the same thing everywhere in the app.
                outcome = (backtest.grade_pick(pick_team, home, away, spread, hp, ap)
                           if spread is not None and pick_team else None)
                status_class = {"win": "status-final-win", "loss": "status-final-loss",
                                 "push": "status-final-push"}.get(outcome, "status-final-push")
                time_label = "FINAL"

        away_slot = team_slot_html(away, ctx.logo_img(away, 36, dim=pick_team == home),
                                    is_pick=pick_team == away, tier_color=tier_color)
        home_slot = team_slot_html(home, ctx.logo_img(home, 36, dim=pick_team == away),
                                    is_pick=pick_team == home, tier_color=tier_color)
        cards_html += (
            f'<div class="today-strip-card" style="--tier:{tier_color};">'
            f'{team_row_html(away_slot, home_slot)}'
            f'{score_html}'
            f'<div class="today-strip-time {status_class}">{time_label}</div>'
            f'</div>'
        )
    cards_html += "</div>"
    st.markdown(cards_html, unsafe_allow_html=True)
