"""Tab 6: Stats — offensive stat leaderboard ("Heisman Watch") and category leaders."""

import streamlit as st

import model

# Which raw columns build_stat_leaderboard() returns count as "leading a national
# category" for the Heisman Watch blurb below, and what top_stat_leaders() call each
# one corresponds to — so a candidate's blurb can truthfully say "national leader in
# receiving yards" only when they actually are, rather than asserting it.
_CATEGORY_LEADERS = [
    ("pass_yds", "Passing Yards", "passing", "YDS"),
    ("pass_td", "Passing TDs", "passing", "TD"),
    ("rush_yds", "Rushing Yards", "rushing", "YDS"),
    ("rush_td", "Rushing TDs", "rushing", "TD"),
    ("rec_yds", "Receiving Yards", "receiving", "YDS"),
    ("rec_td", "Receiving TDs", "receiving", "TD"),
]


def _national_leaders(passing_stats, rushing_stats, receiving_stats):
    """{column: player_name} for whoever is actually #1 nationally in that column —
    computed from the same category leaderboards shown lower on this page, so the
    Heisman Watch blurbs below can only ever cite something that's really true."""
    rows_by_category = {"passing": passing_stats, "rushing": rushing_stats, "receiving": receiving_stats}
    leaders = {}
    for column, _, category, stat_type in _CATEGORY_LEADERS:
        top = model.top_stat_leaders(rows_by_category[category], stat_type, top_n=1)
        if not top.empty:
            leaders[column] = top.iloc[0]["player"]
    return leaders


def _candidate_blurb(row, national_leaders):
    """A one-line, fact-based summary of why this player is in the conversation —
    their real stat line plus, only when actually true, which national category(ies)
    they lead. No odds number: CFBD has no Heisman futures market (see the page's own
    disclaimer), so showing one would mean presenting a made-up number as real."""
    cats = [("passing", row["pass_yds"], row["pass_td"]), ("rushing", row["rush_yds"], row["rush_td"]),
            ("receiving", row["rec_yds"], row["rec_td"])]
    primary = max(cats, key=lambda c: c[1])

    led = [label for col, label, _, _ in _CATEGORY_LEADERS if national_leaders.get(col) == row["player"]]
    lead_str = f"National leader in {', '.join(led)}. " if led else ""

    secondary = max((c for c in cats if c[0] != primary[0]), key=lambda c: c[1])
    dual_threat = f", plus {secondary[1]:.0f} {secondary[0]} yards" if secondary[1] >= 300 else ""

    return (f"{lead_str}{row['total_yards']:.0f} total yards ({primary[0]} {primary[1]:.0f}{dual_threat}), "
            f"{row['total_td']:.0f} total TDs through {row['games']:.0f} games "
            f"({row['score_per_game']:.0f} pts/game).")


def render(ctx):
    st.markdown("## 📈 Stats")
    st.caption(f"{ctx.year} regular season · Offensive stat leaderboard")

    with st.expander("ℹ️ Not real Heisman odds — how is this ranked?"):
        st.caption(
            "CFBD has no awards-odds market — no book prices a Heisman futures line through "
            "this API, so there's nothing legitimate to show as 'odds.' Ranked instead by real "
            "season stats per game played (total yards + 6 pts/TD, passing yards discounted — "
            "see model.py's PASSING_YARD_WEIGHT — then divided by games played so a player isn't "
            "ranked higher just for having played more games). A 'national leader in X' note is "
            "only shown when that player is actually #1 in that category below."
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

        # Games-played denominator for per-game scoring (see build_stat_leaderboard's
        # docstring) — team_ats_records already tracks each team's games this season,
        # so this is free: no extra API call for something we already have.
        team_games = {team: r["games"] for team, r in ctx.ats_records.items()}
        leaderboard = model.build_stat_leaderboard(
            passing_stats, rushing_stats, receiving_stats, top_n=5, team_games=team_games,
        )

        if leaderboard.empty:
            st.info("No player stats available yet for this season.")
        else:
            st.markdown("#### 🏈 Heisman Watch")
            national_leaders = _national_leaders(passing_stats, rushing_stats, receiving_stats)
            for i, row in leaderboard.iterrows():
                logo_col, text_col = st.columns([1, 9])
                with logo_col:
                    st.markdown(ctx.logo_img(row["team"], 36), unsafe_allow_html=True)
                with text_col:
                    team_label = f"{model.rank_badge(row['team'], ctx.rankings)}{row['team']}"
                    st.markdown(
                        f"**{i + 1}. {row['player']}** ({row['position']}, {team_label}): "
                        f"{_candidate_blurb(row, national_leaders)}"
                    )
            st.caption("Ranked by production per game played (see above) across passing/rushing/"
                       "receiving — not a calibrated prediction or a real betting market.")

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
