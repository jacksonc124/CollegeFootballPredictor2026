# CFB SP+ vs Market Spread Model

This script builds weekly college football against-the-spread (ATS) picks by comparing SP+ ratings to market point spreads from the CollegeFootballData (CFBD) API. It:

- Downloads and caches SP+ team ratings.
- Downloads and caches weekly betting lines.
- Computes a model spread (SP+ + home-field).
- Computes the edge vs. the market and implied cover probabilities.
- Prints ranked picks and saves them to CSV.

---

## Requirements

- Python 3.10+ (for type hints like `list[str]` and `int | None`)
- CFBD Python client
- pandas
- streamlit (for the `app.py` dashboard)

Install dependencies (in a virtual environment — see note below):

```bash
python -m venv .venv
.venv\Scripts\activate   # or: source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
```

> **Use a virtual environment.** The `cfbd` package requires `pydantic<2`, which will
> conflict with (and silently downgrade) a global environment that has `pydantic>=2`
> installed for other tools — breaking them. A project-local `.venv` keeps `cfbd`'s
> pydantic 1.x install isolated from everything else on your machine.

You'll also need a CFBD API bearer token (get one at [collegefootballdata.com](https://collegefootballdata.com/key)):

- For `cfbpredict.py`, set the `BEARER_TOKEN` environment variable.
- For `app.py` (Streamlit), either set `BEARER_TOKEN` as an environment variable, or add it to `.streamlit/secrets.toml`:

```toml
BEARER_TOKEN = "your-token-here"
```

### Optional: persistent pick log (Supabase)

The pick log (`pick_log.py`) normally lives only on local disk, which a Streamlit Cloud
redeploy wipes. To make it survive redeploys, create a free project at
[supabase.com](https://supabase.com), run `supabase/schema.sql` once in that project's SQL
Editor, then add these secrets:

```toml
SUPABASE_URL = "https://your-project-ref.supabase.co"
SUPABASE_KEY = "your-service-role-key"   # Settings -> API -> service_role key
```

Absent entirely, the app works exactly as before (local-disk-only). See pick_log.py's
`sync_from_supabase`/`sync_to_supabase` for how this is used.

### Optional: Closing Line Value (CLV) tracking

Requires the Supabase setup above (there'd be nothing to update otherwise). A scheduled
GitHub Action (`.github/workflows/capture_closing_lines.yml`, runs every 30 minutes) records
each logged pick's closing market spread, so the Model Accuracy tab can show whether the
model's picks actually beat the market's closing number — a stronger signal than win rate
alone. To enable it, add these as **repository secrets** (Settings → Secrets and variables →
Actions — separate from the Streamlit secrets above, since this runs outside Streamlit):

- `BEARER_TOKEN` (same CFBD token)
- `SUPABASE_URL` / `SUPABASE_KEY` (same Supabase project)

### Optional: filter picks to your actual CBS Pick'em pool

The Pick'em tab's Top 12 is ranked across the whole week's slate, but a CBS Sports
Pick'em pool is usually a subset of it (e.g. 17 of ~60 games) — some of those Top 12
picks might not even be games you can pick in your pool. This section (`cbs_pickem.py`)
filters the list down to just your pool's actual games, using CBS's own (undocumented)
GraphQL API authenticated with a session cookie copied from your browser — not your
CBS username/password.

To set it up:

1. Open your pool's "Make Picks" page in a browser, logged in.
2. Open DevTools (F12) → **Network tab**, reload the page, and click the request to
   `picks.cbssports.com/football/pickem/pools/...` (the main page document).
3. Click **Headers** → scroll to **Request Headers** → copy the full value of the
   `cookie:` line.
4. Your pool ID and entry ID are both in that page's URL:
   `.../pools/<CBS_POOL_ID>?entryId=<CBS_ENTRY_ID>`

Add all three as secrets:

```toml
CBS_COOKIE = "your-full-cookie-header-value"
CBS_POOL_ID = "your-pool-id"
CBS_ENTRY_ID = "your-entry-id"
```

This cookie is a session token, not your password — it expires (roughly a month, in
practice) and you'll need to repeat steps 1-3 to get a fresh one when it does. Absent
entirely, the Pick'em tab works exactly as before (full-slate Top 12 only).

**This integration is unofficial** — CBS has no public API docs for this, so it was
built by reverse-engineering a real captured request (see `cbs_pickem.py`'s module
docstring) and may break if CBS changes their page. If it stops working, the error
message shown in the app (or CBS's own GraphQL error text) is the best starting point
for fixing it.

Run the dashboard with:

```bash
streamlit run app.py
```

## Project layout

- `model.py` — shared fetchers (SP+ ratings, betting lines, team logos), math helpers, and pick-building logic used by both entry points below.
- `app.py` — Streamlit dashboard orchestrator (secrets, sidebar, fetch/filter pipeline, tab dispatch).
- `ui_helpers.py` — pure presentation helpers (formatting, CSS, the parlay leg-pool builder) shared across `tabs/`.
- `tabs/` — one module per dashboard tab (Today's Games, Pick'em, Parlays, Moneylines & O/U, Rankings & ATS, Model Accuracy, Stats).
- `cbs_pickem.py` — optional CBS Pick'em pool integration (see above).
- `cfbpredict.py` — CLI script that prints picks and saves them to CSV.
- `backtest.py` — grades a past week's picks against actual final scores and reports accuracy/calibration by tier. Run with `python backtest.py <year> <week> [season_type]`.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```
