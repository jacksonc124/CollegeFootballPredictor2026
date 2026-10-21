"""Tab 2: Team Parlays — ATS/moneyline leg pool combined into ranked parlay combos."""

import itertools

import streamlit as st

import model
from ui_helpers import build_parlay_leg_pool


@st.fragment
def render(ctx):
    df_inner = ctx.df
    st.markdown("## 🎰 Team Parlays")
    st.caption("Combined prob = product of leg probabilities · Payout uses each leg's real odds "
               "(−110 assumed for ATS/O-U, actual moneyline for ML legs)")
    st.caption("⚠️ Each combo uses at most one leg per game (no stacking an ATS and moneyline pick on "
               "the same matchup), but legs from *different* games are still assumed independent — "
               "correlated results (e.g. conference-wide trends) aren't modeled.")

    def dec_legs():
        if st.session_state["parlay_legs"] > 2:
            st.session_state["parlay_legs"] -= 1

    def inc_legs():
        if st.session_state["parlay_legs"] < 6:
            st.session_state["parlay_legs"] += 1

    col_minus, col_display, col_plus = st.columns([1, 1, 1])
    with col_minus:
        st.button("−", key="legs_minus", on_click=dec_legs,
                  use_container_width=True, disabled=(st.session_state["parlay_legs"] <= 2))
    with col_display:
        st.markdown(
            f'<div class="leg-display">{st.session_state["parlay_legs"]}</div>'
            f'<div class="leg-label">LEGS</div>',
            unsafe_allow_html=True,
        )
    with col_plus:
        st.button("+", key="legs_plus", on_click=inc_legs,
                  use_container_width=True, disabled=(st.session_state["parlay_legs"] >= 6))

    with st.expander("⚙️ Customize"):
        cc1, cc2 = st.columns(2)
        with cc1:
            include_types = st.multiselect("Bet Types", ["ATS", "ML"], default=["ATS", "ML"],
                                            key="parlay_bet_types")
            ats_tiers = st.multiselect("ATS Tiers", ["A", "B", "C"], default=["A", "B"],
                                        help="Tier C picks have a smaller edge/lower cover probability — "
                                             "riskier legs than the default A/B.",
                                        key="parlay_ats_tiers")
        with cc2:
            ml_edge_pct = st.slider("Min Moneyline Edge", min_value=0, max_value=30,
                                     value=int(model.ML_EDGE_THRESHOLD * 100), step=1, format="%d%%",
                                     help="Model win probability minus the market's vig-removed "
                                          "implied probability. Lower = more moneyline legs qualify.",
                                     key="parlay_ml_edge_pct")
            min_payout = st.number_input("Minimum Payout", min_value=1.0, max_value=50.0, value=1.0, step=0.5,
                                          help="Hide any combo paying out less than this multiplier.",
                                          key="parlay_min_payout")

    leg_count = st.session_state["parlay_legs"]
    # Deliberately wider than just the safest legs — sorting by probability alone and
    # taking a small pool meant every parlay ended up all heavy-favorite moneylines,
    # since those have the highest individual probability by construction. A wider pool
    # keeps some higher-variance, higher-payout legs in the mix (see the two sections
    # below: "Safest" vs. "Higher Payout").
    pool_size = leg_count + 12

    leg_pool = build_parlay_leg_pool(df_inner, tuple(ats_tiers), ml_edge_pct / 100)
    if include_types:
        leg_pool = leg_pool[leg_pool["leg_type"].isin(include_types)]
    else:
        leg_pool = leg_pool.iloc[0:0]
    parlay_pool = leg_pool.sort_values("leg_prob", ascending=False).head(pool_size).reset_index(drop=True)

    if len(parlay_pool) < leg_count:
        st.info(f"Not enough qualifying picks for a {leg_count}-leg parlay with the current filters. "
                f"Try reducing legs, widening ATS Tiers, or lowering Min Moneyline Edge.")
        return

    probs = parlay_pool["leg_prob"].to_numpy()
    decimal_odds = parlay_pool["leg_odds"].map(model.american_to_decimal_odds).to_numpy()
    games = list(zip(parlay_pool["home_team"], parlay_pool["away_team"]))

    parlay_rows = []
    for c in itertools.combinations(range(len(parlay_pool)), leg_count):
        if len({games[i] for i in c}) != leg_count:
            continue  # one leg per game
        joint_prob = 1.0
        payout = 1.0
        for i in c:
            joint_prob *= probs[i]
            payout *= decimal_odds[i]
        if payout < min_payout:
            continue
        parlay_rows.append({"joint_prob": round(joint_prob, 4), "payout": round(payout, 2),
                             "legs": parlay_pool.iloc[list(c)]})

    if not parlay_rows:
        st.info(f"No {leg_count}-leg combos meet the current filters (try lowering Minimum Payout, "
                f"reducing legs, or widening ATS Tiers / Min Moneyline Edge).")
        return

    def render_parlay_cards(rows, title, subtitle):
        st.markdown(f"#### {title}")
        st.caption(subtitle)
        all_html = ""
        for i, p in enumerate(rows[:5]):
            legs_html = ""
            for _, leg in p["legs"].iterrows():
                legs_html += (
                    f'<div class="parlay-leg">'
                    f'{ctx.logo_img(leg["leg_team"], 20)}&nbsp;<b>{leg["leg_label"]}</b>'
                    f'&nbsp;<span style="opacity:0.5">({model.rank_badge(leg["away_team"], ctx.rankings)}{leg["away_team"]} @ '
                    f'{model.rank_badge(leg["home_team"], ctx.rankings)}{leg["home_team"]})</span>'
                    f'&nbsp;&middot;&nbsp;Prob: <b style="color:#38bdf8">{leg["leg_prob"]:.1%}</b>'
                    f'&nbsp;&middot;&nbsp;{leg["leg_detail"]}'
                    f'</div>'
                )
            all_html += (
                f'<div class="parlay-card">'
                f'<div class="parlay-title">Parlay #{i + 1}'
                f'&nbsp;<span style="font-size:14px;opacity:0.5;font-family:\'IBM Plex Mono\',monospace;">'
                f'{leg_count}-leg</span></div>'
                f'{legs_html}'
                f'<div class="parlay-prob">'
                f'Combined Probability: {p["joint_prob"]:.1%}'
                f'&nbsp;&middot;&nbsp;Est. Payout: ~{p["payout"]}x'
                f'</div></div>'
            )
        st.markdown(all_html, unsafe_allow_html=True)

    safest = sorted(parlay_rows, key=lambda x: x["joint_prob"], reverse=True)
    riskiest = sorted(parlay_rows, key=lambda x: x["payout"], reverse=True)

    render_parlay_cards(safest, "🛡️ Safest", "Highest combined probability")
    st.markdown("---")
    render_parlay_cards(riskiest, "🎲 Higher Payout", "Highest payout among the same qualifying picks — "
                                                       "lower probability, bigger swing if it hits")
