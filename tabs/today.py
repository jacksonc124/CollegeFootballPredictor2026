"""A compact strip of today's games, pinned above the tabs next to the favorite-team
card — not a full tab of its own. Everything here still answers questions unique to
"today": logos + names once, the line, the score once the game is underway, and
whether the pick is actually covering right now — not a repeated "ATS Pick: TeamName"
line or a full stat row (that's Pick'em's job)."""

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
        line_html = f'<div class="today-strip-line">Line {spread:+.1f}</div>' if spread is not None else ""

        # Pre-kickoff: no score yet, just the kickoff time as the whole "time strip".
        # Live/final: the score takes over as its own row, and the time strip adds
        # whether the pick is actually covering — the one thing that changes once a
        # game starts and is worth calling out explicitly, not just by border color.
        time_label, status_class, score_html = row["start_date"], "", ""
        live = scoreboard.get((home, away))
        if live and live.get("home_points") is not None and live.get("away_points") is not None:
            hp, ap = int(live["home_points"]), int(live["away_points"])
            score_html = f'<div class="today-strip-score"><span>{ap}</span><span>{hp}</span></div>'
            status = live.get("status")
            outcome = (backtest.grade_pick(pick_team, home, away, spread, hp, ap)
                       if spread is not None and pick_team else None)
            if status == "in_progress":
                status_class = "status-live"
                clock_str = (f"Q{live['period']} {live['clock']}"
                             if live.get("period") and live.get("clock") else "LIVE")
                cover_label = {"win": "Covering", "loss": "Not Covering", "push": "Push"}.get(outcome)
                time_label = f"{clock_str} · {cover_label}" if cover_label else clock_str
            elif status == "completed":
                # Reuses the exact same grading logic as Game-by-game results, so "did
                # the pick win" always means the same thing everywhere in the app.
                status_class = {"win": "status-final-win", "loss": "status-final-loss",
                                 "push": "status-final-push"}.get(outcome, "status-final-push")
                result_label = {"win": "Covered", "loss": "Didn't Cover", "push": "Push"}.get(outcome)
                time_label = f"FINAL · {result_label}" if result_label else "FINAL"

        away_slot = team_slot_html(away, ctx.logo_img(away, 36, dim=pick_team == home),
                                    is_pick=pick_team == away, tier_color=tier_color)
        home_slot = team_slot_html(home, ctx.logo_img(home, 36, dim=pick_team == away),
                                    is_pick=pick_team == home, tier_color=tier_color)
        cards_html += (
            f'<div class="today-strip-card" style="--tier:{tier_color};">'
            f'{team_row_html(away_slot, home_slot)}'
            f'{line_html}'
            f'{score_html}'
            f'<div class="today-strip-time {status_class}">{time_label}</div>'
            f'</div>'
        )
    cards_html += "</div>"
    st.markdown(cards_html, unsafe_allow_html=True)
