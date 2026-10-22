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

Confirmed working against a live pool (14/17 games matched automatically; the other 3
needed match_team_name's abbreviation handling, since added). This module still can't be
exercised from this development environment itself (no network access to cbssports.com),
so changes here are necessarily unverified until tried against the real API. The parsing
functions
(extract_pool_games, match_team_name, match_pool_games_to_df) are pure and unit-tested;
fetch_pool_games itself — the actual network call — isn't, and may need a round of
debugging against what CBS actually returns.
"""

import base64
import difflib
import json
from datetime import datetime, timezone

import requests

import pick_log

# Path (within pick_log's shared app_files table) the CBS cookie is stored under when
# saved via the in-app "Replace CBS cookie" form — see load_cookie_from_supabase's
# docstring for why this exists.
COOKIE_STORAGE_PATH = "cbs_cookie.txt"

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


def resolve_top12_source(df, known_team_names, fetch_pool_games):
    """
    Decide which DataFrame the Top 12 should be ranked from: the user's actual CBS
    Pick'em pool (df filtered to just those games) when reachable, falling back to the
    full slate otherwise — CBS erroring out, returning no games, or matching nothing in
    this slate are all equally valid reasons to fall back, not failures to surface as
    broken. Shared by the Streamlit Pick'em tab (via a cached fetch_pool_games) and the
    standalone weekly-push script (a direct, uncached call), so both pick the same
    source with the same fallback logic instead of two copies that could drift apart.

    fetch_pool_games is a zero-arg callable returning a list of pool game dicts (already
    run through extract_pool_games), or raising on failure. Returns (df, status,
    unmatched): status is a short caption describing which mode is active, and unmatched
    lists any pool game that couldn't be matched to a model row (only meaningful when
    the pool mode is actually active).
    """
    try:
        pool_games = fetch_pool_games()
    except Exception as e:
        return df, f"⚠️ Couldn't reach your CBS pool ({e}) — showing the full-slate Top 12 instead.", []

    if not pool_games:
        return (df, "⚠️ CBS returned no games for this pool's current period — "
                "showing the full-slate Top 12 instead.", [])

    matched_df, unmatched = match_pool_games_to_df(pool_games, df, known_team_names)
    if matched_df.empty:
        return (df, "⚠️ None of your pool's games matched this slate — showing the "
                "full-slate Top 12 instead.", [])

    week_number = next((g["week_number"] for g in pool_games if g.get("week_number")), None)
    week_str = f" (Week {week_number})" if week_number else ""
    status = f"🔒 Filtered to your {len(matched_df)}-game CBS pool{week_str}."
    return matched_df, status, unmatched


def _decode_jwt_payload(token: str) -> dict:
    """
    Decode a JWT's payload with NO signature verification. Safe here specifically because
    this only ever reads CBS_COOKIE — a secret the app already trusts completely (it's
    used to authenticate as the user) — purely to read its own "exp" claim for an expiry
    warning; it is never used to verify or trust a token from anyone else. Returns {} if
    the token isn't shaped like a JWT or its payload isn't valid JSON.
    """
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return {}


def cookie_expiry(cookie: str) -> datetime | None:
    """
    Best-effort expiry time for the CBS_COOKIE secret, read from its auth_state cookie's
    own JWT "exp" claim. Returns None if auth_state isn't present in the cookie string or
    its payload doesn't parse as expected — kept distinct from "already expired" so
    cookie_expiry_warning() can tell "unknown" apart from "about to expire."
    """
    for part in cookie.split(";"):
        name, _, value = part.strip().partition("=")
        if name == "auth_state":
            exp = _decode_jwt_payload(value).get("exp")
            if isinstance(exp, (int, float)):
                return datetime.fromtimestamp(exp, tz=timezone.utc)
    return None


def cookie_expiry_warning(cookie: str, now: datetime | None = None, warn_within_days: int = 5) -> str | None:
    """
    A short warning message if CBS_COOKIE's session is already expired or will expire
    within warn_within_days, else None. Returns None (no warning) when the expiry can't be
    determined at all, rather than treating "unknown" the same as "about to expire" — an
    unusual cookie shape isn't the same situation as an imminent failure.
    """
    expiry = cookie_expiry(cookie)
    if expiry is None:
        return None
    now = now or datetime.now(tz=timezone.utc)
    days_left = (expiry - now).days
    if days_left < 0:
        return "❌ Your CBS session cookie has expired — grab a fresh one (see README)."
    if days_left < warn_within_days:
        when = "within a day" if days_left == 0 else f"in {days_left} day(s)"
        return f"⚠️ Your CBS session cookie expires {when} — grab a fresh one soon (see README)."
    return None


def load_cookie_from_supabase(supabase_url: str, supabase_key: str) -> str | None:
    """
    The CBS session cookie, if one's been saved via the in-app "Replace CBS cookie" form
    (see tabs/pickem.py) — reused by both app.py (overriding the CBS_COOKIE secret when
    present) and the weekly Discord push's script, off the same Supabase-backed store
    pick_log.py already uses for the pick log. This is what makes replacing an expired
    cookie a one-paste action in the running app instead of editing secrets.toml and
    redeploying, or separately updating a GitHub Actions secret for the Discord push.

    Returns None if Supabase isn't configured, or nothing's been saved yet (the caller
    falls back to the CBS_COOKIE secret in that case) — non-fatal on any failure
    (network, bad key), same as pick_log.sync_from_supabase's own reasoning.
    """
    if not (supabase_url and supabase_key):
        return None
    try:
        return pick_log.get_synced_file(COOKIE_STORAGE_PATH, supabase_url, supabase_key)
    except Exception as e:
        print(f"Warning: failed to load CBS cookie from Supabase: {e}")
        return None


def save_cookie_to_supabase(cookie: str, supabase_url: str, supabase_key: str) -> None:
    """
    Saves a freshly-copied CBS cookie to Supabase so both the Streamlit app (next rerun)
    and the weekly Discord push (next run) pick it up immediately — no redeploy, no
    separate GitHub secret update. Raises on failure (network, bad key) so the in-app
    form can show a real error instead of silently not saving.
    """
    pick_log.put_synced_file(COOKIE_STORAGE_PATH, cookie, supabase_url, supabase_key)
