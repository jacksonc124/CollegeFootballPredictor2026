"""
Builds and sends the weekly Top 12 picks message to a Discord channel via an incoming
webhook (Server Settings -> Integrations -> Webhooks -> New Webhook -> copy URL). Message
building (build_top12_embed) is pure and separated from the network call (send_webhook)
so the formatting is unit-testable without hitting Discord. See
scripts/send_discord_picks.py for the actual weekly orchestration, and this repo's
.github/workflows/send_weekly_picks.yml for the schedule.
"""

import pandas as pd
import requests

# Matches this app's ACCENT color (see ui_helpers.py) so the embed's side bar reads as
# "this app," not a generic Discord blue.
DISCORD_COLOR = 0x38BDF8

# Discord hard-caps embeds at 25 fields; the Top 12 never gets close, but this keeps a
# caller's bug (accidentally passing the full slate instead of the top 12) from making
# Discord reject the whole message instead of just overflowing visually.
MAX_FIELDS = 25


def _pick_field(rank: int, row) -> dict:
    # A missing market spread comes through itertuples() as NaN (pandas' float
    # placeholder for a None in a numeric column), not None — `is not None` alone would
    # format it as the literal string "nan" instead of catching it.
    spread = row.market_spread_home
    spread_str = f"{spread:+.1f}" if pd.notna(spread) else "—"
    return {
        "name": f"#{rank}  {row.away_team} @ {row.home_team}  ·  Tier {row.tier}",
        "value": (f"Pick: **{row.pick_team}**  ·  Cover {row.cover_prob:.0%}  ·  "
                  f"Spread {spread_str}  ·  Edge {row.edge_points:+.1f}"),
        "inline": False,
    }


def build_top12_embed(top12_df, season_label: str, cbs_status: str | None = None,
                       cookie_warning: str | None = None) -> dict:
    """
    top12_df: the already-resolved, already-ranked Top 12 rows (see
    cbs_pickem.resolve_top12_source for how that resolution happens), with columns
    home_team/away_team/tier/pick_team/cover_prob/edge_points/market_spread_home.
    season_label: e.g. "2026 · Week 9". cbs_status/cookie_warning are optional one-line
    captions (CBS-pool-filtering status, cookie-expiry warning) shown above the picks
    when present — same captions the Pick'em tab shows, so a Discord reader sees the
    same caveats a Streamlit viewer would. Returns a Discord webhook JSON payload — see
    https://discord.com/developers/docs/resources/webhook#execute-webhook.
    """
    description_lines = [line for line in (cbs_status, cookie_warning) if line]

    fields = [_pick_field(i, row) for i, row in
              enumerate(top12_df.itertuples(index=False), start=1)][:MAX_FIELDS]

    embed = {
        "title": f"🏈 Top 12 ATS Picks — {season_label}",
        "color": DISCORD_COLOR,
        "fields": fields,
        "footer": {"text": "CFB SP+ Model · Not betting advice"},
    }
    if description_lines:
        embed["description"] = "\n".join(description_lines)

    return {"username": "CFB Picks Model", "embeds": [embed]}


def send_webhook(payload: dict, webhook_url: str, timeout: float = 15) -> None:
    """POSTs payload to a Discord incoming webhook URL. Raises on a non-2xx response
    (requests.Response.raise_for_status) — same error-surfacing convention as
    pick_log.py's Supabase calls, so a bad/revoked webhook fails loudly in the GitHub
    Action's logs instead of silently doing nothing."""
    resp = requests.post(webhook_url, json=payload, timeout=timeout)
    resp.raise_for_status()
