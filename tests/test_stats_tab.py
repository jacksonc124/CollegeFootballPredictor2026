from tabs.stats import _candidate_blurb, _national_leaders


def _passing(player, team, yds, td):
    return [
        {"player": player, "team": team, "position": "QB", "stat_type": "YDS", "stat": str(yds)},
        {"player": player, "team": team, "position": "QB", "stat_type": "TD", "stat": str(td)},
    ]


def _receiving(player, team, yds, td):
    return [
        {"player": player, "team": team, "position": "WR", "stat_type": "YDS", "stat": str(yds)},
        {"player": player, "team": team, "position": "WR", "stat_type": "TD", "stat": str(td)},
    ]


def test_national_leaders_picks_the_real_top_player_per_category():
    passing_stats = _passing("QB1", "A", 3000, 25) + _passing("QB2", "B", 2000, 15)
    receiving_stats = _receiving("WR1", "C", 1200, 12)

    leaders = _national_leaders(passing_stats, [], receiving_stats)

    assert leaders["pass_yds"] == "QB1"
    assert leaders["pass_td"] == "QB1"
    assert leaders["rec_yds"] == "WR1"
    assert leaders["rec_td"] == "WR1"
    assert "rush_yds" not in leaders  # no rushing rows at all


def test_candidate_blurb_cites_a_real_national_lead():
    row = {
        "player": "WR1", "team": "C", "pass_yds": 0, "pass_td": 0,
        "rush_yds": 0, "rush_td": 0, "rec_yds": 1200, "rec_td": 12,
        "total_yards": 1200, "total_td": 12, "games": 8, "score_per_game": 100.0,
    }
    blurb = _candidate_blurb(row, {"rec_yds": "WR1", "rec_td": "WR1"})
    assert "National leader in Receiving Yards, Receiving TDs." in blurb
    assert "1200 total yards" in blurb
    assert "through 8 games" in blurb


def test_candidate_blurb_omits_lead_claim_when_not_actually_leading():
    row = {
        "player": "WR2", "team": "D", "pass_yds": 0, "pass_td": 0,
        "rush_yds": 0, "rush_td": 0, "rec_yds": 800, "rec_td": 6,
        "total_yards": 800, "total_td": 6, "games": 7, "score_per_game": 80.0,
    }
    blurb = _candidate_blurb(row, {"rec_yds": "SomeoneElse"})
    assert "National leader" not in blurb


def test_candidate_blurb_mentions_dual_threat_secondary_category():
    row = {
        "player": "QB1", "team": "A", "pass_yds": 2500, "pass_td": 20,
        "rush_yds": 400, "rush_td": 5, "rec_yds": 0, "rec_td": 0,
        "total_yards": 2900, "total_td": 25, "games": 9, "score_per_game": 150.0,
    }
    blurb = _candidate_blurb(row, {})
    assert "plus 400 rushing yards" in blurb


def test_candidate_blurb_skips_dual_threat_when_secondary_is_minor():
    row = {
        "player": "QB1", "team": "A", "pass_yds": 2500, "pass_td": 20,
        "rush_yds": 50, "rush_td": 1, "rec_yds": 0, "rec_td": 0,
        "total_yards": 2550, "total_td": 21, "games": 9, "score_per_game": 150.0,
    }
    blurb = _candidate_blurb(row, {})
    assert "plus" not in blurb
