"""Tab 0: Today's Games — everything kicking off today, spread/moneylines/O-U side by side."""

import pandas as pd
import streamlit as st

import backtest
import model
from ui_helpers import ACCENT, OUTCOME_COLORS, TIER_COLORS


def render(ctx):
    st.markdown(f"## 📅 Today's Games — {ctx.today.strftime('%A, %B %d')}")
    st.caption("Everything kicking off today, spread/moneylines/O-U side by side · "
               "full detail (parlays, rankings, accuracy) lives in the other tabs.")

    if ctx.today_df.empty:
        st.info("No games today in the slate currently selected in the sidebar. "
                "Adjust Year/Week there to jump to a different day.")
        return

    today_df = ctx.today_df
    has_ml = "home_moneyline" in today_df.columns
    has_total = "market_total" in today_df.columns
    scoreboard = ctx.get_scoreboard(tuple(ctx.logos.keys()))

    today_cards_html = '<div class="today-grid">'
    for _, row in today_df.iterrows():
        tier, home, away = row["tier"], row["home_team"], row["away_team"]
        pick_team, cover  = row["pick_team"], row["cover_prob"]
        spread            = row["market_spread_home"]
        tier_color        = TIER_COLORS.get(tier, ACCENT)

        stats_html = (
            f'<div><span class="today-stat-label">Spread</span>'
            f'<span class="today-stat-value">{spread:+.1f}</span></div>'
            if spread is not None else ""
        )
        if has_ml and pd.notna(row.get("home_moneyline")):
            stats_html += (
                f'<div><span class="today-stat-label">Home ML</span>'
                f'<span class="today-stat-value">{row["home_moneyline"]:+.0f}</span></div>'
                f'<div><span class="today-stat-label">Away ML</span>'
                f'<span class="today-stat-value">{row["away_moneyline"]:+.0f}</span></div>'
            )
        if has_total and pd.notna(row.get("market_total")):
            stats_html += (
                f'<div><span class="today-stat-label">O/U Line</span>'
                f'<span class="today-stat-value">{row["market_total"]:.1f}</span></div>'
            )
            if pd.notna(row.get("total_pick")) and row["total_pick"]:
                stats_html += (
                    f'<div><span class="today-stat-label">Total Pick</span>'
                    f'<span class="today-stat-value">{row["total_pick"]}</span></div>'
                )

        # Live score, when the scoreboard has this game and it's actually underway —
        # a "scheduled" game (the common case pre-kickoff) gets no extra line at all,
        # same as before this feature existed.
        live = scoreboard.get((home, away))
        live_html = ""
        if live and live.get("home_points") is not None and live.get("away_points") is not None:
            hp, ap = int(live["home_points"]), int(live["away_points"])
            status = live.get("status")
            if status == "in_progress":
                clock_str = (f"Q{live['period']} {live['clock']}"
                             if live.get("period") and live.get("clock") else "In Progress")
                # "Currently covering" against the live (not final) score — same
                # grade_pick() math as the final-score case, just fed a score that can
                # still change. Colored, but deliberately labeled "(live)" everywhere
                # it appears so it's never mistaken for the graded, final result.
                cover_html = ""
                if spread is not None and pick_team:
                    live_outcome = backtest.grade_pick(pick_team, home, away, spread, hp, ap)
                    cover_label = {"win": "Covering", "loss": "Not Covering", "push": "Push"}.get(live_outcome)
                    if cover_label:
                        color = OUTCOME_COLORS.get(live_outcome, "")
                        style = f' style="color:{color};"' if color else ""
                        cover_html = f' · <span{style}>{cover_label} (live)</span>'
                live_html = (f'<div class="today-live status-live">🔴 LIVE · {clock_str} · '
                             f'{away} {ap} — {home} {hp}{cover_html}</div>')
            elif status == "completed":
                # Reuses the exact same grading logic as Game-by-game results, so "did
                # the pick win" always means the same thing everywhere in the app.
                outcome = (backtest.grade_pick(pick_team, home, away, spread, hp, ap)
                           if spread is not None and pick_team else None)
                label = {"win": "✅ Pick Won", "loss": "❌ Pick Lost", "push": "🟰 Push"}.get(outcome, "Final")
                css_class = {"win": "status-final-win", "loss": "status-final-loss",
                              "push": "status-final-push"}.get(outcome, "status-final-push")
                live_html = (f'<div class="today-live {css_class}">🏁 FINAL {away} {ap} — '
                             f'{home} {hp} · {label}</div>')

        today_cards_html += (
            f'<div class="today-card tier-{tier}">'
            f'<div class="today-card-top">'
            f'<div class="today-kickoff">🗓 {row["start_date"]}</div>'
            f'<div class="pickem-tier-badge tier-{tier}">TIER {tier}</div>'
            f'</div>'
            f'<div class="pickem-logos">{ctx.logo_img(away, 32)}<span class="pickem-vs">@</span>{ctx.logo_img(home, 32)}</div>'
            f'<div class="pickem-matchup">{ctx.fav_star(away)}{model.rank_badge(away, ctx.rankings)}{away} @ '
            f'{ctx.fav_star(home)}{model.rank_badge(home, ctx.rankings)}{home}</div>'
            f'{live_html}'
            f'<div class="pickem-hero">'
            f'<span class="pickem-cover-prob" style="color:{tier_color};">{cover:.0%}</span>'
            f'</div>'
            f'<div class="pickem-confidence-bar">'
            f'<div class="pickem-confidence-fill" style="width:{cover * 100:.0f}%;background:{tier_color};"></div>'
            f'</div>'
            f'<div class="pickem-pick">&#10003; ATS Pick: <b>{model.rank_badge(pick_team, ctx.rankings)}{pick_team}</b></div>'
            f'<div class="today-stats">{stats_html}</div>'
            f'</div>'
        )
    today_cards_html += "</div>"
    st.markdown(today_cards_html, unsafe_allow_html=True)
    st.caption(f"{len(today_df)} game(s) today · sorted as returned by the lines provider — "
               "see the Pick'em tab for a ranked top 12.")
