"""
Fetches this app's CBS Sports Pick'em pool's games via CBS's own GraphQL API
(picks.cbssports.com/graphql), authenticated with a session cookie copied from your
browser rather than a stored username/password — see README for how to get one, and how
to get CBS_POOL_ID/CBS_ENTRY_ID (both visible in the pool's URL).

The query text below (FootballPickemManagerPicksPage) and the response shape it's parsed
against were both reverse-engineered from a real HAR capture of the pool's "Make Picks"
page — CBS has no public docs for this API, so this is unofficial and could break if CBS
changes their schema. fetch_pool_games() surfaces CBS's own GraphQL error messages (e.g.
an expired cookie) rather than a generic failure, specifically so that's easy to diagnose
if it ever stops working.

NOT LIVE-TESTED: built from a captured request/response, not verified against a live call
(this environment has no network access to cbssports.com). The parsing functions
(extract_pool_games, match_team_name, match_pool_games_to_df) are pure and unit-tested;
fetch_pool_games itself — the actual network call — isn't, and may need a round of
debugging against what CBS actually returns.
"""

import difflib

import requests

GRAPHQL_URL = "https://picks.cbssports.com/graphql"

# Captured verbatim from the pool's "Make Picks" page (see module docstring). Sent as a
# normal ad-hoc query (not CBS's own Apollo persisted-query hash, which we don't have and
# can't compute ourselves) — this works as long as CBS's GraphQL server accepts ad-hoc
# queries at all, which most Apollo servers do unless explicitly locked to APQ-only.
QUERY = (
    "query FootballPickemManagerPicksPage($poolId:ID!$entryId:ID!$poolPeriodId:ID"
    "$returnUpToCurrent:Boolean){commonPool(id:$poolId){id name season{id year}"
    "...on FootballPickemManagerPool{gameInstanceUid isUsingSpread areGamesAvailable "
    "canSelectCustomGames parentPoolId hasEnded entryTiebreakerQuestions{id key label "
    "seasonId}poolPeriod(poolPeriodId:$poolPeriodId){id order isPlayOff isCurrent "
    "poolEvents{id cbsEventId awayTeamId awayTeamScore awayTeam{id cbsTeamId abbrev "
    "colorHexDex colorPrimaryHex colorSecondaryHex mediumName nickName shortName "
    "sportType location losses ties wins imageUrl rank}homeTeamId homeTeamScore "
    "homeTeamSpread(input:{poolId:$poolId})homeTeam{id cbsTeamId abbrev colorHexDex "
    "colorPrimaryHex colorSecondaryHex mediumName nickName shortName sportType location "
    "losses ties wins imageUrl rank}cbsEventId gameStatus gameStatusDesc gametrackerLink "
    "isLocked markedFinalAt possession seasonType sportType tiebreakerOrder extra{id "
    "homeTeamRank awayTeamRank homeTeamPickemPercentOwned awayTeamPickemPercentOwned "
    "homeTeamPickemPercentOwnedAgainstSpread awayTeamPickemPercentOwnedAgainstSpread "
    "gameTitle}oddsMarket(input:{poolId:$poolId}){id bookUsed{id name displayName}"
    "moneyLines{id isDrawVersion odds oddsTrend selectionId openingOdds teamId}"
    "spreads{id odds oddsTrend openingOdds openingSpread selectionId spread teamId}"
    "totals{choice id odds oddsTrend openingOdds openingTotal selectionId total}}"
    "tvInfoName tvNetworks{callLetters countryName id name}timeRemaining gamePeriod "
    "weekNumber winningTeamId startsAt ticketInfo{id url price}highlightsUrl}}"
    "poolPeriods(returnUpToCurrent:$returnUpToCurrent){id description isCurrent order}"
    "poolSettings{id gamesPerPeriod showPickPercentages tiebreaker{totalScore}"
    "weights{weightingOption}openInvites startWeek}myMembership{id isManager}"
    "myEntries{id name}}}commonEntry(id:$entryId){...on FootballPickemEntry{id name "
    "avatarUrl gameInstanceUid url userId picksCount maxPicksCount parentEntryId "
    "pickStatus memberId isMine tiebreakerStatus entryPicks(input:"
    "{poolPeriodId:$poolPeriodId}){id itemId poolPeriodId slotId weight cbsItemId "
    "cbsSlotId spread{id spread spreadForItemId spreadBook}}"
    "defaultAvailableWeights(poolPeriodId:$poolPeriodId)"
    "entryTiebreakersAnswers(input:{poolPeriodId:$poolPeriodId}){id "
    "tiebreakerQuestionId value poolPeriodId}}}}"
)


def fetch_pool_games(cookie: str, pool_id: str, entry_id: str,
                     pool_period_id: str | None = None, timeout: int = 15) -> dict:
    """
    POST the FootballPickemManagerPicksPage query to CBS's GraphQL API and return the
    "data" object from the response. pool_period_id=None asks CBS for its own notion of
    the current period (matches what the real page requests on load).

    Raises requests.HTTPError on a non-2xx HTTP response, or RuntimeError if the response
    is 200 but the GraphQL layer itself reports errors (e.g. an expired/invalid cookie,
    or a wrong pool_id/entry_id) — surfacing CBS's own error text rather than failing
    silently or generically, since this integration is unofficial and the clearest
    signal when it breaks is what CBS itself says went wrong.
    """
    payload = {
        "operationName": "FootballPickemManagerPicksPage",
        "variables": {
            "poolId": pool_id, "entryId": entry_id,
            "poolPeriodId": pool_period_id, "returnUpToCurrent": True,
        },
        "query": QUERY,
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    }
    resp = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    if body.get("errors"):
        raise RuntimeError(f"CBS GraphQL error: {body['errors']}")
    return body.get("data") or {}


