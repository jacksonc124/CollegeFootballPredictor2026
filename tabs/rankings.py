"""Tab 4: Rankings & ATS — SP+ championship favorites, AP/Coaches polls, best/worst ATS."""

import pandas as pd
import streamlit as st

import model


def render(ctx):
    st.markdown("## 🥇 National Championship Favorites")
    st.caption(f"Based on SP+ ratings · {ctx.year} season · Higher rating = stronger team")

    sp_ratings = ctx.get_sp_ratings(ctx.year)

    if not sp_ratings:
        st.warning("No SP+ ratings found for this year.")
    else:
        sp_df = (
            pd.DataFrame(list(sp_ratings.items()), columns=["Team", "SP+ Rating"])
            .sort_values("SP+ Rating", ascending=False)
            .reset_index(drop=True)
        )
        display_champ = sp_df.head(25)
        sp_max = display_champ["SP+ Rating"].max()
        sp_min = display_champ["SP+ Rating"].min()

        cards_html = '<div class="futures-grid">'
        for i, row in display_champ.iterrows():
            rank       = i + 1
            team       = row["Team"]
            rating     = row["SP+ Rating"]
            rank_class = {1: "rank-1", 2: "rank-2", 3: "rank-3"}.get(rank, "rank-other")
            medal      = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")
            logo_tag   = ctx.logo_img(team, 40)
            bar_pct    = int((rating - sp_min) / (sp_max - sp_min + 0.001) * 100) if sp_max != sp_min else 80
            cards_html += (
                f'<div class="futures-card {rank_class}">'
                f'<div class="futures-rank">{medal}</div>'
                f'{logo_tag}'
                f'<div class="futures-name">{model.rank_badge(team, ctx.rankings)}{team}</div>'
                f'<div class="futures-score">{rating:+.1f}</div>'
                f'<div class="futures-label">SP+ Rating</div>'
                f'<div class="bar-bg"><div class="bar-fill" style="background:#38bdf8;width:{bar_pct}%;"></div></div>'
                f'</div>'
            )
        cards_html += "</div>"
        st.markdown(cards_html, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📰 AP & Coaches Top 25")
    st.caption(f"Actual human-voter poll rankings for {ctx.season_label.title()}, for comparison against SP+ above.")

    poll_cols = st.columns(2)
    for col, poll_name in zip(poll_cols, model.RANKING_POLLS):
        with col:
            st.markdown(f"**{poll_name}**")
            ranks = ctx.rankings.get(poll_name, {})
            if not ranks:
                st.caption("No rankings available for this week yet.")
                continue
            poll_df = (
                pd.DataFrame(list(ranks.items()), columns=["Team", "Rank"])
                .sort_values("Rank")
                .reset_index(drop=True)
            )
            poll_df["Logo"] = poll_df["Team"].map(lambda t: ctx.logos.get(t, ""))
            poll_df = poll_df[["Logo", "Rank", "Team"]]
            st.dataframe(
                poll_df, use_container_width=True, hide_index=True, height=min(50 + 35 * len(poll_df), 600),
                column_config={"Logo": st.column_config.ImageColumn("", width="small")},
            )

    st.markdown("---")
    st.markdown("### 📈 Best & Worst Against the Spread")
    st.caption(f"{ctx.year} real ATS record (CFBD-graded, not a model output) · "
               "ranked by average cover margin, the size of the beat/miss vs. the closing line, not just win/loss.")

    # get_teams_ats has no classification filter either (same situation as player
    # season stats) — filter to FBS using the team names already fetched for logos.
    fbs_ats_teams = set(ctx.logos.keys()) or set(ctx.ats_records.keys())
    ats_rows = [
        {"Team": team, "Record": model.ats_record_str(team, ctx.ats_records),
         "Games": r["games"], "Avg Cover Margin": r["avg_cover_margin"]}
        for team, r in ctx.ats_records.items()
        if r["avg_cover_margin"] is not None and team in fbs_ats_teams
    ]
    if not ats_rows:
        st.info("No ATS records available for this year yet — check back once games have been played.")
    else:
        ats_df = (
            pd.DataFrame(ats_rows)
            .sort_values("Avg Cover Margin", ascending=False)
            .reset_index(drop=True)
        )
        ats_df["Logo"] = ats_df["Team"].map(lambda t: ctx.logos.get(t, ""))
        ats_df = ats_df[["Logo", "Team", "Record", "Games", "Avg Cover Margin"]]
        ats_col_config = {"Logo": st.column_config.ImageColumn("", width="small")}
        ats_cols = st.columns(2)
        with ats_cols[0]:
            st.markdown("**Best ATS**")
            st.dataframe(ats_df.head(10), use_container_width=True, hide_index=True, column_config=ats_col_config)
        with ats_cols[1]:
            st.markdown("**Worst ATS**")
            st.dataframe(ats_df.tail(10).sort_values("Avg Cover Margin"), use_container_width=True,
                         hide_index=True, column_config=ats_col_config)
