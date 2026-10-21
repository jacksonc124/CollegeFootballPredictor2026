"""Tab 6: Stats — offensive stat leaderboard ("Heisman Watch") and category leaders."""

import streamlit as st

import model


def render(ctx):
    st.markdown("## 📈 Stats")
    st.caption(f"{ctx.year} regular season · Offensive stat leaderboard")

    st.info(
        "ℹ️ **Not real Heisman odds.** CFBD has no awards-odds market — no book prices a "
        "Heisman futures line through this API, so there's nothing legitimate to display as "
        "'odds.' What's below is a simple composite of real season stats instead: total yards "
        "+ 6 points per touchdown, summed across passing/rushing/receiving. It's a common "
        "informal 'total production' heuristic for gauging who's in the Heisman conversation, "
        "not a calibrated prediction.",
        icon="ℹ️",
    )

    if "stats_loaded_year" not in st.session_state:
        st.session_state["stats_loaded_year"] = None
    stats_loaded = st.session_state["stats_loaded_year"] == ctx.year

    if not stats_loaded:
        st.info(f"Fetches passing/rushing/receiving stats for every FBS player in {ctx.year} (3 API calls, "
                f"cached afterward for 1 hour).")
        if st.button("📊 Load Player Stats", key="run_stats", type="primary"):
            st.session_state["stats_loaded_year"] = ctx.year
            st.rerun()
    else:
        with st.spinner("Fetching player season stats…"):
            try:
                passing_stats = ctx.get_player_season_stats(ctx.year, "passing")
                rushing_stats = ctx.get_player_season_stats(ctx.year, "rushing")
                receiving_stats = ctx.get_player_season_stats(ctx.year, "receiving")
            except Exception as e:
                st.error(f"API error: {e}")
                passing_stats, rushing_stats, receiving_stats = [], [], []

        # get_player_season_stats has no classification filter (unlike the Games API), so it
        # returns every division mixed together. Filter to FBS using the team names already
        # fetched for logos — matches the rest of the app, which is FBS-only throughout.
        fbs_teams = set(ctx.logos.keys())
        if fbs_teams:
            passing_stats = [r for r in passing_stats if r["team"] in fbs_teams]
            rushing_stats = [r for r in rushing_stats if r["team"] in fbs_teams]
            receiving_stats = [r for r in receiving_stats if r["team"] in fbs_teams]

        leaderboard = model.build_stat_leaderboard(passing_stats, rushing_stats, receiving_stats, top_n=10)

        if leaderboard.empty:
            st.info("No player stats available yet for this season.")
        else:
            st.markdown("#### 🏈 Heisman Watch — Top 10 by Total Production")
            display = leaderboard[["player", "team", "position", "total_yards", "total_td", "score"]].rename(columns={
                "player": "Player", "team": "Team", "position": "Pos",
                "total_yards": "Total Yards", "total_td": "Total TDs", "score": "Score",
            })
            display["Logo"] = display["Team"].map(lambda t: ctx.logos.get(t, ""))
            display = display[["Logo", "Player", "Team", "Pos", "Total Yards", "Total TDs", "Score"]]
            st.dataframe(
                display, use_container_width=True, hide_index=True,
                column_config={
                    "Logo": st.column_config.ImageColumn("", width="small"),
                    "Total Yards": st.column_config.NumberColumn("Total Yards", format="%.0f"),
                    "Total TDs": st.column_config.NumberColumn("Total TDs", format="%.0f"),
                    "Score": st.column_config.NumberColumn("Score", format="%.0f",
                                                            help="Total yards + 6 × total TDs"),
                },
            )

        st.markdown("---")
        st.markdown("#### Category leaders")
        st.caption("Ranked within their own stat — unlike Heisman Watch above, these aren't blended "
                   "across categories, so rushers and receivers show up here on equal footing with passers.")

        def render_leader_table(rows, stat_type, value_label):
            leaders = model.top_stat_leaders(rows, stat_type, top_n=5)
            if leaders.empty:
                st.caption("No data.")
                return
            leaders = leaders.rename(columns={"player": "Player", "team": "Team", "position": "Pos", "value": value_label})
            leaders["Logo"] = leaders["Team"].map(lambda t: ctx.logos.get(t, ""))
            leaders = leaders[["Logo", "Player", "Team", "Pos", value_label]]
            st.dataframe(
                leaders, use_container_width=True, hide_index=True,
                column_config={
                    "Logo": st.column_config.ImageColumn("", width="small"),
                    value_label: st.column_config.NumberColumn(value_label, format="%.0f"),
                },
            )

        p1, p2 = st.columns(2)
        with p1:
            st.markdown("**Passing Yards**")
            render_leader_table(passing_stats, "YDS", "Yards")
        with p2:
            st.markdown("**Passing TDs**")
            render_leader_table(passing_stats, "TD", "TDs")

        r1, r2 = st.columns(2)
        with r1:
            st.markdown("**Rushing Yards**")
            render_leader_table(rushing_stats, "YDS", "Yards")
        with r2:
            st.markdown("**Rushing TDs**")
            render_leader_table(rushing_stats, "TD", "TDs")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Receiving Yards**")
            render_leader_table(receiving_stats, "YDS", "Yards")
        with c2:
            st.markdown("**Receiving TDs**")
            render_leader_table(receiving_stats, "TD", "TDs")
