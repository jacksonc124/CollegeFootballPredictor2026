"""Tab 5: Model Accuracy — verified (logged-pick) accuracy, trends, markets, maintenance,
and the separate (biased) tier calibration check."""

import pandas as pd
import streamlit as st

import backtest
import model
import pick_log
from ui_helpers import outcome_row_css


def render(ctx):
    st.markdown("## 📊 Model Accuracy")

    st.markdown("### ✅ Verified Accuracy (Logged Picks)")
    st.caption("Only picks explicitly logged *before* their games were played — unlike the tier "
               "calibration check below, this has no look-ahead bias. It's the real record, but it "
               "only covers whatever's been logged via the 📌 Log Picks button on the Pick'em tab.")

    logged_df = pick_log.load_log()
    manual_records = pick_log.load_manual_records()
    if logged_df.empty:
        graded_log = logged_df
        log_acc = {"n": 0, "wins": 0, "losses": 0, "win_rate": None}
        week_record = pick_log.summarize_by_week(graded_log)
        all_slates = pd.DataFrame(columns=["year", "week", "season_type"])
    else:
        with st.spinner("Grading logged picks against final scores…"):
            graded_log = pick_log.grade_logged_picks(ctx.bearer_token)
        log_acc = backtest.overall_accuracy(graded_log)
        # This log is never cleared — a new slate gets auto-logged every time the "current
        # week" changes, so these numbers are a running total across every slate ever
        # logged, not just the current week's ~50 games. Surfacing the slate count here
        # (instead of leaving people to infer it from "92 seems like a lot") makes that
        # explicit instead of reading like a possible bug.
        week_record = pick_log.summarize_by_week(graded_log)
        all_slates = logged_df[["year", "week", "season_type"]].drop_duplicates().sort_values(
            ["year", "week"], na_position="first"
        )

    manual_wins = int(manual_records["wins"].sum()) if not manual_records.empty else 0
    manual_losses = int(manual_records["losses"].sum()) if not manual_records.empty else 0
    total_wins = log_acc["wins"] + manual_wins
    total_losses = log_acc["losses"] + manual_losses
    total_n = total_wins + total_losses
    total_slates = len(week_record) + len(manual_records)

    if total_n == 0:
        st.info("No picks logged yet, and no remembered record entered below. Use the 📌 Log Picks "
                "button on the Pick'em tab each week to start building a real track record.")
    else:
        lg1, lg2, lg3, lg4 = st.columns(4)
        lg1.metric("Logged Picks Graded", total_n)
        lg2.metric("Win Rate", f"{total_wins / total_n:.1%}")
        lg3.metric("Wins / Losses", f"{total_wins} / {total_losses}")
        lg4.metric("Slates Logged", total_slates)
        note = f" (including {len(manual_records)} manually-recorded slate(s))" if not manual_records.empty else ""
        st.caption(f"Cumulative across {total_slates} logged slate(s){note} — see Record by week below "
                   f"for the per-slate breakdown.")

    if not logged_df.empty:
        st.markdown("#### Game-by-game results")
        st.caption("Pick a logged slate to see exactly which games the model got right.")
        slate_options = list(all_slates.itertuples(index=False, name=None))

        def _format_slate(opt):
            yr, wk, stype = opt
            week_label = f"Week {int(wk)}" if pd.notna(wk) else "Postseason"
            return f"{int(yr)} {week_label} ({stype.title()})"

        selected_slate = st.selectbox(
            "Slate", options=slate_options, format_func=_format_slate,
            index=len(slate_options) - 1, key="game_results_slate",  # default to the most recently logged slate
        )
        sel_year, sel_week, sel_season_type = selected_slate
        week_mask = graded_log["week"].isna() if pd.isna(sel_week) else graded_log["week"] == sel_week
        slate_games = graded_log[
            (graded_log["year"] == sel_year) & week_mask & (graded_log["season_type"] == sel_season_type)
        ].sort_values("cover_prob", ascending=False).copy()

        def _result_str(r):
            if pd.isna(r["home_points"]):
                return "—"
            return f"{r['home_team']} {int(r['home_points'])}-{int(r['away_points'])} {r['away_team']}"

        outcome_labels = {"win": "✅ Win", "loss": "❌ Loss", "push": "🟰 Push"}
        slate_games["Home Logo"] = slate_games["home_team"].map(lambda t: ctx.logos.get(t, ""))
        slate_games["Away Logo"] = slate_games["away_team"].map(lambda t: ctx.logos.get(t, ""))
        slate_games["Result"] = slate_games.apply(_result_str, axis=1)
        slate_games["Outcome"] = slate_games["outcome"].map(lambda o: outcome_labels.get(o, "⏳ Pending"))

        mark = {"win": "✅", "loss": "❌", "push": "🟰"}

        def _total_str(r):
            if not r["total_pick"] or pd.isna(r["total_pick"]):
                return ""
            return f"{r['total_pick'].title()} {r['market_total']:g} {mark.get(r['total_outcome'], '⏳')}"

        def _ml_str(r):
            if not r["ml_pick_team"] or pd.isna(r["ml_pick_team"]):
                return ""
            odds = f" ({r['ml_odds']:+.0f})" if pd.notna(r["ml_odds"]) else ""
            return f"{r['ml_pick_team']}{odds} {mark.get(r['ml_outcome'], '⏳')}"

        slate_games["Total"] = slate_games.apply(_total_str, axis=1)
        slate_games["Moneyline"] = slate_games.apply(_ml_str, axis=1)

        game_display = slate_games.rename(columns={
            "home_team": "Home", "away_team": "Away",
            "market_spread_home": "Market Spread", "pick_team": "Pick", "tier": "Tier",
        })[["Home Logo", "Home", "Away Logo", "Away", "Market Spread", "Pick", "Tier", "Result", "Outcome",
            "Total", "Moneyline"]]

        def _shade_outcome_row(row):
            return [outcome_row_css(slate_games.loc[row.name, "outcome"])] * len(row)

        st.dataframe(
            game_display.style.apply(_shade_outcome_row, axis=1),
            use_container_width=True, hide_index=True,
            column_config={
                "Home Logo": st.column_config.ImageColumn("", width="small"),
                "Away Logo": st.column_config.ImageColumn("", width="small"),
                "Market Spread": st.column_config.NumberColumn("Market Spread", format="%+.1f"),
            },
        )

    st.markdown("---")
    st.markdown("### 📅 Trends")

    if total_n > 0 or not manual_records.empty:
        st.markdown("#### Record by week")
        st.caption("Every logged slate, win/loss record once results are in — 'Pending' means it's "
                   "logged but the games haven't finished yet. A row with no real games behind it "
                   "(marked below) came from a manually-entered record instead.")
        # Built from logged_df (not logged_weeks()'s list-of-tuples helper) so the merge
        # key columns share the exact same dtypes as week_record's — both ultimately trace
        # back to the same load_log() call, avoiding a None-vs-NaN dtype mismatch on the
        # "week" column (None for postseason) that a fresh tuple-derived DataFrame risks.
        weeks_display = all_slates.merge(week_record, on=["year", "week", "season_type"], how="left")
        if not weeks_display.empty:
            # .apply(axis=1) on an empty DataFrame returns the frame unchanged (not a
            # Series), which breaks the assignment below — happens here whenever there are
            # no real logged slates yet and this section is only showing manual records.
            weeks_display["Record"] = weeks_display.apply(
                lambda r: f"{int(r['wins'])}-{int(r['losses'])}" if pd.notna(r["wins"]) else "Pending", axis=1,
            )
        # Slates with only a remembered total, no real per-game rows at all — these are
        # never merged into a real slate's numbers (that would double-count if the real
        # log ever catches up), they're additional rows of their own.
        manual_only_rows = pd.DataFrame()
        if not manual_records.empty:
            existing_keys = set(zip(all_slates["year"], all_slates["week"], all_slates["season_type"]))
            manual_only_rows = manual_records[
                ~manual_records.apply(lambda r: (r["year"], r["week"], r["season_type"]) in existing_keys, axis=1)
            ].copy()
            manual_only_rows["Record"] = (
                manual_only_rows["wins"].astype(str) + "-" + manual_only_rows["losses"].astype(str) + " *"
            )
            manual_only_rows["win_rate"] = manual_only_rows["wins"] / (manual_only_rows["wins"] + manual_only_rows["losses"])
            weeks_display = pd.concat([weeks_display, manual_only_rows], ignore_index=True)
        weeks_display = weeks_display.sort_values(["year", "week"], na_position="first").rename(
            columns={"year": "Year", "week": "Week", "season_type": "Season Type", "win_rate": "Win Rate"}
        )
        st.dataframe(
            weeks_display[["Year", "Week", "Season Type", "Record", "Win Rate"]],
            use_container_width=True, hide_index=True,
            column_config={"Win Rate": st.column_config.ProgressColumn("Win Rate", min_value=0.0, max_value=1.0)},
        )
        if not manual_only_rows.empty:
            st.caption("\\* Manually recorded — no per-game detail, so it won't appear in Game-by-game results.")

    st.markdown("---")
    st.markdown("### 💰 Markets")

    if not logged_df.empty:
        st.markdown("#### Totals & moneyline accuracy")
        totals_all = backtest.summarize_market(graded_log, "total_outcome")
        ml_all = backtest.summarize_market(graded_log, "ml_outcome")
        if totals_all.empty and ml_all.empty:
            st.caption("No graded totals or moneyline picks yet. These are only recorded for slates "
                       "logged from now on (older slates were logged spread-only, and can't be filled "
                       "in after kickoff without hindsight) — they'll show up here once those games finish.")
        else:
            def _rec(df_):
                if df_.empty:
                    return "—", "—"
                r = df_.iloc[0]
                push = f"-{int(r['pushes'])}" if r["pushes"] else ""
                rate = f"{r['win_rate']:.1%}" if pd.notna(r["win_rate"]) else "—"
                return f"{int(r['wins'])}-{int(r['losses'])}{push}", rate

            tot_rec, tot_rate = _rec(totals_all)
            ml_rec, ml_rate = _rec(ml_all)
            ml_units = graded_log["ml_profit"].dropna().sum() if "ml_profit" in graded_log else 0.0
            tm1, tm2, tm3 = st.columns(3)
            tm1.metric("Over/Under Record", tot_rec, tot_rate, delta_color="off")
            tm2.metric("Moneyline Record", ml_rec, ml_rate, delta_color="off")
            tm3.metric("Moneyline Units (1u flat)", f"{ml_units:+.2f}")
            st.caption("Over/under and moneyline picks logged pre-kickoff, graded on final scores. "
                       "Moneyline win rate alone can mislead (heavy favorites win often but pay little), "
                       "so units shows profit at the logged price on a flat 1-unit bet.")

            tier_totals = backtest.summarize_market(graded_log, "total_outcome", "total_tier")
            strong = graded_log[graded_log["ml_edge"].fillna(0) >= model.ML_EDGE_THRESHOLD]
            ml_strong = backtest.summarize_market(strong, "ml_outcome")
            bt1, bt2 = st.columns(2)
            with bt1:
                if not tier_totals.empty:
                    st.caption("Over/under by tier")
                    tier_totals = tier_totals.assign(win_rate=tier_totals["win_rate"] * 100)
                    st.dataframe(
                        tier_totals.rename(columns={"total_tier": "Tier", "wins": "W", "losses": "L",
                                                    "pushes": "P", "win_rate": "Win Rate"}),
                        use_container_width=True, hide_index=True,
                        column_config={"Win Rate": st.column_config.NumberColumn(format="%.1f%%")},
                    )
            with bt2:
                if not ml_strong.empty:
                    s_rec, s_rate = _rec(ml_strong)
                    st.caption(f"Moneyline, strong edge only (≥{model.ML_EDGE_THRESHOLD:.0%}): {s_rec} ({s_rate})")

        st.markdown("#### Closing Line Value (CLV)")
        st.caption("Did the logged spread beat where the market actually closed? This is the standard "
                   "sharp-betting signal for real edge — win rate alone is noisy over a season, but "
                   "consistently beating the close isn't. Only covers picks logged after CLV tracking "
                   "was added and whose game's closing line was actually captured pre-kickoff (see the "
                   "scheduled capture_closing_lines job) — older picks show no CLV, not zero CLV.")
        clv_summary = backtest.summarize_clv(graded_log)
        if clv_summary["n"] == 0:
            st.caption("No picks with a captured closing line yet.")
        else:
            cv1, cv2 = st.columns(2)
            cv1.metric("Avg CLV", f"{clv_summary['avg_clv']:+.2f} pts", help="Positive means the logged "
                       "number was better, on average, than where the line closed.")
            cv2.metric("Beat the Close", f"{clv_summary['positive_rate']:.1%}",
                      help=f"Share of {clv_summary['n']} picks with positive CLV.")

    st.markdown("---")
    st.markdown("### 🛠️ Maintenance")

    with st.expander("➕ Record a remembered result for a slate with no per-game detail"):
        st.caption("For a slate whose logged picks were lost (e.g. to a disk reset) before anyone "
                   "backed them up. This is saved on the server alongside the log itself, so — "
                   "unlike Favorite Team above — everyone visiting the app sees it too. It carries "
                   "the same reboot risk as the log, for the same reason: there's nowhere else to "
                   "put it without adding real external storage.")
        mc1, mc2, mc3, mc4, mc5 = st.columns([1, 1, 1, 1, 1])
        with mc1:
            manual_year = st.number_input("Year", min_value=2000, max_value=2030, value=ctx.year, key="manual_record_year")
        with mc2:
            manual_postseason = st.checkbox("Postseason", key="manual_record_postseason")
        with mc3:
            manual_week = st.number_input("Week", min_value=1, max_value=15, value=1,
                                           disabled=manual_postseason, key="manual_record_week")
        with mc4:
            manual_wins_in = st.number_input("Wins", min_value=0, step=1, key="manual_record_wins")
        with mc5:
            manual_losses_in = st.number_input("Losses", min_value=0, step=1, key="manual_record_losses")
        manual_season_type = "postseason" if manual_postseason else "regular"
        manual_week_val = None if manual_postseason else int(manual_week)
        save_col, del_col = st.columns(2)
        with save_col:
            if st.button("Save remembered record", key="save_manual_record"):
                pick_log.add_manual_record(int(manual_year), manual_week_val, manual_season_type,
                                            int(manual_wins_in), int(manual_losses_in))
                pick_log.sync_to_supabase(ctx.supabase_url, ctx.supabase_key)
                st.success(f"Saved {manual_wins_in}-{manual_losses_in} for {int(manual_year)} "
                           f"{'Postseason' if manual_postseason else f'Week {manual_week}'}.")
                st.rerun()
        with del_col:
            if st.button("Remove this slate's remembered record", key="delete_manual_record"):
                pick_log.delete_manual_record(int(manual_year), manual_week_val, manual_season_type)
                pick_log.sync_to_supabase(ctx.supabase_url, ctx.supabase_key)
                st.rerun()
        if not manual_records.empty:
            st.caption("Currently recorded: " + ", ".join(
                f"{int(r.year)} {'Postseason' if pd.isna(r.week) else f'Week {int(r.week)}'} ({r.season_type}): "
                f"{int(r.wins)}-{int(r.losses)}"
                for r in manual_records.itertuples()
            ))

    def _read_and_validate_log_csv(uploaded_file):
        """Guard against a malformed or wrong-shaped upload corrupting the shared pick log."""
        max_bytes = 5 * 1024 * 1024
        if uploaded_file.size > max_bytes:
            return None, f"File is too large ({uploaded_file.size / 1024:.0f} KB) — max is 5 MB."
        try:
            df = pd.read_csv(uploaded_file)
        except Exception as e:
            return None, f"Couldn't read that as a CSV: {e}"
        missing = set(pick_log.LOG_COLUMNS) - set(df.columns)
        if missing:
            return None, f"Missing required column(s): {', '.join(sorted(missing))}."
        return df, None

    st.markdown("#### Backup / restore log")
    if ctx.supabase_url and ctx.supabase_key:
        st.caption("✅ Auto-syncing to Supabase — this log survives a redeploy. "
                   "The controls below still work the same for manual backups or a full restore.")
    else:
        st.caption("⚠️ This log lives on the app's local disk and is **not** persisted externally — a "
                   "redeploy pulls a fresh container and wipes it. Download periodically to keep a "
                   "permanent record, and restore after a reset. Add SUPABASE_URL/SUPABASE_KEY secrets "
                   "to make this automatic instead.")
    bk_col1, bk_col2, bk_col3 = st.columns(3)
    with bk_col1:
        st.download_button("⬇️ Download Log (CSV)", data=logged_df.to_csv(index=False),
                           file_name="pick_log.csv", mime="text/csv", disabled=logged_df.empty)
    with bk_col2:
        uploaded_log = st.file_uploader("⬆️ Replace Log (CSV)", type="csv", key="restore_log_upload",
                                         help="Overwrites the entire log with this file — anything logged "
                                              "since isn't kept. Use Merge instead unless you specifically "
                                              "want to discard what's currently logged.")
        if uploaded_log is not None:
            restored_df, error = _read_and_validate_log_csv(uploaded_log)
            if error:
                st.error(f"Couldn't replace the log: {error}")
            else:
                pick_log.restore_log(restored_df)
                pick_log.sync_to_supabase(ctx.supabase_url, ctx.supabase_key)
                st.success("Log replaced — reload the page to see it reflected.")
    with bk_col3:
        uploaded_merge = st.file_uploader("⬆️ Merge Log (CSV)", type="csv", key="merge_log_upload",
                                           help="Adds this file's picks alongside whatever's already "
                                                "logged, instead of replacing it — for reconstructing a "
                                                "lost slate (e.g. from an old picks export re-graded "
                                                "against results) without losing anything logged since. "
                                                "A slate that's already logged is safely deduplicated.")
        if uploaded_merge is not None:
            merge_df, error = _read_and_validate_log_csv(uploaded_merge)
            if error:
                st.error(f"Couldn't merge the log: {error}")
            else:
                pick_log.merge_log(merge_df)
                pick_log.sync_to_supabase(ctx.supabase_url, ctx.supabase_key)
                st.success("Log merged — reload the page to see it reflected.")

    st.markdown("---")
    # Deliberately small and below Verified Accuracy: this used to show a full win-rate/
    # record breakdown, but that number is inflated by look-ahead bias in a way CFBD's data
    # makes unfixable (see the warning below) — an impressive-looking but wrong number is
    # worse than none at all in a betting context. What survives that bias reasonably well
    # is the *relative* question "does higher confidence actually track with better
    # results", so that's all this shows. The real, unbiased accuracy is Verified Accuracy
    # above — this stays secondary, both in position and size.
    st.markdown("#### 🎯 Tier Calibration Check")
    st.caption("Does higher confidence (Tier A) actually track with better results than lower "
               "confidence (Tier C)? Not a real accuracy number — see why below.")
    st.warning(
        "⚠️ **Look-ahead bias.** CFBD's SP+ ratings are one value per team per *year* — the "
        "fully-converged, end-of-season rating — not what was knowable the week a game was "
        "actually played. Grading past weeks with it means the 'prediction' already reflects "
        "games that hadn't happened yet, which inflates the numbers below. There's no clean fix "
        "(CFBD doesn't expose historical weekly snapshots), so treat this as a rough directional "
        "check — does Tier A actually beat Tier C — not a performance claim.",
        icon="⚠️",
    )

    if "accuracy_loaded_year" not in st.session_state:
        st.session_state["accuracy_loaded_year"] = None
    is_loaded = st.session_state["accuracy_loaded_year"] == ctx.year

    if not is_loaded:
        st.info(f"Checks every completed week of {ctx.year} — up to ~3× the API calls the rest of the "
                f"app uses combined. Cached afterward (6 hours), so this only costs quota once per season.")
        if st.button("🔄 Run Calibration Check", key="run_accuracy", type="primary"):
            st.session_state["accuracy_loaded_year"] = ctx.year
            st.rerun()
    else:
        with st.spinner("Backtesting every completed week of the season…"):
            graded = ctx.get_season_backtest(ctx.year)

        if graded.empty:
            st.info("No completed games with results yet for this season.")
        else:
            tier_summary = backtest.summarize_by_tier(graded)
            st.dataframe(
                tier_summary.rename(columns={
                    "tier": "Tier", "n": "N", "wins": "Wins",
                    "avg_predicted_cover_prob": "Predicted Cover Prob", "actual_win_rate": "Actual Win Rate",
                }),
                use_container_width=True, hide_index=True,
                column_config={
                    "Predicted Cover Prob": st.column_config.ProgressColumn("Predicted Cover Prob", min_value=0.0, max_value=1.0),
                    "Actual Win Rate": st.column_config.ProgressColumn("Actual Win Rate", min_value=0.0, max_value=1.0),
                },
            )
