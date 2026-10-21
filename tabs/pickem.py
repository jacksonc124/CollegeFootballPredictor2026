"""Tab 1: CBS Pick'em — ranked top 12 ATS picks, plus the full filterable All Games table."""

import pandas as pd
import streamlit as st

import cbs_pickem
import model
import pick_log
from ui_helpers import ACCENT, DISPLAY_COLUMNS, TIER_COLORS, tier_row_css


def _render_cbs_pool_section(ctx):
    """
    Filters the ranked Top 12 down to only the games actually in this user's CBS Sports
    Pick'em pool — CBS's pool is usually a subset of the week's full slate (e.g. 17 of
    ~60 games), not every game, so the full-slate Top 12 above can include picks that
    aren't even an option in the real pool. See cbs_pickem.py: this is an unofficial
    integration built from a captured request, not CBS's documented API.
    """
    st.markdown("### 🔒 My CBS Pool")
    if not ctx.cbs_configured:
        st.caption("Not set up yet — add CBS_COOKIE, CBS_POOL_ID, and CBS_ENTRY_ID secrets "
                   "to filter the list above down to only games actually in your CBS pool. "
                   "See the README for how to get these from your browser.")
        return

    try:
        with st.spinner("Fetching your CBS pool's games…"):
            pool_games = ctx.get_cbs_pool_games()
    except Exception as e:
        st.error(f"Couldn't fetch your CBS pool ({e}). Your session cookie may have "
                 "expired — see the README for how to grab a fresh one.")
        return

    if not pool_games:
        st.info("CBS returned no games for this pool's current period.")
        return

    known_team_names = set(ctx.logos.keys())
    matched_df, unmatched = cbs_pickem.match_pool_games_to_df(pool_games, ctx.df, known_team_names)
    week_number = next((g["week_number"] for g in pool_games if g.get("week_number")), None)
    week_str = f" · Week {week_number}" if week_number else ""
    st.caption(f"{len(pool_games)} game(s) in your pool{week_str} · "
               f"{len(matched_df)} matched to this slate's model picks.")

    if matched_df.empty:
        st.warning("None of your pool's games matched this slate — try a different "
                   "Year/Week in the sidebar to match your pool's actual week.")
    else:
        top_pool = matched_df[matched_df["tier"] != "Pass"].sort_values(
            "cover_prob", ascending=False
        ).reset_index(drop=True)
        display = top_pool.rename(columns=DISPLAY_COLUMNS)[
            ["Home", "Away", "Market Spread", "Pick", "Cover Prob", "Edge (pts)", "Tier"]
        ]
        st.dataframe(
            display, use_container_width=True, hide_index=True,
            column_config={
                "Cover Prob": st.column_config.ProgressColumn("Cover Prob", min_value=0.0, max_value=1.0),
                "Edge (pts)": st.column_config.NumberColumn("Edge (pts)", format="%+.1f"),
                "Market Spread": st.column_config.NumberColumn("Market Spread", format="%+.1f"),
            },
        )

    if unmatched:
        with st.expander(f"⚠️ {len(unmatched)} pool game(s) couldn't be matched — check manually"):
            for g in unmatched:
                st.caption(f"{g.get('away_team') or '?'} @ {g.get('home_team') or '?'}")