def extract_pool_games(graphql_data: dict) -> list[dict]:
    """
    Flatten the raw GraphQL response down to just what this app needs per game:
    {"home_team": str|None, "away_team": str|None, "home_spread": float|None,
    "game_status": str|None, "starts_at": int|None (epoch ms), "week_number": int|None}.
    Uses each team's mediumName (CBS's closest equivalent to CFBD's plain school name,
    e.g. "South Alabama", "Marshall") for later matching against this app's own team names.
    """
    pool = graphql_data.get("commonPool") or {}
    period = pool.get("poolPeriod") or {}
    events = period.get("poolEvents") or []
    games = []
    for e in events:
        home = e.get("homeTeam") or {}
        away = e.get("awayTeam") or {}
        games.append({
            "home_team": home.get("mediumName"),
            "away_team": away.get("mediumName"),
            "home_spread": e.get("homeTeamSpread"),
            "game_status": e.get("gameStatus"),
            "starts_at": e.get("startsAt"),
            "week_number": e.get("weekNumber"),
        })
    return games


def _strip_trailing_qualifier(name: str) -> str:
    """"Miami (Fla.)" -> "Miami" — CBS disambiguates some schools with a trailing
    parenthetical that CFBD's plain name doesn't carry (CFBD's bare "Miami" already means
    the Florida one; only the Ohio one gets its own qualified CFBD name)."""
    return name.split("(")[0].strip() if "(" in name else name


def _is_abbreviation_of(cbs_token: str, known_token: str) -> bool:
    """Whether a CBS token (e.g. "St", "App", "W") is a plausible abbreviation of a known
    full-name token (e.g. "State", "Appalachian", "Western") — true if it's an exact match
    or a case-insensitive prefix of it. Covers CBS's common media-style abbreviations
    ("Iowa St." for "Iowa State", "App. St." for "Appalachian State", "W. Kentucky" for
    "Western Kentucky") without needing a hardcoded lookup table of every school CBS
    might abbreviate this way."""
    cbs_token, known_token = cbs_token.lower(), known_token.lower()
    return cbs_token == known_token or known_token.startswith(cbs_token)


def _tokens_abbreviate(cbs_name: str, known_name: str) -> bool:
    """Whether every token of cbs_name is a plausible abbreviation of the corresponding
    token of known_name, in order (same token count required) — see _is_abbreviation_of."""
    cbs_tokens = cbs_name.replace(".", "").split()
    known_tokens = known_name.replace(".", "").split()
    if len(cbs_tokens) != len(known_tokens):
        return False
    return all(_is_abbreviation_of(c, k) for c, k in zip(cbs_tokens, known_tokens))


def match_team_name(cbs_name: str | None, known_names) -> str | None:
    """
    Best-effort match of a CBS team name (mediumName, e.g. "South Alabama") to one of
    this app's own team names (CFBD naming, e.g. model.get_team_logos()/get_sp_ratings()
    keys). Tries, in order: an exact match (the common case); stripping a trailing
    parenthetical qualifier CBS adds but CFBD doesn't ("Miami (Fla.)" -> "Miami"); CBS's
    common media-style abbreviations ("Iowa St." -> "Iowa State", "App. St." ->
    "Appalachian State"); and finally a close fuzzy match for anything else minor.
    Returns None rather than guessing when nothing is close enough to trust.
    """
    if not cbs_name:
        return None
    if cbs_name in known_names:
        return cbs_name

    stripped = _strip_trailing_qualifier(cbs_name)
    if stripped != cbs_name and stripped in known_names:
        return stripped

    for known in known_names:
        if _tokens_abbreviate(stripped, known):
            return known

    close = difflib.get_close_matches(cbs_name, known_names, n=1, cutoff=0.8)
    return close[0] if close else None


def match_pool_games_to_df(pool_games: list[dict], df, known_team_names):
    """
    Cross-reference CBS pool games against the model's picks DataFrame by team name.

    Returns (matched_df, unmatched_games): matched_df is df filtered to only the rows
    whose (home_team, away_team) both matched a CBS pool game — the model's own
    cover_prob/tier/pick_team etc. are kept as-is, CBS is only used to decide *which*
    games are actually in the pool. unmatched_games lists the raw CBS game dicts that
    couldn't be confidently matched to any row in df (e.g. a name CFBD and CBS spell
    differently, or a game the model doesn't have a line for yet), so the UI can flag
    those explicitly instead of silently dropping them.
    """
    matched_pairs = set()
    unmatched = []
    for g in pool_games:
        home = match_team_name(g.get("home_team"), known_team_names)
        away = match_team_name(g.get("away_team"), known_team_names)
        if home and away:
            matched_pairs.add((home, away))
        else:
            unmatched.append(g)

    if df.empty:
        return df, unmatched
    mask = df.apply(lambda r: (r["home_team"], r["away_team"]) in matched_pairs, axis=1)
    return df[mask].copy(), unmatched
