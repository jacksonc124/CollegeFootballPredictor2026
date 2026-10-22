import pandas as pd

from discord_notify import MAX_FIELDS, build_top12_embed


def _top12_df():
    return pd.DataFrame([
        {"home_team": "Oklahoma", "away_team": "New Mexico", "tier": "A", "pick_team": "New Mexico",
         "cover_prob": 0.67, "edge_points": 5.8, "market_spread_home": -22.5},
        {"home_team": "Miss. State", "away_team": "South Carolina", "tier": "A", "pick_team": "South Carolina",
         "cover_prob": 0.66, "edge_points": 5.4, "market_spread_home": None},
    ])


def test_build_top12_embed_shape():
    payload = build_top12_embed(_top12_df(), "2026 · Week 9")
    assert payload["username"] == "CFB Picks Model"
    assert len(payload["embeds"]) == 1
    embed = payload["embeds"][0]
    assert embed["title"] == "🏈 Top 12 ATS Picks — 2026 · Week 9"
    assert "description" not in embed  # no cbs_status/cookie_warning given
    assert len(embed["fields"]) == 2


def test_build_top12_embed_field_content():
    embed = build_top12_embed(_top12_df(), "2026 · Week 9")["embeds"][0]
    first = embed["fields"][0]
    assert first["name"] == "#1  New Mexico @ Oklahoma  ·  Tier A"
    assert "Pick: **New Mexico**" in first["value"]
    assert "Cover 67%" in first["value"]
    assert "Spread -22.5" in first["value"]
    assert "Edge +5.8" in first["value"]


def test_build_top12_embed_handles_missing_spread():
    embed = build_top12_embed(_top12_df(), "2026 · Week 9")["embeds"][0]
    second = embed["fields"][1]
    assert "Spread —" in second["value"]


def test_build_top12_embed_includes_status_and_warning_as_description():
    embed = build_top12_embed(
        _top12_df(), "2026 · Week 9",
        cbs_status="🔒 Filtered to your 2-game CBS pool (Week 9).",
        cookie_warning="⚠️ Your CBS session cookie expires in 3 day(s)...",
    )["embeds"][0]
    assert "Filtered to your 2-game CBS pool" in embed["description"]
    assert "expires in 3 day(s)" in embed["description"]


def test_build_top12_embed_truncates_to_max_fields():
    rows = [
        {"home_team": f"Home{i}", "away_team": f"Away{i}", "tier": "A", "pick_team": f"Away{i}",
         "cover_prob": 0.6, "edge_points": 3.0, "market_spread_home": -3.0}
        for i in range(MAX_FIELDS + 5)
    ]
    embed = build_top12_embed(pd.DataFrame(rows), "2026 · Week 9")["embeds"][0]
    assert len(embed["fields"]) == MAX_FIELDS