def render(ctx):
    st.markdown("## 🏆 CBS Pick'em — Top 12 ATS Picks")
    st.caption("Ranked by cover probability · Against the spread")

    log_col, btn_col = st.columns([4, 1])
    with log_col:
        if pick_log.already_logged(ctx.year, ctx.api_week, ctx.season_type):
            reason = "auto-logged (this is the current week)" if ctx.is_current_slate else "logged"
            st.caption(f"✅ This slate's picks are {reason} for unbiased accuracy tracking — "
                       "see the Model Accuracy tab.")
        elif ctx.is_current_slate:
            st.caption("📌 Auto-logging this slate now (current week) for a genuinely unbiased "
                       "accuracy record — see the Model Accuracy tab.")
        else:
            st.caption("📌 This isn't the current week, so it won't auto-log — use the button to log it "
                       "manually if you want it tracked anyway. See the Model Accuracy tab.")
    with btn_col:
        if not pick_log.already_logged(ctx.year, ctx.api_week, ctx.season_type):
            if st.button("📌 Log Picks", key="log_picks_btn", use_container_width=True, type="primary"):
                pick_log.log_picks(ctx.df, ctx.year, ctx.api_week, ctx.season_type)
                pick_log.sync_to_supabase(ctx.supabase_url, ctx.supabase_key)
                st.rerun()
    st.markdown("---")

    df = ctx.df
    top12 = (df[df["tier"] != "Pass"]
             .sort_values("cover_prob", ascending=False)
             .head(12).reset_index(drop=True))

    if top12.empty:
        st.info("Not enough picks above Pass tier for a top 12.")
    else:
        cards_html = '<div class="pickem-grid">'
        for i, row in top12.iterrows():
            tier, home, away       = row["tier"], row["home_team"], row["away_team"]
            pick_team, cover, edge = row["pick_team"], row["cover_prob"], row["edge_points"]
            spread                 = row["market_spread_home"]
            neutral_site, notes    = row.get("neutral_site"), row.get("game_notes") or ""
            game_date               = row.get("start_date") or ""
            venue                   = row.get("venue") or ""
            spread_str = f"Spread: {spread:+.1f}" if spread is not None else ""
            if neutral_site is None:
                site_str = ""
            elif neutral_site:
                site_str = f"🏟 {venue}" if venue else "🏟 Neutral Site"
            else:
                site_str = f"🏠 {venue}" if venue else "🏠 Home Game"
            date_str = f"🗓 {game_date}" if game_date else ""
            note_str = f"<br/>{notes}" if notes else ""
            # Line shopping: only worth a line when some other book actually beats the
            # number already shown above (a tie or worse isn't "extra value").
            best_str = ""
            best_spread = row.get("best_spread_value")
            if pd.notna(best_spread) and spread is not None:
                shown_side_spread = spread if pick_team == home else -spread
                if best_spread > shown_side_spread:
                    best_str = f"🛒 Best: {best_spread:+.1f} @ {row['best_spread_provider']}"
            tier_color = TIER_COLORS.get(tier, ACCENT)
            cards_html += (
                f'<div class="pickem-card tier-{tier}">'
                f'<div class="pickem-card-top">'
                f'<div class="pickem-rank">#{i + 1}</div>'
                f'<div class="pickem-tier-badge tier-{tier}">TIER {tier}</div>'
                f'</div>'
                f'<div class="pickem-logos">{ctx.logo_img(away, 32)}<span class="pickem-vs">@</span>{ctx.logo_img(home, 32)}</div>'
                f'<div class="pickem-matchup">{ctx.fav_star(away)}{model.rank_badge(away, ctx.rankings)}{away} @ '
                f'{ctx.fav_star(home)}{model.rank_badge(home, ctx.rankings)}{home}</div>'
                f'<div class="pickem-hero">'
                f'<span class="pickem-cover-prob" style="color:{tier_color};">{cover:.0%}</span>'
                f'</div>'
                f'<div class="pickem-confidence-bar">'
                f'<div class="pickem-confidence-fill" style="width:{cover * 100:.0f}%;background:{tier_color};"></div>'
                f'</div>'
                f'<div class="pickem-pick">&#10003; Pick: <b>{model.rank_badge(pick_team, ctx.rankings)}{pick_team}</b></div>'
                f'<div class="pickem-meta">'
                f'Edge: <b>{edge:+.1f} pts</b>'
                f'{"<br/>" + spread_str if spread_str else ""}'
                f'{"<br/>" + best_str if best_str else ""}'
                f'{"<br/>" + site_str if site_str else ""}'
                f'{"<br/>" + date_str if date_str else ""}'
                f'{note_str}'
                f'</div></div>'
            )
        cards_html += "</div>"
        st.markdown(cards_html, unsafe_allow_html=True)

    st.markdown("---")
    _render_cbs_pool_section(ctx)

    st.markdown("---")
    st.markdown("## 📋 All Games")
    tier_filter = st.multiselect("Filter by Tier", ["A","B","C","Pass"], default=["A","B","C","Pass"], key="tf1")
    filtered = df[df["tier"].isin(tier_filter)] if tier_filter else df

    # Subtle full-row tint (not just the Tier cell) so the strongest picks are scannable
    # at a glance without reading every row — same tier colors as everywhere else in the app.
    def _shade_row(row):
        return [tier_row_css(row["Tier"])] * len(row)

    table_df = (
        filtered.drop(columns=["pick_team"]).rename(columns=DISPLAY_COLUMNS)
                .sort_values("Edge (pts)", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
    )
    # ATS lookups use the clean team name, so compute them before the rank-badge prefix is added.
    table_df["Home ATS"] = table_df["Home"].map(lambda t: model.ats_record_str(t, ctx.ats_records))
    table_df["Away ATS"] = table_df["Away"].map(lambda t: model.ats_record_str(t, ctx.ats_records))
    table_df["Home"] = table_df["Home"].map(lambda t: f"{ctx.fav_star(t)}{model.rank_badge(t, ctx.rankings)}{t}")
    table_df["Away"] = table_df["Away"].map(lambda t: f"{ctx.fav_star(t)}{model.rank_badge(t, ctx.rankings)}{t}")
    st.dataframe(
        table_df.style.apply(_shade_row, axis=1),
        use_container_width=True, height=min(50 + 35 * len(filtered), 600),
        column_config={
            "Cover Prob": st.column_config.ProgressColumn("Cover Prob", min_value=0.0, max_value=1.0),
            "Edge (pts)": st.column_config.NumberColumn("Edge (pts)", format="%+.1f"),
            "Model Spread": st.column_config.NumberColumn("Model Spread", format="%+.1f"),
            "Market Spread": st.column_config.NumberColumn("Market Spread", format="%+.1f"),
            "SP+ Home": st.column_config.NumberColumn("SP+ Home", format="%+.1f"),
            "SP+ Away": st.column_config.NumberColumn("SP+ Away", format="%+.1f"),
            "Neutral Site": st.column_config.CheckboxColumn("Neutral Site"),
            "Best Spread": st.column_config.NumberColumn("Best Spread", format="%+.1f",
                                                           help="Best available spread across every book CFBD returned "
                                                                "for whichever side the model picked ATS."),
            "Best ML": st.column_config.NumberColumn("Best ML", format="%+.0f",
                                                       help="Best available moneyline price across every book CFBD "
                                                            "returned for whichever side the model picked straight-up."),
        },
    )
    st.markdown("---")
    dl1, dl2 = st.columns(2)
    with dl1:
        fname = f"all_games_{ctx.year}_postseason" if ctx.postseason else f"all_games_{ctx.year}_wk{ctx.week}"
        st.download_button("⬇️ All Games (CSV)",
                           data=df.drop(columns=["pick_team"]).rename(columns=DISPLAY_COLUMNS).to_csv(index=False),
                           file_name=f"{fname}.csv", mime="text/csv")
    with dl2:
        if not ctx.strong.empty:
            fname2 = f"strong_picks_{ctx.year}_postseason" if ctx.postseason else f"strong_picks_{ctx.year}_wk{ctx.week}"
            st.download_button("⬇️ Strong Picks (CSV)",
                               data=ctx.strong.drop(columns=["pick_team"]).rename(columns=DISPLAY_COLUMNS).to_csv(index=False),
                               file_name=f"{fname2}.csv", mime="text/csv")
